from test_portal import app, people, call, login, make_order
from test_customer import register_customer
from models import User
from permissions import ROLES, TABS, PUBLIC


def test_every_private_api_has_explicit_policy(app):
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith('/api/') and rule.endpoint not in PUBLIC:
            assert any(rule.endpoint in endpoints for endpoints in ROLES.values()), rule.rule


def test_role_permissions_and_direct_api_denials(app,people):
    admin,staff,ids=people
    customer=register_customer(app,'rbac_customer')
    assert admin.get('/api/me').json['permissions']['tabs']==TABS['admin']
    assert staff[0].get('/api/me').json['permissions']['tabs']==TABS['staff']
    assert customer.get('/api/me').json['permissions']['tabs']==TABS['customer']
    staff_denied=[('GET','/api/admin/dashboard'),('GET','/api/admin/report.csv'),('GET','/api/users'),('POST','/api/users'),('PATCH','/api/users/'+ids[1]),('POST','/api/orders'),('PUT','/api/depot'),('POST','/api/admin/bulk-assign'),('POST','/api/import'),('POST','/api/sample'),('POST','/api/trips/anything/cancel')]
    customer_denied=staff_denied+[('POST','/api/plan'),('GET','/api/history'),('GET','/api/history/anything'),('GET','/api/export/anything.csv'),('POST','/api/orders/anything/status'),('POST','/api/orders/anything/cod'),('POST','/api/trips/anything/start')]
    # Customers can create orders, so omit that one endpoint from their deny list.
    customer_denied=[pair for pair in customer_denied if pair!=('POST','/api/orders')]
    for client,denied in [(staff[0],staff_denied),(customer,customer_denied)]:
        for method,path in denied:
            r=call(client,path,{},method=method)
            assert r.status_code==403,(method,path,r.status_code,r.json)
    assert 'admin-page' not in customer.get('/api/me').json['permissions']['tabs']
    assert 'employees-page' not in staff[0].get('/api/me').json['permissions']['tabs']


def test_new_api_is_denied_by_default(app):
    @app.get('/api/unlisted-test-only')
    def unlisted():
        return {'secret':'should never be returned'}
    c=app.test_client()
    call(c,'/api/setup',dict(username='admin',password='AdminTest@123'))
    login(c,'admin','AdminTest@123')
    assert c.get('/api/unlisted-test-only').status_code==403


def test_cookie_role_tampering_does_not_elevate(people):
    _,staff,_=people
    c=staff[0]
    with c.session_transaction() as session:
        session['role']='admin'
        session['is_admin']=True
    assert c.get('/api/me').json['user']['role']=='staff'
    assert c.get('/api/users').status_code==403


def test_unknown_database_role_invalidates_session(app,people):
    _,staff,ids=people
    with app.extensions['store'].begin() as s:
        s.get(User,ids[0]).role='unknown_role'
    assert staff[0].get('/api/state').status_code==401
    assert staff[0].get('/api/me').json['user'] is None
