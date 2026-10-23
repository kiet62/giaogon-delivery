from test_portal import app, people, call, make_order, get_order, status
from models import Order


def test_admin_dashboard_scope_and_report(people):
    a,cs,ids=people
    first=make_order(a,ids[0]);make_order(a,ids[1])
    for value in ['picked_up','delivering','delivered']:
        assert status(cs[0],first['id'],value,cod_collected=value=='delivered').status_code==200
    r=a.get('/api/admin/dashboard')
    assert r.status_code==200
    d=r.json
    assert d['total']==2 and d['counts']['delivered']==1
    assert d['cod_collected']==100000 and d['success_rate']==50
    assert sum(u['total'] for u in d['employees'])==2
    assert d['events']
    assert cs[0].get('/api/admin/dashboard').status_code==403
    assert cs[0].get('/api/admin/report.csv').status_code==403
    assert a.get('/api/admin/report.csv').status_code==200


def test_bulk_assignment_and_permission(people):
    a,cs,ids=people
    orders=[make_order(a) for _ in range(3)]
    d=dict(orders=[dict(id=o['id'],version=o['version']) for o in orders],shipper_id=ids[0])
    assert call(cs[0],'/api/admin/bulk-assign',d).status_code==403
    r=call(a,'/api/admin/bulk-assign',d)
    assert r.status_code==200 and r.json['count']==3
    assert len(cs[0].get('/api/state').json['orders'])==3
    assert len(cs[1].get('/api/state').json['orders'])==0


def test_bulk_conflict_rolls_back_every_order(people):
    a,cs,ids=people
    one=make_order(a);two=make_order(a)
    d=dict(shipper_id=ids[0],orders=[dict(id=one['id'],version=1),dict(id=two['id'],version=999)])
    assert call(a,'/api/admin/bulk-assign',d).status_code==409
    assert get_order(a,one['id'])['status']=='pending'
    d['orders']=[dict(id=one['id'],version=1)]*2
    assert call(a,'/api/admin/bulk-assign',d).status_code==400


def test_employee_edit_only_admin(people):
    a,cs,ids=people
    d=dict(name='Tên cập nhật',phone='0912345678',vehicle='Xe máy 59A')
    assert call(cs[1],'/api/users/'+ids[0],d,method='PATCH').status_code==403
    assert call(a,'/api/users/'+ids[0],d,method='PATCH').status_code==200
    u=next(u for u in a.get('/api/users').json if u['id']==ids[0])
    assert u['name']==d['name'] and u['vehicle']==d['vehicle']
    assert call(a,'/api/users/'+ids[0],dict(name='   '),method='PATCH').status_code==400


def test_report_date_range_and_validation(app,people):
    a,_,ids=people
    o=make_order(a,ids[0])
    with app.extensions['store'].begin() as s:
        s.get(Order,o['id']).created='2026-10-01T12:00:00+00:00'
    assert a.get('/api/admin/dashboard?from=2026-10-01&to=2026-10-01').json['total']==1
    assert a.get('/api/admin/dashboard?from=2026-10-02').json['total']==0
    assert a.get('/api/admin/dashboard?from=2026-10-10&to=2026-10-01').status_code==400
    assert a.get('/api/admin/dashboard?from=not-a-date').status_code==400
