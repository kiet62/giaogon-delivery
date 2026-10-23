from test_portal import app,people,call,login,make_order,get_order,status


def register_customer(app,username):
    c=app.test_client()
    r=call(c,'/api/register',dict(username=username,password='Customer@123',password_confirm='Customer@123',role='admin'))
    assert r.status_code==201 and r.json['role']=='customer'
    assert login(c,username,'Customer@123').status_code==200
    return c


def customer_order(c,**extra):
    d=dict(name='Người nhận',address='TP.HCM',lat=10.78,lon=106.71,phone='0900000000',cod=100000)
    r=call(c,'/api/orders',d|extra)
    assert r.status_code==201,r.json
    return r.json


def test_customer_create_ownership_and_no_privilege_escalation(app,people):
    admin,staff,ids=people
    c=register_customer(app,'customer1')
    o=customer_order(c,created_by=ids[0],shipper_id=ids[0],status='delivered',cod_collected=True)
    assert o['created_by']==c.get('/api/me').json['user']['id']
    assert o['shipper_id'] is None and o['status']=='pending' and not o['cod_collected']
    assert len(c.get('/api/state').json['orders'])==1
    assert len(admin.get('/api/state').json['orders'])==1
    assert len(staff[0].get('/api/state').json['orders'])==0


def test_customer_cannot_see_other_orders(app,people):
    a,_,ids=people
    c1=register_customer(app,'customer1');c2=register_customer(app,'customer2')
    own=customer_order(c1);other=customer_order(c2)
    make_order(a,ids[0])
    assert [o['id'] for o in c1.get('/api/state').json['orders']]==[own['id']]
    assert c1.get('/api/orders/'+other['id']).status_code==404
    assert c1.get('/api/orders/'+other['id']+'/events').status_code==404
    assert call(c1,'/api/orders/'+other['id']+'/cancel',dict(version=1)).status_code==404
    exported=c1.get('/api/orders.csv').data.decode('utf-8-sig')
    assert own['code'] in exported and other['code'] not in exported


def test_customer_tracking_after_assignment_and_delivery(app,people):
    a,staff,ids=people;c=register_customer(app,'customer1');o=customer_order(c)
    assert call(a,'/api/orders/'+o['id']+'/assign',dict(shipper_id=ids[0],version=o['version'])).status_code==200
    assert c.get('/api/orders/'+o['id']).json['status']=='assigned'
    for target in ['picked_up','delivering','delivered']:
        assert status(staff[0],o['id'],target,cod_collected=target=='delivered').status_code==200
        assert c.get('/api/orders/'+o['id']).json['status']==target
    assert c.get('/api/orders/'+o['id']).json['cod_collected'] is True
    assert len(c.get('/api/orders/'+o['id']+'/events').json)==5


def test_customer_cannot_operate_admin_or_shipper_actions(app,people):
    a,_,ids=people;c=register_customer(app,'customer1');o=customer_order(c)
    assert c.get('/api/admin/dashboard').status_code==403
    assert c.get('/api/users').status_code==403
    for path,data in [('/api/plan',dict(order_ids=[o['id']])),('/api/orders/'+o['id']+'/status',dict(status='delivered',version=1)),('/api/orders/'+o['id']+'/cod',dict(version=1)),('/api/orders/'+o['id']+'/assign',dict(shipper_id=ids[0],version=1))]:
        assert call(c,path,data).status_code==403
    assert call(c,'/api/orders/'+o['id'],dict(name='edit'),method='PUT').status_code==403


def test_customer_cancel_only_before_assignment(app,people):
    a,_,ids=people;c=register_customer(app,'customer1');o=customer_order(c)
    assert call(c,'/api/orders/'+o['id']+'/cancel',dict(version=o['version'])).status_code==200
    assert c.get('/api/orders/'+o['id']).json['status']=='cancelled'
    two=customer_order(c)
    call(a,'/api/orders/'+two['id']+'/assign',dict(shipper_id=ids[0],version=1))
    assert call(c,'/api/orders/'+two['id']+'/cancel',dict(version=get_order(a,two['id'])['version'])).status_code==409


def test_admin_can_create_and_lock_customer(app,people):
    a,_,_=people
    r=call(a,'/api/users',dict(username='customeradmin',name='Khách được tạo',password='Temporary@123',role='customer'))
    assert r.status_code==201 and r.json['role']=='customer'
    c=app.test_client();login(c,'customeradmin','Temporary@123')
    assert call(c,'/api/password',dict(old_password='Temporary@123',new_password='Customer@123')).status_code==200
    customer_order(c)
    assert call(a,'/api/users/'+r.json['id'],dict(active=False),method='PATCH').status_code==200
    assert c.get('/api/state').status_code==401
