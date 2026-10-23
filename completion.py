"""Scoped archive, in-app notifications, labels and immutable cash receipts."""
import io
import math
from flask import request, jsonify, g, render_template, send_file
from sqlalchemy import select, func
from werkzeug.exceptions import Conflict
from models import Order, Event, NotificationRead, Settlement, Parcel, Remittance, RemittanceItem, User
from operations import enrich


def scoped_orders():
    q=select(Order)
    if g.user['role']=='customer':q=q.where(Order.created_by==g.user['id'])
    elif g.user['role']=='staff':q=q.where(Order.shipper_id==g.user['id'])
    return q


def register_completion(app,Store,visible_order,change_order,event,uid,order_json):
    @app.get('/api/archive/orders')
    def archive_orders():
        page=max(1,min(int(request.args.get('page',1)),1000000));size=30
        q=scoped_orders();term=request.args.get('q','').strip()[:150];status=request.args.get('status','')
        if term:q=q.where(Order.code.contains(term,autoescape=True)|Order.name.contains(term,autoescape=True)|Order.phone.contains(term,autoescape=True)|Order.address.contains(term,autoescape=True))
        if status:q=q.where(Order.status==status)
        with Store() as s:
            total=s.scalar(select(func.count()).select_from(q.subquery()))
            rows=[enrich(s,order_json(o)) for o in s.scalars(q.order_by(Order.created.desc(),Order.id).offset((page-1)*size).limit(size))]
        return jsonify(items=rows,page=page,pages=max(1,math.ceil(total/size)),total=total)

    def scoped_events():
        return select(Event).where(Event.order_id.in_(scoped_orders().with_only_columns(Order.id)))

    @app.route('/api/notifications',methods=['GET','POST'])
    def notifications():
        with Store.begin() as s:
            read=select(NotificationRead.event_id).where(NotificationRead.user_id==g.user['id'])
            if request.method=='POST':
                ids=request.get_json().get('ids',[])
                if not isinstance(ids,list) or len(ids)>100:raise ValueError('Chọn tối đa 100 thông báo.')
                permitted=list(s.scalars(scoped_events().where(Event.id.in_(ids),~Event.id.in_(read))))
                for e in permitted:s.add(NotificationRead(user_id=g.user['id'],event_id=e.id))
                return jsonify(ok=True)
            unread=s.scalar(select(func.count()).select_from(scoped_events().where(~Event.id.in_(read)).subquery()))
            seen=set(s.scalars(read))
            page=max(1,min(int(request.args.get('page',1)),1000000))
            rows=list(s.scalars(scoped_events().order_by(Event.created.desc(),Event.id).offset((page-1)*50).limit(50)))
            return jsonify(unread=unread,page=page,items=[dict(id=e.id,order_id=e.order_id,code=s.get(Order,e.order_id).code,action=e.action,created=e.created,read=e.id in seen) for e in rows])

    @app.post('/api/orders/<ident>/settlement')
    def record_settlement(ident):
        d=request.get_json();kind=d.get('kind');reference=str(d.get('reference','')).strip()[:150];note=str(d.get('note','')).strip()[:500]
        if kind not in ['payout','refund'] or not reference:raise ValueError('Chọn loại phiếu và nhập mã giao dịch/biên nhận thực tế.')
        with Store.begin() as s:
            o=visible_order(s,ident);p=s.get(Parcel,ident)
            if s.scalar(select(Settlement.id).where(Settlement.order_id==ident,Settlement.kind==kind)):raise Conflict('Khoản này đã được ghi nhận, không chi lần hai.')
            retained=0
            if kind=='payout':
                owner=s.get(User,o.created_by) if o.created_by else None
                confirmed=s.scalar(select(RemittanceItem.id).join(Remittance,Remittance.id==RemittanceItem.remittance_id).where(RemittanceItem.order_id==ident,RemittanceItem.active==True,Remittance.status=='confirmed',RemittanceItem.cod_amount==o.cod))
                if o.status!='delivered' or not o.cod_collected or o.cod<=0 or not owner or owner.role!='customer' or not confirmed:
                    raise Conflict('Chỉ trả COD cho khách tạo đơn đã giao, thu COD và kho xác nhận đối soát.')
                amount=o.cod
            else:
                if o.status not in ['cancelled','returned'] or not p or not p.fee_collected or p.shipping_fee<=0:raise Conflict('Chỉ xử lý phí đã thu của đơn hủy hoặc đã hoàn về kho.')
                raw=d.get('retained_fee',0)
                if isinstance(raw,bool) or not float(raw).is_integer() or not 0<=float(raw)<=p.shipping_fee:raise ValueError('Phí giữ lại phải là số nguyên từ 0 đến phí đã thu.')
                retained=int(raw);amount=p.shipping_fee-retained
                if not note:raise ValueError('Nhập lý do hoàn phí hoặc giữ lại phí vận chuyển/hoàn hàng.')
            change_order(s,o,{},d.get('version'))
            s.add(Settlement(id=uid(),order_id=ident,kind=kind,amount=amount,retained_fee=retained,reference=reference,note=note,actor_id=g.user['id']))
            event(s,ident,('Đã trả COD cho người tạo đơn: ' if kind=='payout' else 'Đã xử lý hoàn phí: ')+str(amount)+'đ · giữ lại '+str(retained)+'đ · biên nhận '+reference)
        return jsonify(ok=True,amount=amount),201

    @app.get('/api/orders/<ident>/label')
    def shipping_label(ident):
        with Store() as s:
            o=visible_order(s,ident);data=enrich(s,order_json(o))
            return render_template('label.html',o=data)

    @app.get('/api/orders/<ident>/qr')
    def label_qr(ident):
        import qrcode
        with Store() as s:code=visible_order(s,ident).code
        image=qrcode.make(code);out=io.BytesIO();image.save(out,format='PNG');out.seek(0)
        return send_file(out,mimetype='image/png')
