from test_portal import app, csrf, call, login


def test_register_without_name_first_admin_then_customer(app):
    first=app.test_client()
    data=dict(username='firstadmin',password='AdminPass@123',password_confirm='AdminPass@123')
    r=call(first,'/api/register',data)
    assert r.status_code==201 and r.json['role']=='admin'
    assert login(first,'firstadmin','AdminPass@123').status_code==200
    assert first.get('/api/me').json['user']['name']=='firstadmin'
    second=app.test_client()
    r=call(second,'/api/register',dict(username='newstaff',password='StaffPass@123',password_confirm='StaffPass@123',role='admin'))
    assert r.status_code==201 and r.json['role']=='customer'
    login(second,'newstaff','StaffPass@123')
    assert second.get('/api/users').status_code==403
    assert second.get('/api/state').json['orders']==[]


def test_register_validation_and_duplicate(app):
    c=app.test_client()
    d=dict(username='newuser',password='Password@123',password_confirm='WrongPass@123')
    assert call(c,'/api/register',d).status_code==400
    d['password_confirm']=d['password']
    assert c.post('/api/register',json=d).status_code==403
    assert call(c,'/api/register',d).status_code==201
    assert call(c,'/api/register',d).status_code==409


def test_auth_pages_have_no_admin_name_field(app):
    c=app.test_client()
    for page in ['/login','/register']:
        r=c.get(page)
        assert r.status_code==200
        html=r.data.decode()
        assert 'Họ tên Admin' not in html and 'setup-name' not in html
        assert 'Đăng ký' in html and 'Đăng nhập' in html
