import io
import os
import pytest
from sqlalchemy import delete, select
from app import create_app
from models import Base, User, Order, PlanOrder, Setting


@pytest.fixture
def app(tmp_path, monkeypatch):
    actual = os.environ.get('SHIPPER_TEST_SQLSERVER')
    if actual:
        assert actual.startswith('GiaoGonShipper_QA_'), 'Never clear production data'
        monkeypatch.setenv('SQLSERVER_DATABASE', actual)
        application = create_app(testing=True)
        with application.extensions['store'].begin() as s:
            for table in reversed(Base.metadata.sorted_tables):
                if table.name != 'settings':
                    s.execute(delete(table))
    else:
        application = create_app('sqlite:///' + str(tmp_path/'qa.sqlite'), testing=True)
    return application


def csrf(c):
    return {'X-CSRF-Token': c.get('/api/me').json['csrf']}


def call(c, path, data=None, method='POST'):
    return c.open(path, method=method, json=data or {}, headers=csrf(c))


def login(c, username, password):
    return call(c,'/api/login',dict(username=username,password=password))


@pytest.fixture
def people(app):
    admin = app.test_client()
    r = call(admin,'/api/setup',dict(username='admin',name='Admin QA',password='AdminTest@123'))
    assert r.status_code == 201, r.json
    assert login(admin,'admin','AdminTest@123').status_code == 200
    clients=[]
    ids=[]
    for i in [1,2]:
        r=call(admin,'/api/users',dict(username=f'staff{i}',name=f'Nhân viên {i}',password='TempTest@123'))
        assert r.status_code==201,r.json
        ids.append(r.json['id'])
        c=app.test_client()
        assert login(c,f'staff{i}','TempTest@123').status_code==200
        assert call(c,'/api/password',dict(old_password='TempTest@123',new_password='StaffTest@123')).status_code==200
        clients.append(c)
    return admin,clients,ids


def make_order(admin, shipper_id=None, name='Người nhận QA'):
    r=call(admin,'/api/orders',dict(name=name,address='TP.HCM',lat=10.78,lon=106.71,phone='0900000000',cod=100000,shipper_id=shipper_id))
    assert r.status_code==201,r.json
    return r.json


def get_order(c, ident):
    return next(o for o in c.get('/api/state').json['orders'] if o['id']==ident)


def status(c, ident, value, **extra):
    o=get_order(c,ident)
    if value=='delivered':
        from PIL import Image
        photo=io.BytesIO();Image.new('RGB',(8,8),'white').save(photo,'PNG');photo.seek(0)
        data=dict(receiver_name='Người nhận kiểm thử',version=str(o['version']),cod_collected='true' if extra.get('cod_collected') else 'false',photo=(photo,'proof.png'))
        return c.post(f'/api/orders/{ident}/deliver',data=data,headers=csrf(c))
    return call(c,f'/api/orders/{ident}/status',dict(status=value,version=o['version'],**extra))


def test_setup_auth_csrf(app):
    c=app.test_client()
    assert c.get('/').status_code==302
    assert c.get('/api/state').status_code==401
    assert c.post('/api/setup',json={}).status_code==403
    assert call(c,'/api/setup',dict(username='admin',name='Admin',password='AdminTest@123')).status_code==201
    assert call(c,'/api/setup',dict(username='other',name='Other',password='AdminTest@123')).status_code==409
    assert login(c,'admin','wrongpassword').status_code==401
    assert login(c,'admin','AdminTest@123').status_code==200
    assert c.post('/api/logout').status_code==403
    assert call(c,'/api/logout').status_code==200
    assert c.get('/api/state').status_code==401


def test_password_hash_and_role_enforcement(app,people):
    a,clients,ids=people
    with app.extensions['store']() as s:
        u=s.get(User,ids[0]); assert u.password_hash!='StaffTest@123'
    staff=clients[0]
    assert call(staff,'/api/users',dict(role='admin')).status_code==403
    assert staff.get('/api/users').status_code==403
    assert call(staff,'/api/orders',dict(name='Bad')).status_code==403
    assert call(staff,'/api/depot',dict(name='Bad'),method='PUT').status_code==403
    assert call(staff,'/api/sample').status_code==403


def test_temp_password_gate(app,people):
    a,_,_=people
    call(a,'/api/users',dict(username='newstaff',name='New',password='TempTest@123'))
    c=app.test_client();login(c,'newstaff','TempTest@123')
    assert c.get('/api/state').status_code==403
    assert call(c,'/api/password',dict(old_password='wrong',new_password='Changed@123')).status_code==400
    assert call(c,'/api/password',dict(old_password='TempTest@123',new_password='Changed@123')).status_code==200
    assert c.get('/api/state').status_code==200


def test_staff_scope_and_direct_access(people):
    a,clients,ids=people
    one=make_order(a,ids[0]);two=make_order(a,ids[1])
    assert [o['id'] for o in clients[0].get('/api/state').json['orders']]==[one['id']]
    assert clients[0].get('/api/orders/'+two['id']+'/events').status_code==404
    assert call(clients[0],'/api/orders/'+two['id']+'/status',dict(status='picked_up',version=1)).status_code==404
    export=clients[0].get('/api/orders.csv').data.decode('utf-8-sig')
    assert one['code'] in export and two['code'] not in export


def test_order_lifecycle_cod_audit(people):
    a,cs,ids=people; c=cs[0];o=make_order(a,ids[0]);ident=o['id']
    assert status(c,ident,'delivered').status_code==400
    for value in ['picked_up','delivering','delivered']:
        assert status(c,ident,value).status_code==200
    assert get_order(c,ident)['cod_collected'] is False
    assert call(c,f'/api/orders/{ident}/cod',dict(version=get_order(c,ident)['version'])).status_code==200
    assert c.get('/api/state').json['stats']['cod_collected']==100000
    assert len(c.get('/api/orders/'+ident+'/events').json)==5
    assert status(c,ident,'cancelled').status_code==403


def test_failure_reason_and_retry(people):
    a,cs,ids=people;c=cs[0];o=make_order(a,ids[0]);ident=o['id']
    status(c,ident,'picked_up');status(c,ident,'delivering')
    assert status(c,ident,'failed').status_code==400
    assert status(c,ident,'failed',reason='Không nghe máy').status_code==200
    assert status(c,ident,'delivering').status_code==200
    assert get_order(c,ident)['failure_reason']==''


def test_concurrent_edit_and_assignment(people):
    a,cs,ids=people;o=make_order(a)
    assert call(a,f"/api/orders/{o['id']}/assign",dict(shipper_id=ids[0],version=1)).status_code==200
    assert call(a,f"/api/orders/{o['id']}/assign",dict(shipper_id=ids[1],version=1)).status_code==409
    assert len(cs[0].get('/api/state').json['orders'])==1
    assert len(cs[1].get('/api/state').json['orders'])==0


def test_trip_access_lifecycle_and_fixed_parameters(people):
    a,cs,ids=people;c=cs[0];o=make_order(a,ids[0])
    data=dict(order_ids=[o['id']],source='estimate',population=99999,iterations=99999,seeds=[1],shipper_id=ids[1])
    r=call(c,'/api/plan',data);assert r.status_code==200,r.json
    p=r.json
    assert p['config']['population']==60 and p['config']['iterations']==150
    ident=p['id']
    assert cs[1].get('/api/history/'+ident).status_code==404
    assert cs[1].get('/api/export/'+ident+'.csv').status_code==404
    assert call(cs[1],'/api/trips/'+ident+'/start').status_code==404
    assert call(a,'/api/plan',dict(order_ids=[o['id']],shipper_id=ids[0])).status_code==409
    assert call(c,'/api/trips/'+ident+'/start').status_code==200
    assert get_order(c,o['id'])['status']=='picked_up'
    assert call(c,'/api/trips/'+ident+'/complete').status_code==409
    status(c,o['id'],'delivering');status(c,o['id'],'delivered',cod_collected=True)
    assert call(c,'/api/trips/'+ident+'/complete').status_code==200
    assert call(c,'/api/trips/'+ident+'/complete').status_code==409
    assert c.get('/api/history/'+ident).json['status']=='completed'
    assert c.get('/api/export/'+ident+'.csv').status_code==200


def test_cancel_and_release_trip(people):
    a,cs,ids=people;o=make_order(a,ids[0]);c=cs[0]
    p=call(c,'/api/plan',dict(order_ids=[o['id']],source='estimate')).json
    assert call(c,'/api/trips/'+p['id']+'/cancel').status_code==403
    assert call(a,'/api/trips/'+p['id']+'/cancel').status_code==200
    assert get_order(c,o['id'])['in_active_plan'] is False
    assert call(a,f"/api/orders/{o['id']}/assign",dict(shipper_id=ids[1],version=get_order(a,o['id'])['version'])).status_code==200


def test_disable_and_password_reset_invalidates_session(people):
    a,cs,ids=people
    assert call(a,'/api/users/'+ids[0],dict(active=False),method='PATCH').status_code==200
    assert cs[0].get('/api/state').status_code==401
    assert call(a,'/api/users/'+ids[0],dict(active=True),method='PATCH').status_code==200
    assert call(a,'/api/users/'+ids[1],dict(password='ResetPass@123'),method='PATCH').status_code==200
    assert cs[1].get('/api/state').status_code==401


def test_import_atomic_and_sample_non_destructive(people):
    a,cs,ids=people
    make_order(a)
    data=b'name,address,lat,lon,cod\nValid,A,10,106,1\nBad,B,100,106,1\n'
    r=a.post('/api/import',data={'file':(io.BytesIO(data),'orders.csv')},headers=csrf(a))
    assert r.status_code==400
    assert len(a.get('/api/state').json['orders'])==1
    assert call(a,'/api/sample',dict(shipper_id=ids[0])).status_code==200
    assert len(a.get('/api/state').json['orders'])==7


def test_no_advanced_settings(people):
    a,_,_=people
    html=a.get('/').data.decode()
    for token in ['id="population"','id="iterations"','id="seeds"','class="advanced"']:
        assert token not in html
