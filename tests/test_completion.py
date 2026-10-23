from test_portal import app,people,call,get_order,status
from test_customer import register_customer
from test_fulfillment import parcel_order,finish
from models import Order


def test_contact_edit_keeps_tariff_and_paid_fee(people):
    a,cs,ids=people
    for paid in [False,True]:
        o=parcel_order(a,ids[0],fee_payer='sender')
        if paid:
            assert call(a,'/api/orders/'+o['id']+'/fee',dict(version=o['version'])).status_code==200
            o=get_order(a,o['id'])
        old=o['parcel']['shipping_fee'];t=a.get('/api/admin/pricing').json
        assert call(a,'/api/admin/pricing',t|dict(base_fee=t['base_fee']+50000),method='PUT').status_code==200
        edit=o|o['parcel']|dict(phone='0911111111',quoted_fee=old)
        r=call(a,'/api/orders/'+o['id'],edit,method='PUT');assert r.status_code==200,r.json
        after=get_order(a,o['id']);assert after['parcel']['shipping_fee']==old
        assert after['parcel']['fee_collected']==paid
        assert after['phone']=='0911111111'


def test_weight_edit_reprices_unpaid_order(people):
    a,_,ids=people;o=parcel_order(a,ids[0]);old=o['parcel']['shipping_fee']
    r=call(a,'/api/orders/'+o['id'],o|o['parcel']|dict(weight_kg=10),method='PUT')
    assert r.status_code==200 and get_order(a,o['id'])['parcel']['shipping_fee']>old


def test_returns_not_collectible_cod(app,people):
    a,_,ids=people;o=parcel_order(a,ids[0])
    for state in ['returning','returned','cancelled']:
        with app.extensions['store'].begin() as s:s.get(Order,o['id']).status=state
        assert a.get('/api/state').json['stats']['cod_outstanding']==0
        assert a.get('/api/admin/dashboard').json['cod_outstanding']==0


def test_payout_requires_confirmed_money_and_is_unique(app,people):
    a,cs,ids=people;c=register_customer(app,'payout_customer');o=parcel_order(c)
    call(a,'/api/orders/'+o['id']+'/assign',dict(shipper_id=ids[0],version=o['version']))
    finish(cs[0],o['id']);current=get_order(a,o['id'])
    data=dict(kind='payout',reference='BANK-TEST-1',version=current['version'])
    assert call(cs[0],'/api/orders/'+o['id']+'/settlement',data).status_code==403
    assert call(c,'/api/orders/'+o['id']+'/settlement',data).status_code==403
    assert call(a,'/api/orders/'+o['id']+'/settlement',data).status_code==409
    call(cs[0],'/api/orders/'+o['id']+'/fee',dict(version=current['version']))
    current=get_order(a,o['id'])
    r=call(cs[0],'/api/remittances',dict(orders=[dict(id=o['id'],version=current['version'])]));assert r.status_code==201
    assert call(a,'/api/remittances/'+r.json['id']+'/confirm',{}).status_code==200
    data['version']=get_order(a,o['id'])['version']
    r=call(a,'/api/orders/'+o['id']+'/settlement',data);assert r.status_code==201,r.json
    assert r.json['amount']==o['cod']
    assert call(a,'/api/orders/'+o['id']+'/settlement',data).status_code==409
    assert c.get('/api/orders/'+o['id']).json['settlements'][0]['reference']=='BANK-TEST-1'


def test_refund_retained_amount_validation_and_audit(people):
    a,_,ids=people;o=parcel_order(a,fee_payer='sender')
    call(a,'/api/orders/'+o['id']+'/fee',dict(version=o['version']))
    o=get_order(a,o['id']);status(a,o['id'],'cancelled');o=get_order(a,o['id'])
    d=dict(kind='refund',reference='CASH-1',note='Giu phi xu ly',version=o['version'],retained_fee=o['parcel']['shipping_fee']+1)
    assert call(a,'/api/orders/'+o['id']+'/settlement',d).status_code==400
    d['retained_fee']=5000
    r=call(a,'/api/orders/'+o['id']+'/settlement',d);assert r.status_code==201,r.json
    assert r.json['amount']==o['parcel']['shipping_fee']-5000
    assert call(a,'/api/orders/'+o['id']+'/settlement',d).status_code==409
    assert any('CASH-1' in e['action'] for e in a.get('/api/orders/'+o['id']+'/events').json)


def test_archive_notifications_and_label_ownership(app,people):
    a,cs,ids=people;c=register_customer(app,'notice_customer');other=register_customer(app,'notice_other')
    o=parcel_order(c)
    assert c.get('/api/archive/orders').json['total']==1
    assert other.get('/api/archive/orders').json['total']==0
    assert other.get('/api/notifications').json['unread']==0
    n=c.get('/api/notifications').json;assert n['unread']==1
    call(other,'/api/notifications',dict(ids=[n['items'][0]['id']]))
    assert c.get('/api/notifications').json['unread']==1
    assert call(c,'/api/notifications',dict(ids=[n['items'][0]['id']])).status_code==200
    assert c.get('/api/notifications').json['unread']==0
    assert c.get('/api/orders/'+o['id']+'/label').status_code==200
    qr=c.get('/api/orders/'+o['id']+'/qr');assert qr.status_code==200 and qr.data.startswith(b'\x89PNG')
    assert other.get('/api/orders/'+o['id']+'/label').status_code==404
    assert cs[0].get('/api/orders/'+o['id']+'/qr').status_code==404


def test_archive_pagination_does_not_hide_old_orders(app,people):
    a,_,_=people
    for i in range(31):parcel_order(a,name='Archive '+str(i))
    first=a.get('/api/archive/orders').json;last=a.get('/api/archive/orders?page=2').json
    assert first['total']==31 and first['pages']==2 and len(first['items'])==30
    assert len(last['items'])==1
    assert not set(o['id'] for o in first['items'])&set(o['id'] for o in last['items'])
    assert a.get('/api/archive/orders?q=Archive%2030').json['total']==1
    assert a.get('/api/history?offset=100').json==[]
    assert a.get('/api/billing?offset=100').json['receipts']==[]
