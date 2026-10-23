import csv
import io
import json
import os
import re
import secrets
import threading
import time
import uuid
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session, g, redirect, send_file
from sqlalchemy import select, func, update, text
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException, Forbidden, NotFound, Conflict
from werkzeug.security import generate_password_hash, check_password_hash
from models import connect, User, Order, Plan, PlanOrder, Setting, Event, Proof, Parcel, now
from routing import plan, order_data, location, DEFAULT_DEPOT
from permissions import ROLES, TABS, PUBLIC, allowed
from operations import register_operations, save_parcel, enrich

ROOT = Path(__file__).parent
ACTIVE = ['assigned', 'picked_up', 'delivering', 'failed']
STATUSES = dict(pending='Chờ phân công', assigned='Đã phân công', picked_up='Đã lấy hàng', delivering='Đang giao', delivered='Đã giao', failed='Giao thất bại', cancelled='Đã hủy',returning='Đang chuyển hoàn',returned='Đã hoàn về kho')


def uid():
    return str(uuid.uuid4())


def person(u):
    return dict(id=u.id, username=u.username, name=u.name, role=u.role, active=u.active, phone=u.phone, vehicle=u.vehicle, must_change_password=u.must_change_password)


def order_json(o):
    return {k: getattr(o, k) for k in ['id', 'code', 'name', 'phone', 'address', 'lat', 'lon', 'note', 'service_minutes', 'cod', 'cod_collected', 'status', 'shipper_id', 'created_by', 'failure_reason', 'version', 'created', 'updated']}


def password_ok(p):
    if not isinstance(p, str) or not 8 <= len(p) <= 128:
        raise ValueError('Mật khẩu cần từ 8 đến 128 ký tự.')


def create_app(test_url=None, testing=False):
    load_dotenv(ROOT / '.env')
    app = Flask(__name__)
    secret_path = ROOT / 'instance' / '.session-key'
    if testing:
        secret = 'test-only-session-secret'
    else:
        secret_path.parent.mkdir(exist_ok=True)
        if not secret_path.exists():
            try:
                with secret_path.open('x') as f:
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        secret = os.environ.get('SECRET_KEY') or secret_path.read_text().strip()
    app.config.update(SECRET_KEY=secret, TESTING=testing, MAX_CONTENT_LENGTH=4*1024*1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1')
    if test_url and not testing:
        raise ValueError('Database kiểm thử chỉ được dùng khi testing=True.')
    engine, Store = connect(test_url)
    app.extensions['store'] = Store
    app.extensions['engine'] = engine
    with Store.begin() as s:
        if not s.get(Setting, 1):
            s.add(Setting(id=1, data=json.dumps(DEFAULT_DEPOT)))
    bootstrap_lock = threading.Lock()
    attempts, attempt_lock = {}, threading.Lock()

    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    @app.before_request
    def auth():
        g.user = None
        if session.get('uid'):
            with Store() as s:
                u = s.get(User, session['uid'])
                if u and u.active and u.role in ROLES and u.auth_version == session.get('auth_version'):
                    g.user = person(u)
                else:
                    session.clear()
        if not request.path.startswith('/api/'):
            return
        if request.method not in ['GET', 'HEAD', 'OPTIONS']:
            if not session.get('csrf') or not secrets.compare_digest(session['csrf'], request.headers.get('X-CSRF-Token', '')):
                return jsonify(error='Phiên làm việc đã thay đổi. Tải lại trang rồi thử lại.'), 403
        public = ['/api/me', '/api/login', '/api/setup', '/api/register']
        if request.path not in public and not g.user:
            return jsonify(error='Vui lòng đăng nhập.'), 401
        if g.user and g.user['must_change_password'] and request.path not in ['/api/me', '/api/password', '/api/logout']:
            return jsonify(error='Cần đổi mật khẩu tạm trước khi sử dụng.', require_password_change=True), 403
        if request.endpoint not in PUBLIC and g.user and not allowed(g.user['role'],request.endpoint,request.method,request.view_args):
            return jsonify(error='Vai trò của bạn không được phép sử dụng chức năng này.'), 403

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        if request.path.startswith('/api/') or request.path in ['/', '/login']:
            response.headers['Cache-Control'] = 'no-store'
        return response

    def admin(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not g.user or g.user['role'] != 'admin':
                raise Forbidden('Chức năng dành cho Admin.')
            return fn(*args, **kwargs)
        return wrapper

    def visible_order(s, ident):
        o = s.get(Order, ident)
        owns = o and ((g.user['role']=='customer' and o.created_by==g.user['id']) or (g.user['role']=='staff' and o.shipper_id==g.user['id']))
        if not o or (g.user['role'] != 'admin' and not owns):
            raise NotFound('Không tìm thấy đơn hàng trong phạm vi được phân công.')
        return o

    def visible_plan(s, ident):
        p = s.get(Plan, ident)
        if not p or (g.user['role'] != 'admin' and p.shipper_id != g.user['id']):
            raise NotFound('Không tìm thấy chuyến trong phạm vi được phân công.')
        return p

    def active_plan(s, order_id):
        return s.scalar(select(PlanOrder.id).where(PlanOrder.order_id == order_id, PlanOrder.active == True))

    def event(s, order_id, action):
        s.add(Event(id=uid(), order_id=order_id, actor_id=g.user['id'], action=action[:500]))

    def change_order(s, o, values, expected):
        if type(expected) is not int or expected != o.version:
            raise Conflict('Đơn vừa được cập nhật. Tải lại trước khi sửa.')
        changed = s.execute(update(Order).where(Order.id == o.id, Order.version == expected).values(**values, version=expected+1, updated=now()).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise Conflict('Đơn vừa được cập nhật ở phiên khác.')

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        if isinstance(exc, IntegrityError):
            return jsonify(error='Dữ liệu trùng hoặc đơn đã thuộc một chuyến khác. Hãy tải lại.'), 409
        if isinstance(exc, (ValueError, KeyError, TypeError, OverflowError)):
            return jsonify(error=str(exc)), 400
        app.logger.exception('Request failed')
        return jsonify(error='Không thể xử lý yêu cầu. Kiểm tra nhật ký máy chủ.'), 500

    @app.get('/')
    def index():
        return render_template('index.html') if g.user else redirect('/login')

    @app.get('/login')
    @app.get('/register')
    def login_page():
        return redirect('/') if g.user else render_template('login.html')

    @app.get('/api/me')
    def me():
        with Store() as s:
            needs_setup = s.scalar(select(func.count()).select_from(User)) == 0
        return jsonify(user=g.user, csrf=csrf(), needs_setup=needs_setup,
                       permissions=dict(tabs=TABS[g.user['role']],operations=sorted(ROLES[g.user['role']])) if g.user else None,
                       database='Microsoft SQL Server' if engine.dialect.name == 'mssql' else 'SQLite chỉ dùng kiểm thử')

    @app.post('/api/setup')
    @app.post('/api/register')
    def setup():
        d = request.get_json()
        username = str(d.get('username', '')).strip().lower()
        if not re.fullmatch(r'[a-z0-9_.-]{3,60}', username):
            raise ValueError('Tên đăng nhập: 3–60 ký tự a-z, số, dấu chấm, gạch ngang/gạch dưới.')
        password_ok(d.get('password'))
        is_registration = request.path == '/api/register'
        if is_registration and d.get('password_confirm') != d['password']:
            raise ValueError('Hai mật khẩu không khớp.')
        name = username if is_registration else str(d.get('name', '')).strip()[:150] or username
        with bootstrap_lock, Store.begin() as s:
            if engine.dialect.name == 'mssql':
                s.execute(text("DECLARE @r int; EXEC @r = sp_getapplock @Resource='GiaoGonBootstrap', @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=5000; IF @r < 0 THROW 50001, 'Bootstrap locked', 1;"))
            existing_count = s.scalar(select(func.count()).select_from(User))
            if existing_count and not is_registration:
                raise Conflict('Đã có tài khoản Admin. Không thể tạo lại qua bước khởi tạo.')
            if s.scalar(select(User.id).where(User.username == username)):
                raise Conflict('Tên đăng nhập đã tồn tại. Chọn tên khác.')
            role = 'customer' if existing_count else 'admin'
            s.add(User(id=uid(), username=username, name=name, password_hash=generate_password_hash(d['password']), role=role))
        return jsonify(ok=True, role=role), 201

    @app.post('/api/login')
    def login():
        key = request.remote_addr
        with attempt_lock:
            recent = [x for x in attempts.get(key, []) if time.monotonic()-x < 300]
            attempts[key] = recent
            if len(recent) >= 10:
                return jsonify(error='Thử đăng nhập quá nhiều lần. Vui lòng chờ 5 phút.'), 429
        d = request.get_json()
        with Store() as s:
            u = s.scalar(select(User).where(User.username == str(d.get('username', '')).strip().lower()))
            if not u or not u.active or not check_password_hash(u.password_hash, str(d.get('password', ''))):
                with attempt_lock:
                    attempts.setdefault(key, []).append(time.monotonic())
                return jsonify(error='Sai tài khoản/mật khẩu hoặc tài khoản đã bị khóa.'), 401
            session.clear()
            session.update(uid=u.id, auth_version=u.auth_version)
            payload = person(u)
        with attempt_lock:
            attempts.pop(key, None)
        return jsonify(user=payload, csrf=csrf())

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post('/api/password')
    def password():
        d = request.get_json()
        password_ok(d.get('new_password'))
        with Store.begin() as s:
            u = s.get(User, g.user['id'])
            if not check_password_hash(u.password_hash, str(d.get('old_password', ''))):
                raise ValueError('Mật khẩu hiện tại không đúng.')
            if check_password_hash(u.password_hash, d['new_password']):
                raise ValueError('Mật khẩu mới cần khác mật khẩu cũ.')
            u.password_hash = generate_password_hash(d['new_password'])
            u.must_change_password = False
            u.auth_version += 1
            session['auth_version'] = u.auth_version
        return jsonify(ok=True)

    @app.put('/api/profile')
    def profile():
        d = request.get_json()
        with Store.begin() as s:
            u = s.get(User, g.user['id'])
            u.phone = str(d.get('phone', ''))[:30]
            u.vehicle = str(d.get('vehicle', ''))[:100]
        return jsonify(ok=True)

    @app.route('/api/users', methods=['GET', 'POST'])
    @admin
    def users():
        with Store.begin() as s:
            if request.method == 'GET':
                return jsonify([person(u) for u in s.scalars(select(User).order_by(User.created))])
            d = request.get_json()
            username = str(d.get('username', '')).strip().lower()
            if not re.fullmatch(r'[a-z0-9_.-]{3,60}', username) or not str(d.get('name', '')).strip():
                raise ValueError('Nhập họ tên và tên đăng nhập hợp lệ (3–60 ký tự).')
            password_ok(d.get('password'))
            role = d.get('role','staff')
            if role not in ['staff','customer']:
                raise ValueError('Chỉ tạo tài khoản Nhân viên hoặc Khách hàng.')
            u = User(id=uid(), username=username, name=str(d['name']).strip()[:150], password_hash=generate_password_hash(d['password']), role=role, must_change_password=True, phone=str(d.get('phone', ''))[:30], vehicle=str(d.get('vehicle', ''))[:100])
            s.add(u)
            s.flush()
            return jsonify(person(u)), 201

    @app.patch('/api/users/<ident>')
    @admin
    def update_user(ident):
        with Store.begin() as s:
            u = s.get(User, ident)
            if not u or u.role not in ['staff','customer']:
                raise NotFound('Không tìm thấy tài khoản.')
            d = request.get_json()
            if 'name' in d:
                name = str(d['name']).strip()
                if not name or len(name)>150:
                    raise ValueError('Họ tên cần từ 1 đến 150 ký tự.')
                u.name = name
            if 'phone' in d:
                u.phone = str(d['phone'])[:30]
            if 'vehicle' in d:
                u.vehicle = str(d['vehicle'])[:100]
            if 'active' in d:
                if type(d['active']) is not bool:
                    raise ValueError('Trạng thái tài khoản không hợp lệ.')
                if not d['active'] and s.scalar(select(Plan.id).where(Plan.shipper_id == ident, Plan.status.in_(['planned', 'in_progress']))):
                    raise Conflict('Nhân viên đang có chuyến chưa kết thúc. Hoàn tất/hủy chuyến trước khi khóa.')
                u.active = d['active']
                u.auth_version += 1
            if d.get('password'):
                password_ok(d['password'])
                u.password_hash = generate_password_hash(d['password'])
                u.must_change_password = True
                u.auth_version += 1
        return jsonify(ok=True)

    def dashboard_data(s):
        q=select(Order)
        start=request.args.get('from','')
        end=request.args.get('to','')
        try:
            first=date.fromisoformat(start) if start else None
            last=date.fromisoformat(end) if end else None
        except ValueError:
            raise ValueError('Ngày lọc phải có định dạng YYYY-MM-DD.')
        if first and last and first>last:
            raise ValueError('Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.')
        if first:q=q.where(Order.created>=first.isoformat())
        if last:q=q.where(Order.created<(last+timedelta(days=1)).isoformat())
        orders=list(s.scalars(q))
        counts={status:sum(o.status==status for o in orders) for status in STATUSES}
        users=list(s.scalars(select(User).where(User.role=='staff').order_by(User.name)))
        employees=[]
        for u in users:
            subset=[o for o in orders if o.shipper_id==u.id]
            employees.append(dict(id=u.id,name=u.name,active=u.active,vehicle=u.vehicle,phone=u.phone,total=len(subset),delivered=sum(o.status=='delivered' for o in subset),failed=sum(o.status=='failed' for o in subset),cod_collected=sum(o.cod for o in subset if o.cod_collected),cod_outstanding=sum(o.cod for o in subset if not o.cod_collected and o.status not in ['cancelled','returning','returned'])))
        events=s.execute(select(Event,Order.code,User.name).join(Order,Event.order_id==Order.id).join(User,Event.actor_id==User.id).order_by(Event.created.desc()).limit(20)).all()
        return dict(from_date=start,to_date=end,total=len(orders),counts=counts,success_rate=round(100*counts['delivered']/len(orders),1) if orders else 0,cod_collected=sum(o.cod for o in orders if o.cod_collected),cod_outstanding=sum(o.cod for o in orders if not o.cod_collected and o.status not in ['cancelled','returning','returned']),active_trips=s.scalar(select(func.count()).select_from(Plan).where(Plan.status.in_(['planned','in_progress']))),employees=employees,events=[dict(action=e.action,order_code=code,actor=name,created=e.created) for e,code,name in events])

    @app.get('/api/admin/dashboard')
    @admin
    def dashboard():
        with Store() as s:
            return jsonify(dashboard_data(s))

    @app.get('/api/admin/report.csv')
    @admin
    def admin_report():
        with Store() as s:data=dashboard_data(s)
        f=io.StringIO();w=csv.writer(f)
        w.writerow(['Tu ngay UTC',data['from_date'] or 'Tat ca','Den ngay UTC',data['to_date'] or 'Tat ca'])
        w.writerow(['Nhan vien','Hoat dong','Tong don','Da giao','That bai','COD da thu','COD chua thu'])
        for u in data['employees']:
            name=u['name'];name="'"+name if name.startswith(('=','+','-','@','\t','\r')) else name
            w.writerow([name,u['active'],u['total'],u['delivered'],u['failed'],u['cod_collected'],u['cod_outstanding']])
        return send_file(io.BytesIO(f.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name='bao-cao-quan-tri.csv')

    @app.post('/api/admin/bulk-assign')
    @admin
    def bulk_assign():
        d=request.get_json();items=d.get('orders')
        if not isinstance(items,list) or not 1<=len(items)<=100:
            raise ValueError('Chọn 1–100 đơn để phân công.')
        ids=[item['id'] for item in items]
        if len(set(ids))!=len(ids):raise ValueError('Danh sách đơn bị trùng.')
        with Store.begin() as s:
            employee=s.get(User,d.get('shipper_id'))
            if not employee or not employee.active or employee.role!='staff':
                raise ValueError('Chọn nhân viên đang hoạt động.')
            for item in items:
                o=visible_order(s,item['id'])
                if o.status not in ['pending','assigned','failed'] or active_plan(s,o.id):
                    raise Conflict('Có đơn đang giao hoặc thuộc chuyến. Chưa phân công bất kỳ đơn nào.')
                change_order(s,o,dict(shipper_id=employee.id,status='assigned',failure_reason=''),item.get('version'))
                event(s,o.id,'Phân công hàng loạt cho '+employee.name)
        return jsonify(count=len(items))

    @app.get('/api/state')
    def state():
        with Store() as s:
            q = select(Order).order_by(Order.created.desc())
            if g.user['role'] == 'customer':
                q = q.where(Order.created_by == g.user['id'])
            elif g.user['role'] != 'admin':
                q = q.where(Order.shipper_id == g.user['id'])
            orders = [order_json(o) for o in s.scalars(q.limit(1000))]
            for o in orders:enrich(s,o)
            if g.user['role']=='admin':
                owners={o['created_by'] for o in orders if o['created_by']}
                names=dict(s.execute(select(User.id,User.name).where(User.id.in_(owners))).all()) if owners else {}
                for o in orders:o['creator_name']=names.get(o['created_by'],'')
            active_ids = set(s.scalars(select(PlanOrder.order_id).where(PlanOrder.active == True)))
            for o in orders:
                o['in_active_plan'] = o['id'] in active_ids
            employees = [person(u) for u in s.scalars(select(User).where(User.role == 'staff'))] if g.user['role'] == 'admin' else ([g.user] if g.user['role']=='staff' else [])
            return jsonify(depot=json.loads(s.get(Setting, 1).data), orders=orders, employees=employees, user=g.user, stats=dict(total=len(orders), delivered=sum(o['status']=='delivered' for o in orders), failed=sum(o['status']=='failed' for o in orders), cod_collected=sum(o['cod'] for o in orders if o['cod_collected']), cod_outstanding=sum(o['cod'] for o in orders if not o['cod_collected'] and o['status'] not in ['cancelled','returning','returned'])))

    @app.put('/api/depot')
    @admin
    def depot():
        p = location(request.get_json())
        with Store.begin() as s:
            s.get(Setting, 1).data = json.dumps(p)
        return jsonify(p)

    def values(d):
        p = order_data(d)
        p['phone'] = str(d.get('phone', ''))[:30]
        cod = float(d.get('cod', 0))
        if not cod.is_integer() or not 0 <= cod <= 1_000_000_000:
            raise ValueError('COD là số tiền nguyên từ 0 đến 1 tỷ đồng.')
        p['cod'] = int(cod)
        return p

    def add_order(s, d):
        shipper_id = d.get('shipper_id') or None
        if shipper_id:
            u = s.get(User, shipper_id)
            if not u or not u.active or u.role != 'staff':
                raise ValueError('Nhân viên được chọn không hợp lệ.')
        o = Order(id=uid(), code='GH'+uuid.uuid4().hex[:10].upper(), **values(d), created_by=g.user['id'], shipper_id=shipper_id, status='assigned' if shipper_id else 'pending')
        s.add(o)
        s.flush()
        save_parcel(s,o,d)
        s.flush()
        event(s, o.id, 'Tạo đơn' + (' và phân công nhân viên' if shipper_id else ''))
        return o

    @app.post('/api/orders')
    def add():
        if g.user['role'] not in ['admin','customer']:
            raise Forbidden('Chỉ Admin và Khách hàng được tạo đơn.')
        d=dict(request.get_json())
        if g.user['role']=='customer':
            d['shipper_id']=None
            d['service_minutes']=3
        with Store.begin() as s:
            o = add_order(s, d)
            return jsonify(enrich(s,order_json(o))), 201

    @app.get('/api/orders/<ident>')
    def order_detail(ident):
        with Store() as s:
            o=visible_order(s,ident)
            return jsonify(enrich(s,order_json(o)))

    @app.post('/api/orders/<ident>/cancel')
    def customer_cancel(ident):
        if g.user['role']!='customer':
            raise Forbidden('Chức năng hủy yêu cầu dành cho khách tạo đơn.')
        with Store.begin() as s:
            o=visible_order(s,ident)
            if o.status!='pending' or o.shipper_id or active_plan(s,ident):
                raise Conflict('Chỉ hủy được đơn của bạn khi chưa phân công.')
            change_order(s,o,dict(status='cancelled'),request.get_json().get('version'))
            event(s,ident,'Khách hàng hủy yêu cầu trước khi phân công')
        return jsonify(ok=True)

    @app.put('/api/orders/<ident>')
    @admin
    def edit(ident):
        d = request.get_json()
        with Store.begin() as s:
            o = visible_order(s, ident)
            if o.status not in ['pending', 'assigned'] or active_plan(s, ident):
                raise Conflict('Chỉ sửa đơn chưa lấy hàng và chưa thuộc chuyến đang hoạt động.')
            previous=order_json(o)
            change_order(s, o, values(d), d.get('version'))
            save_parcel(s,o,d,previous)
            event(s, ident, 'Admin sửa thông tin đơn')
        return jsonify(ok=True)

    @app.post('/api/orders/<ident>/assign')
    @admin
    def assign(ident):
        d = request.get_json()
        with Store.begin() as s:
            o = visible_order(s, ident)
            if o.status not in ['pending', 'assigned', 'failed'] or active_plan(s, ident):
                raise Conflict('Không thể phân công lại đơn đang thuộc chuyến hoặc đang giao.')
            u = s.get(User, d.get('shipper_id'))
            if not u or not u.active or u.role != 'staff':
                raise ValueError('Chọn nhân viên đang hoạt động.')
            change_order(s, o, dict(shipper_id=u.id, status='assigned', failure_reason=''), d.get('version'))
            event(s, ident, 'Phân công cho ' + u.name)
        return jsonify(ok=True)

    @app.post('/api/orders/<ident>/status')
    def status(ident):
        if g.user['role']=='customer':
            raise Forbidden('Khách hàng chỉ được theo dõi, không được sửa trạng thái giao hàng.')
        d = request.get_json()
        with Store.begin() as s:
            o = visible_order(s, ident)
            target = d.get('status')
            allowed = {'assigned':['picked_up'], 'picked_up':['delivering'], 'delivering':['delivered','failed'], 'failed':['delivering']}
            if target == 'cancelled':
                if g.user['role'] != 'admin' or o.status not in ['pending','assigned','failed'] or active_plan(s, ident):
                    raise Forbidden('Chỉ Admin hủy đơn chưa giao và không thuộc chuyến đang hoạt động.')
            elif target not in allowed.get(o.status, []):
                raise ValueError('Không thể chuyển từ ' + STATUSES[o.status] + ' sang trạng thái được chọn.')
            if target=='delivered':
                raise ValueError('Dùng chức năng Xác nhận giao hàng với tên người nhận và ảnh bằng chứng.')
            reason = str(d.get('reason','')).strip()[:500]
            if target == 'failed' and not reason:
                raise ValueError('Nhập lý do giao thất bại.')
            collected = d.get('cod_collected', False)
            if type(collected) is not bool:
                raise ValueError('Xác nhận COD không hợp lệ.')
            change_order(s, o, dict(status=target, failure_reason=reason if target == 'failed' else '', cod_collected=(collected and o.cod>0) if target=='delivered' else o.cod_collected), d.get('version'))
            event(s, ident, STATUSES[target] + (': '+reason if reason else ''))
        return jsonify(ok=True)

    @app.post('/api/orders/<ident>/cod')
    def cod(ident):
        if g.user['role']=='customer':
            raise Forbidden('Chỉ Admin hoặc nhân viên giao hàng được xác nhận thu COD.')
        with Store.begin() as s:
            o = visible_order(s, ident)
            if o.status != 'delivered' or o.cod <= 0 or o.cod_collected:
                raise ValueError('Chỉ xác nhận COD cho đơn đã giao, còn tiền chưa thu.')
            change_order(s, o, dict(cod_collected=True), request.get_json().get('version'))
            event(s, ident, 'Xác nhận đã thu COD ' + str(o.cod) + ' đồng')
        return jsonify(ok=True)

    @app.get('/api/orders/<ident>/events')
    def events(ident):
        with Store() as s:
            visible_order(s, ident)
            rows = s.execute(select(Event, User.name).join(User, Event.actor_id == User.id).where(Event.order_id == ident).order_by(Event.created))
            return jsonify([dict(action=e.action, actor=name, created=e.created) for e,name in rows])

    @app.post('/api/import')
    @admin
    def import_csv():
        f = request.files.get('file')
        if not f or not f.filename.lower().endswith('.csv'):
            raise ValueError('Chọn file CSV UTF-8 có tiêu đề name,address,lat,lon,phone,cod.')
        rows = list(csv.DictReader(io.StringIO(f.read().decode('utf-8-sig'))))
        if not 1 <= len(rows) <= 100:
            raise ValueError('Mỗi file cần 1–100 đơn.')
        with Store.begin() as s:
            for row in rows:
                add_order(s, row)
        return jsonify(count=len(rows))

    @app.post('/api/sample')
    @admin
    def sample():
        points = [('Mai Anh','Bến Thành',10.7725,106.698),('Minh Khang','Tân Định',10.7883,106.6909),('Ngọc Hà','Bình Thạnh',10.8101,106.7091),('Quang Huy','Thảo Điền',10.803,106.732),('Thanh Tú','Quận 4',10.7578,106.7048),('Bảo Trân','Quận 7',10.729,106.718)]
        with Store.begin() as s:
            for name, address, lat, lon in points:
                add_order(s, dict(name=name,address=address,lat=lat,lon=lon,cod=100000,note='Đơn mẫu',shipper_id=request.get_json().get('shipper_id')))
        return jsonify(count=6)

    @app.post('/api/plan')
    def optimize():
        if g.user['role']=='customer':
            raise Forbidden('Chức năng lập chuyến dành cho Admin và Nhân viên.')
        d = request.get_json()
        ids = d.get('order_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=25 or len(ids)!=len(set(ids)):
            raise ValueError('Chọn 1–25 đơn không trùng để lập chuyến.')
        with Store() as s:
            selected = [visible_order(s,i) for i in ids]
            target = d.get('shipper_id') if g.user['role']=='admin' else g.user['id']
            u = s.get(User,target) if target else None
            if not u or not u.active or u.role!='staff':
                raise ValueError('Chọn nhân viên giao chuyến.')
            if any(o.shipper_id!=target or o.status not in ACTIVE or active_plan(s,o.id) for o in selected):
                raise Conflict('Chỉ lập chuyến từ đơn đã phân công cho cùng nhân viên, chưa nằm trong chuyến khác và chưa giao/hủy.')
            versions = {o.id:o.version for o in selected}
            ps = [json.loads(s.get(Setting,1).data)] + [enrich(s,order_json(o)) for o in selected]
        # Fixed algorithm parameters: no advanced settings accepted from the UI/API.
        cfg = {k:d[k] for k in ['source','objective','return_to_depot'] if k in d}
        record = plan(ps,cfg)
        ident = uid()
        record.update(id=ident, created=now())
        with Store.begin() as s:
            employee = s.get(User,target)
            if not employee or not employee.active:
                raise Conflict('Tài khoản nhân viên đã thay đổi.')
            p = Plan(id=ident,code='CG'+uuid.uuid4().hex[:10].upper(),shipper_id=target,created_by=g.user['id'],data=json.dumps(record))
            s.add(p)
            s.flush()
            for order_id in ids:
                o = visible_order(s,order_id)
                if o.shipper_id!=target or o.status not in ACTIVE:
                    raise Conflict('Đơn đã thay đổi khi tính tuyến. Vui lòng lập lại chuyến.')
                change_order(s,o,{},versions[order_id])
                s.add(PlanOrder(id=uid(),plan_id=ident,order_id=order_id,active=True))
                event(s,order_id,'Thêm vào chuyến '+p.code)
        return jsonify(record)

    def trip_json(s,p,full=False):
        r = json.loads(p.data)
        orders = list(s.scalars(select(Order).join(PlanOrder,Order.id==PlanOrder.order_id).where(PlanOrder.plan_id==p.id)))
        data = dict(id=p.id,code=p.code,created=p.created,status=p.status,shipper_id=p.shipper_id,shipper_name=s.get(User,p.shipper_id).name,count=len(orders),delivered=sum(o.status=='delivered' for o in orders),failed=sum(o.status=='failed' for o in orders),distance_km=r['distance_km'],total_minutes=r['total_minutes'],winner=r['winner'],source_label=r['source_label'])
        if full:
            return r | data | dict(current_orders=[order_json(o) for o in orders])
        return data

    @app.get('/api/history')
    def history():
        with Store() as s:
            q=select(Plan).order_by(Plan.created.desc())
            if g.user['role']!='admin':
                q=q.where(Plan.shipper_id==g.user['id'])
            return jsonify([trip_json(s,p) for p in s.scalars(q.offset(max(0,min(int(request.args.get('offset',0)),10000000))).limit(100))])

    @app.get('/api/history/<ident>')
    def detail(ident):
        with Store() as s:
            return jsonify(trip_json(s,visible_plan(s,ident),True))

    @app.post('/api/trips/<ident>/<action>')
    def trip_action(ident,action):
        if g.user['role']=='customer':
            raise Forbidden('Khách hàng không được vận hành chuyến giao.')
        with Store.begin() as s:
            p=visible_plan(s,ident)
            # SQL compare-and-swap serializes concurrent start/complete/cancel requests.
            previous=p.status
            target={'start':'in_progress','complete':'completed','cancel':'cancelled'}.get(action)
            if not target or (action=='start' and previous!='planned') or (action=='complete' and previous!='in_progress') or (action=='cancel' and (g.user['role']!='admin' or previous!='planned')):
                raise Conflict('Thao tác không phù hợp với trạng thái chuyến hoặc quyền của bạn.')
            links=list(s.scalars(select(PlanOrder).where(PlanOrder.plan_id==ident)))
            orders=[s.get(Order,l.order_id) for l in links]
            if action=='complete' and any(o.status not in ['delivered','failed','returned'] for o in orders):
                raise Conflict('Cần cập nhật tất cả đơn thành đã giao hoặc thất bại trước khi kết thúc chuyến.')
            changed=s.execute(update(Plan).where(Plan.id==ident,Plan.status==previous).values(status=target,updated=now()).execution_options(synchronize_session=False))
            if changed.rowcount!=1:
                raise Conflict('Trạng thái chuyến đã thay đổi. Tải lại.')
            for link,o in zip(links,orders):
                if action=='start' and o.status=='assigned':
                    change_order(s,o,dict(status='picked_up'),o.version)
                    event(s,o.id,'Lấy hàng khi bắt đầu chuyến '+p.code)
                if action in ['complete','cancel']:
                    link.active=False
                event(s,o.id,{'start':'Bắt đầu','complete':'Kết thúc','cancel':'Hủy'}[action]+' chuyến '+p.code)
        return jsonify(ok=True)

    def safe(v):
        return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v

    @app.get('/api/export/<ident>.csv')
    def export(ident):
        with Store() as s:
            p=visible_plan(s,ident)
            r=json.loads(p.data)
        f=io.StringIO(); w=csv.writer(f)
        w.writerow(['Thu tu','Ma don','Nguoi nhan','Dien thoai','Dia chi','COD','Chang km','Den sau phut','Nguon'])
        for step,idx in enumerate(r['route']):
            point=r['points'][idx]; leg=r['legs'][step-1] if step else None
            w.writerow([step,point.get('code','KHO'),safe(point['name']),safe(point.get('phone','')),safe(point['address']),point.get('cod',0),leg['distance_km'] if leg else 0,leg['arrival_minutes'] if leg else 0,r['source_label']])
        return send_file(io.BytesIO(f.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name=p.code+'.csv')

    @app.get('/api/orders.csv')
    def export_orders():
        with Store() as s:
            q=select(Order)
            if g.user['role']=='customer':q=q.where(Order.created_by==g.user['id'])
            elif g.user['role']!='admin':q=q.where(Order.shipper_id==g.user['id'])
            rows=[order_json(o) for o in list(s.scalars(q))]
            for o in rows:enrich(s,o)
        f=io.StringIO();w=csv.writer(f);w.writerow(['Ma don','Nguoi nhan','Dien thoai','Dia chi','Trang thai','COD','Da thu COD','Ten hang','So kien','Tong kg','Phi giao','Nguoi tra phi','Da thu phi'])
        for o in rows:
            p=o['parcel'];w.writerow([o['code'],safe(o['name']),safe(o['phone']),safe(o['address']),STATUSES[o['status']],o['cod'],o['cod_collected'],safe(p['item_name']),p['quantity'],p['weight_kg'],p['shipping_fee'],p['fee_payer'],p['fee_collected']])
        return send_file(io.BytesIO(f.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name='danh-sach-don.csv')

    register_operations(app,Store,visible_order,change_order,event,uid)
    from completion import register_completion
    register_completion(app,Store,visible_order,change_order,event,uid,order_json)
    return app


if __name__=='__main__':
    create_app().run(host='127.0.0.1',port=int(os.environ.get('PORT','5006')),debug=False)
