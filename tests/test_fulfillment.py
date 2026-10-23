import io
from PIL import Image
from test_portal import app,people,call,csrf,get_order,status
from test_customer import register_customer


def parcel_order(a,shipper_id=None,**extra):
    d=dict(name='Người nhận',address='TP.HCM',lat=10.78,lon=106.71,phone='0900000000',cod=100000,shipper_id=shipper_id,item_name='Quần áo',weight_kg=3,quantity=2,fee_payer='recipient')|extra
    r=call(a,'/api/orders',d);assert r.status_code==201,r.json
    return r.json


def finish(c,ident):
    assert status(c,ident,'picked_up').status_code==200
    assert status(c,ident,'delivering').status_code==200
    r=status(c,ident,'delivered',cod_collected=True);assert r.status_code==200,r.json


def test_parcel_quote_and_authoritative_fee(app,people):
    a,_,_=people;c=register_customer(app,'parcel_customer')
    d=dict(lat=10.78,lon=106.71,weight_kg=3,quantity=2,item_name='Kiện thử',fee_payer='recipient')
    q=call(c,'/api/quote',d);assert q.status_code==200
    fee=q.json['shipping_fee'];assert fee>=20000 and fee%1000==0
    o=parcel_order(c,shipping_fee=1)
    assert o['parcel']['shipping_fee']==fee
    assert o['parcel']['quantity']==2
    assert call(c,'/api/orders',dict(name='Bad',address='A',**d,quoted_fee=fee+1000)).status_code==409
    assert call(c,'/api/quote',d|dict(weight_kg=0)).status_code==400


def test_pricing_snapshot_preserves_old_orders(people):
    a,cs,ids=people
    o=parcel_order(a,ids[0]);old=o['parcel']['shipping_fee']
    t=a.get('/api/admin/pricing').json
    assert call(cs[0],'/api/admin/pricing',t,method='PUT').status_code==403
    assert call(a,'/api/admin/pricing',t|dict(base_fee=50000),method='PUT').status_code==200
    assert get_order(a,o['id'])['parcel']['shipping_fee']==old
    assert parcel_order(a,ids[0])['parcel']['shipping_fee']>old
    call(a,'/api/admin/pricing',t,method='PUT')


def test_delivery_proof_scope_and_validation(app,people):
    a,cs,ids=people;c=register_customer(app,'proof_customer');o=parcel_order(c)
    call(a,'/api/orders/'+o['id']+'/assign',dict(shipper_id=ids[0],version=o['version']))
    status(cs[0],o['id'],'picked_up');status(cs[0],o['id'],'delivering')
    current=get_order(a,o['id'])
    assert call(cs[0],'/api/orders/'+o['id']+'/status',dict(status='delivered',version=current['version'])).status_code==400
    data=dict(receiver_name='Recipient',version=str(current['version']),photo=(io.BytesIO(b'not an image'),'fake.jpg'))
    assert cs[0].post('/api/orders/'+o['id']+'/deliver',data=data,headers=csrf(cs[0])).status_code==400
    assert status(cs[0],o['id'],'delivered').status_code==200
    assert c.get('/api/orders/'+o['id']+'/proof').status_code==200
    assert cs[1].get('/api/orders/'+o['id']+'/proof').status_code==404
    other=register_customer(app,'proof_other')
    assert other.get('/api/orders/'+o['id']+'/proof').status_code==404
    assert c.get('/api/orders/'+o['id']).json['proof']['receiver_name']


def test_return_workflow_admin_receives(people):
    a,cs,ids=people;o=parcel_order(a,ids[0]);ident=o['id']
    status(cs[0],ident,'picked_up');status(cs[0],ident,'delivering');status(cs[0],ident,'failed',reason='Không nhận')
    r=call(cs[0],'/api/orders/'+ident+'/return',dict(action='request',reason='Khách từ chối',version=get_order(cs[0],ident)['version']))
    assert r.status_code==200,r.json
    d=dict(action='receive',reason='Kho đã kiểm đếm',version=get_order(a,ident)['version'])
    assert call(cs[0],'/api/orders/'+ident+'/return',d).status_code==403
    assert call(a,'/api/orders/'+ident+'/return',d).status_code==200
    assert get_order(a,ident)['status']=='returned'


def test_fee_roles_and_no_reset_of_paid_fee(people):
    a,cs,ids=people;o=parcel_order(a,ids[0],fee_payer='sender')
    d=dict(version=o['version'])
    assert call(cs[0],'/api/orders/'+o['id']+'/fee',d).status_code==403
    assert call(a,'/api/orders/'+o['id']+'/fee',d).status_code==200
    current=get_order(a,o['id'])
    edit=current|current['parcel']|dict(weight_kg=20)
    assert call(a,'/api/orders/'+o['id'],edit,method='PUT').status_code==409
    assert get_order(a,o['id'])['parcel']['fee_collected'] is True


def prepare_cash(a,c,staff_id):
    o=parcel_order(a,staff_id);finish(c,o['id'])
    assert not c.get('/api/billing').json['eligible']
    latest=get_order(c,o['id'])
    assert call(c,'/api/orders/'+o['id']+'/fee',dict(version=latest['version'])).status_code==200
    return get_order(c,o['id'])


def test_remittance_confirmation_no_double_count(people):
    a,cs,ids=people;c=cs[0];o=prepare_cash(a,c,ids[0])
    eligible=c.get('/api/billing').json['eligible'];assert len(eligible)==1
    assert eligible[0]['total']==o['cod']+o['parcel']['shipping_fee']
    d=dict(orders=[dict(id=o['id'],version=o['version'])],note='Nộp tiền QA')
    r=call(c,'/api/remittances',d);assert r.status_code==201,r.json
    assert call(c,'/api/remittances',d).status_code==409
    assert cs[1].get('/api/billing').json['receipts']==[]
    assert call(c,'/api/remittances/'+r.json['id']+'/confirm',{}).status_code==403
    assert call(a,'/api/remittances/'+r.json['id']+'/confirm',dict(note='Đã nhận đủ')).status_code==200
    assert call(a,'/api/remittances/'+r.json['id']+'/confirm',{}).status_code==409
    assert c.get('/api/billing').json['receipts'][0]['status']=='confirmed'
    assert c.get('/api/billing').json['eligible']==[]


def test_rejected_remittance_can_be_resubmitted(people):
    a,cs,ids=people;c=cs[0];o=prepare_cash(a,c,ids[0])
    r=call(c,'/api/remittances',dict(orders=[dict(id=o['id'],version=o['version'])]))
    assert r.status_code==201
    assert call(a,'/api/remittances/'+r.json['id']+'/reject',dict(note='Chưa nhận tiền')).status_code==200
    available=c.get('/api/billing').json['eligible'];assert len(available)==1
    assert call(c,'/api/remittances',dict(orders=[dict(id=o['id'],version=available[0]['version'])])).status_code==201
