"""Parcel pricing, protected delivery evidence, returns and COD reconciliation."""
import io
import json
import math
import warnings
from flask import request, jsonify, g, send_file
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update, func
from werkzeug.exceptions import Forbidden, Conflict, NotFound
from models import Settlement, Parcel, Proof, Remittance, RemittanceItem, Order, Setting, User, now
from algorithms import distances

DEFAULT_TARIFF=dict(base_fee=15000,included_km=3,per_km=3000,included_kg=2,per_kg=5000)


def parcel_values(d):
    name=str(d.get('item_name') or 'Kiện hàng').strip()[:150]
    qty=float(d.get('quantity') if d.get('quantity') not in [None,''] else 1);weight=float(d.get('weight_kg') if d.get('weight_kg') not in [None,''] else 1);value=float(d.get('declared_value') or 0)
    if not name or not qty.is_integer() or not 1<=qty<=1000 or not math.isfinite(weight) or not .1<=weight<=100 or not value.is_integer() or not 0<=value<=1_000_000_000:
        raise ValueError('Kiện hàng cần tên, 1–1000 kiện, tổng khối lượng 0,1–100 kg và giá trị hợp lệ.')
    kind=d.get('goods_type') or 'normal';payer=d.get('fee_payer') or 'sender'
    if kind not in ['normal','fragile','food','documents'] or payer not in ['sender','recipient']:
        raise ValueError('Loại hàng hoặc người trả phí không hợp lệ.')
    return dict(item_name=name,quantity=int(qty),weight_kg=weight,declared_value=int(value),goods_type=kind,fee_payer=payer)


def quote(s,d):
    p=parcel_values(d)
    lat=float(d['lat']);lon=float(d['lon'])
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
        raise ValueError('Chọn vị trí giao hợp lệ trước khi tính phí.')
    depot=json.loads(s.get(Setting,1).data)
    t=s.get(Setting,2);tariff=json.loads(t.data) if t else DEFAULT_TARIFF.copy()
    km=float(distances([depot,dict(lat=lat,lon=lon)],'haversine')[0,1])
    fee=math.ceil((tariff['base_fee']+max(0,km-tariff['included_km'])*tariff['per_km']+math.ceil(max(0,p['weight_kg']-tariff['included_kg']))*tariff['per_kg'])/1000)*1000
    if not 0<=fee<=1_000_000_000:raise ValueError('Phí tính được ngoài giới hạn. Kiểm tra biểu phí.')
    return dict(shipping_fee=int(fee),distance_km=km,tariff=tariff,basis='Biểu phí nội bộ · khoảng cách đường thẳng từ kho · làm tròn 1.000đ')


def save_parcel(s,o,d,previous=None):
    p=s.get(Parcel,o.id)
    merged=({k:getattr(p,k) for k in parcel_values({})} if p else {}) | d
    values=parcel_values(merged)
    # Contact-only edits keep the original tariff snapshot and paid state.
    unchanged=p and previous and all(float(previous[k])==float(d[k]) for k in ['lat','lon']) and all(getattr(p,k)==v for k,v in values.items())
    if unchanged:return
    q=quote(s,merged)
    if d.get('quoted_fee') is not None and int(d['quoted_fee'])!=q['shipping_fee']:
        raise Conflict('Biểu phí hoặc vị trí đã thay đổi. Tính phí và xác nhận lại.')
    paid=bool(p and p.fee_collected)
    if paid:
        raise Conflict('Đơn đã thu phí. Không đổi kiện hàng/vị trí hoặc người trả phí khi chưa xử lý khoản đã thu.')
    if not p:p=Parcel(order_id=o.id);s.add(p)
    for k,v in values.items():setattr(p,k,v)
    p.shipping_fee=q['shipping_fee'];p.fee_basis=json.dumps(q);p.fee_collected=paid


def enrich(s,data):
    p=s.get(Parcel,data['id'])
    data['parcel']={k:getattr(p,k) for k in ['item_name','quantity','weight_kg','goods_type','declared_value','shipping_fee','fee_payer','fee_collected']} if p else dict(item_name='Đơn cũ',quantity=1,weight_kg=0,goods_type='normal',declared_value=0,shipping_fee=0,fee_payer='sender',fee_collected=False)
    proof=s.execute(select(Proof.receiver_name,Proof.note,Proof.created).where(Proof.order_id==data['id'])).first()
    data['proof']=dict(receiver_name=proof.receiver_name,note=proof.note,created=proof.created,url='/api/orders/'+data['id']+'/proof') if proof else None
    data['settlements']=[dict(kind=r.kind,amount=r.amount,retained_fee=r.retained_fee,reference=r.reference,note=r.note,created=r.created) for r in s.scalars(select(Settlement).where(Settlement.order_id==data['id']))]
    return data


def image_bytes(upload):
    if not upload:raise ValueError('Cần ảnh xác nhận giao hàng (JPEG/PNG/WebP).')
    raw=upload.read(3*1024*1024+1)
    if len(raw)>3*1024*1024:raise ValueError('Ảnh tối đa 3 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in ['JPEG','PNG','WEBP'] or img.width*img.height>12_000_000:raise ValueError('Ảnh không hợp lệ hoặc quá lớn.')
                img.load();img=img.convert('RGB');img.thumbnail((1600,1600));out=io.BytesIO();img.save(out,'JPEG',quality=85)
                return out.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise ValueError('File không phải ảnh hợp lệ.') from exc


def register_operations(app,Store,visible_order,change_order,event,uid):
    @app.post('/api/quote')
    def shipping_quote():
        with Store() as s:return jsonify(quote(s,request.get_json()))

    @app.route('/api/admin/pricing',methods=['GET','PUT'])
    def pricing():
        with Store.begin() as s:
            row=s.get(Setting,2)
            if request.method=='GET':return jsonify(json.loads(row.data) if row else DEFAULT_TARIFF)
            d=request.get_json();t={}
            for k in DEFAULT_TARIFF:
                v=float(d[k]);limit=100 if k in ['included_km','included_kg'] else 1_000_000
                if not math.isfinite(v) or not 0<=v<=limit or (k not in ['included_km','included_kg'] and not v.is_integer()):raise ValueError('Biểu phí không hợp lệ.')
                t[k]=v
            if row:row.data=json.dumps(t)
            else:s.add(Setting(id=2,data=json.dumps(t)))
        return jsonify(ok=True)

    @app.post('/api/orders/<ident>/deliver')
    def deliver(ident):
        d=request.form;receiver=str(d.get('receiver_name','')).strip()[:150]
        if not receiver:raise ValueError('Nhập tên người đã nhận hàng.')
        image=image_bytes(request.files.get('photo'))
        with Store.begin() as s:
            o=visible_order(s,ident)
            if o.status!='delivering':raise ValueError('Chỉ xác nhận giao cho đơn đang giao.')
            p=s.get(Parcel,ident)
            fee=d.get('fee_collected')=='true'
            if fee and (not p or p.fee_payer!='recipient'):raise ValueError('Nhân viên chỉ xác nhận phí người nhận trả.')
            change_order(s,o,dict(status='delivered',failure_reason='',cod_collected=d.get('cod_collected')=='true' and o.cod>0),int(d.get('version',0)))
            s.add(Proof(order_id=ident,actor_id=g.user['id'],receiver_name=receiver,note=str(d.get('note',''))[:500],image=image))
            if p and p.fee_payer=='recipient':p.fee_collected=fee
            event(s,ident,'Đã giao · người nhận: '+receiver+' · có ảnh xác nhận')
        return jsonify(ok=True)

    @app.get('/api/orders/<ident>/proof')
    def delivery_proof(ident):
        with Store() as s:
            visible_order(s,ident);p=s.get(Proof,ident)
            if not p:raise NotFound('Chưa có ảnh giao hàng.')
            image=p.image
        response=send_file(io.BytesIO(image),mimetype='image/jpeg',download_name='xac-nhan-giao.jpg')
        response.headers['Cache-Control']='no-store'
        return response

    @app.post('/api/orders/<ident>/fee')
    def collect_fee(ident):
        with Store.begin() as s:
            o=visible_order(s,ident);p=s.get(Parcel,ident)
            if not p or not p.shipping_fee or p.fee_collected:raise ValueError('Không có phí chưa thu.')
            if o.status in ['cancelled','returned']:raise ValueError('Không thu phí mới cho đơn đã hủy/hoàn.')
            if p.fee_payer=='sender' and g.user['role']!='admin':raise Forbidden('Phí người gửi trả do Admin xác nhận tại kho.')
            if p.fee_payer=='recipient' and o.status!='delivered':raise ValueError('Chỉ xác nhận phí người nhận khi đã giao.')
            change_order(s,o,{},request.get_json().get('version'));p.fee_collected=True
            event(s,ident,'Xác nhận thu phí giao '+str(p.shipping_fee)+' đồng · '+p.fee_payer)
        return jsonify(ok=True)

    @app.post('/api/orders/<ident>/return')
    def return_order(ident):
        d=request.get_json();action=d.get('action');reason=str(d.get('reason','')).strip()[:500]
        if action=='receive' and g.user['role']!='admin':raise Forbidden('Chỉ Admin xác nhận kho đã nhận hàng hoàn.')
        if not reason:raise ValueError('Nhập lý do hoàn hoặc biên nhận kho.')
        with Store.begin() as s:
            o=visible_order(s,ident)
            if action=='request' and o.status=='failed':target='returning'
            elif action=='receive' and o.status=='returning' and g.user['role']=='admin':target='returned'
            else:raise Conflict('Không thể hoàn đơn ở trạng thái hoặc quyền hiện tại.')
            change_order(s,o,dict(status=target,failure_reason=reason),d.get('version'))
            event(s,ident,('Chuyển hoàn: ' if target=='returning' else 'Kho đã nhận hàng hoàn: ')+reason)
        return jsonify(ok=True)

    def scope(s):
        q=select(Order).where(Order.status=='delivered')
        if g.user['role']=='staff':q=q.where(Order.shipper_id==g.user['id'])
        return list(s.scalars(q))

    def remit_json(s,r):
        items=list(s.scalars(select(RemittanceItem).where(RemittanceItem.remittance_id==r.id)))
        return dict(id=r.id,code=r.code,staff_id=r.staff_id,staff_name=s.get(User,r.staff_id).name,total=r.total,status=r.status,note=r.note,review_note=r.review_note,created=r.created,reviewed=r.reviewed,orders=[dict(order_id=i.order_id,code=s.get(Order,i.order_id).code,cod=i.cod_amount,fee=i.fee_amount) for i in items])

    @app.get('/api/billing')
    def billing():
        with Store() as s:
            locked=set(s.scalars(select(RemittanceItem.order_id).where(RemittanceItem.active==True)))
            eligible=[]
            for o in scope(s):
                p=s.get(Parcel,o.id);fee=p.shipping_fee if p and p.fee_payer=='recipient' else 0
                ready=(not o.cod or o.cod_collected) and (not fee or p.fee_collected)
                if ready and o.shipper_id and o.id not in locked and o.cod+fee>0:
                    eligible.append(dict(id=o.id,version=o.version,code=o.code,staff_id=o.shipper_id,cod=o.cod,fee=fee,total=o.cod+fee))
            q=select(Remittance).order_by(Remittance.created.desc())
            if g.user['role']=='staff':q=q.where(Remittance.staff_id==g.user['id'])
            receipts=[remit_json(s,r) for r in list(s.scalars(q.offset(max(0,min(int(request.args.get('offset',0)),10000000))).limit(100)))]
            totals={}
            for status in ['pending','confirmed']:
                total_q=select(func.coalesce(func.sum(Remittance.total),0)).where(Remittance.status==status)
                if g.user['role']=='staff':total_q=total_q.where(Remittance.staff_id==g.user['id'])
                totals[status]=s.scalar(total_q)
        return jsonify(eligible=eligible,receipts=receipts,totals=totals)

    @app.post('/api/remittances')
    def submit_remittance():
        d=request.get_json();items=d.get('orders')
        if not isinstance(items,list) or not 1<=len(items)<=100 or len({i['id'] for i in items})!=len(items):raise ValueError('Chọn 1–100 đơn không trùng.')
        with Store.begin() as s:
            target=g.user['id'] if g.user['role']=='staff' else d.get('staff_id')
            employee=s.get(User,target) if target else None
            if not employee or employee.role!='staff':raise ValueError('Chọn nhân viên nộp tiền.')
            rows=[]
            for item in items:
                o=visible_order(s,item['id']);p=s.get(Parcel,o.id);fee=p.shipping_fee if p and p.fee_payer=='recipient' else 0
                if o.shipper_id!=target or o.status!='delivered' or (o.cod and not o.cod_collected) or (fee and not p.fee_collected) or o.cod+fee<=0:raise Conflict('Có đơn chưa thu đủ tiền hoặc không thuộc nhân viên này.')
                if s.scalar(select(RemittanceItem.id).where(RemittanceItem.order_id==o.id,RemittanceItem.active==True)):raise Conflict('Có đơn đã nằm trong phiếu đối soát khác.')
                change_order(s,o,{},item.get('version'));rows.append((o,o.cod,fee))
            r=Remittance(id=uid(),code='DS'+uid().replace('-','')[:10].upper(),staff_id=target,total=sum(c+f for o,c,f in rows),note=str(d.get('note',''))[:500])
            s.add(r);s.flush()
            for o,c,f in rows:
                s.add(RemittanceItem(id=uid(),remittance_id=r.id,order_id=o.id,cod_amount=c,fee_amount=f))
                event(s,o.id,'Gửi phiếu nộp tiền '+r.code)
        return jsonify(id=r.id),201

    @app.post('/api/remittances/<ident>/<action>')
    def review_remittance(ident,action):
        d=request.get_json();note=str(d.get('note','')).strip()[:500]
        if action not in ['confirm','reject'] or (action=='reject' and not note):raise ValueError('Chọn xác nhận/từ chối, kèm lý do nếu từ chối.')
        with Store.begin() as s:
            r=s.get(Remittance,ident)
            if not r:raise NotFound('Không tìm thấy phiếu.')
            target='confirmed' if action=='confirm' else 'rejected'
            result=s.execute(update(Remittance).where(Remittance.id==ident,Remittance.status=='pending').values(status=target,reviewed_by=g.user['id'],reviewed=now(),review_note=note).execution_options(synchronize_session=False))
            if result.rowcount!=1:raise Conflict('Phiếu đã được xử lý, không xác nhận hai lần.')
            for item in list(s.scalars(select(RemittanceItem).where(RemittanceItem.remittance_id==ident))):
                if action=='reject':item.active=False
                event(s,item.order_id,('Admin xác nhận nhận tiền ' if action=='confirm' else 'Admin từ chối phiếu ')+r.code+(': '+note if note else ''))
        return jsonify(ok=True)
