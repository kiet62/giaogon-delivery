import os,sys,io,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if not os.environ.get('SQLSERVER_DATABASE','').startswith('GiaoGonShippingValidation_'):
 raise RuntimeError('Use a NEW isolated database with prefix GiaoGonShippingValidation_. Never run against production.')
from app import create_app
from PIL import Image
app=create_app(testing=True)
assert app.extensions['engine'].dialect.name=='mssql'
def send(c,path,data=None,method='POST'):
 token=c.get('/api/me').json['csrf']
 r=c.open(path,method=method,json=data or {},headers={'X-CSRF-Token':token})
 return r
admin=app.test_client()
r=send(admin,'/api/setup',dict(username='validation_admin',password='ValidationAdmin@123'));assert r.status_code==201,r.json
assert send(admin,'/api/login',dict(username='validation_admin',password='ValidationAdmin@123')).status_code==200
r=send(admin,'/api/users',dict(username='validation_staff',name='Nhân viên kiểm tra',password='ValidationStaff@123'));assert r.status_code==201,r.json
staff_id=r.json['id'];staff=app.test_client()
send(staff,'/api/login',dict(username='validation_staff',password='ValidationStaff@123'))
assert send(staff,'/api/password',dict(old_password='ValidationStaff@123',new_password='ValidationStaffNew@123')).status_code==200
customer=app.test_client()
assert send(customer,'/api/register',dict(username='validation_customer',password='ValidationCustomer@123',password_confirm='ValidationCustomer@123')).status_code==201
send(customer,'/api/login',dict(username='validation_customer',password='ValidationCustomer@123'))
r=send(customer,'/api/orders',dict(name='Người nhận kiểm tra',address='Điểm mẫu TP.HCM',lat=10.78,lon=106.71,item_name='Kiện kiểm tra',quantity=2,weight_kg=3,cod=100000,fee_payer='recipient'));assert r.status_code==201,r.json
o=r.json;ident=o['id']
assert o['parcel']['shipping_fee']>=20000
assert send(admin,'/api/orders/'+ident+'/assign',dict(shipper_id=staff_id,version=o['version'])).status_code==200
def current():return staff.get('/api/orders/'+ident).json
for status in ['picked_up','delivering']:
 r=send(staff,'/api/orders/'+ident+'/status',dict(status=status,version=current()['version']));assert r.status_code==200,r.json
photo=io.BytesIO();Image.new('RGB',(16,16),'white').save(photo,'PNG');photo.seek(0)
token=staff.get('/api/me').json['csrf']
r=staff.post('/api/orders/'+ident+'/deliver',data=dict(version=str(current()['version']),receiver_name='Người nhận mẫu',cod_collected='true',fee_collected='true',photo=(photo,'confirmation.png')),headers={'X-CSRF-Token':token});assert r.status_code==200,r.json
assert customer.get('/api/orders/'+ident+'/proof').status_code==200
assert customer.get('/api/billing').status_code==403
billing=staff.get('/api/billing').json;assert len(billing['eligible'])==1
row=billing['eligible'][0]
r=send(staff,'/api/remittances',dict(orders=[dict(id=ident,version=row['version'])],note='SQL Server validation'));assert r.status_code==201,r.json
receipt=r.json['id']
assert send(staff,'/api/remittances/'+receipt+'/confirm').status_code==403
assert send(admin,'/api/remittances/'+receipt+'/confirm',dict(note='Đã kiểm tra')).status_code==200
assert send(admin,'/api/remittances/'+receipt+'/confirm').status_code==409
assert staff.get('/api/billing').json['receipts'][0]['status']=='confirmed'
assert not staff.get('/api/billing').json['eligible']

# Cash payout and refund receipts are tested only in this isolated validation database.
o=admin.get('/api/orders/'+ident).json
r=send(admin,'/api/orders/'+ident+'/settlement',dict(kind='payout',version=o['version'],reference='SQL-VALIDATION-PAYOUT'))
assert r.status_code==201,r.json
assert send(admin,'/api/orders/'+ident+'/settlement',dict(kind='payout',version=o['version'],reference='SQL-VALIDATION-PAYOUT')).status_code==409
assert customer.get('/api/orders/'+ident).json['settlements'][0]['amount']==100000
r=send(customer,'/api/orders',dict(name='Refund validation',address='HCM',lat=10.78,lon=106.71,item_name='Validation',quantity=1,weight_kg=1,cod=50000,fee_payer='sender'));assert r.status_code==201,r.json
refund=r.json;rid=refund['id'];oldfee=refund['parcel']['shipping_fee']
t=admin.get('/api/admin/pricing').json
assert send(admin,'/api/admin/pricing',t|dict(base_fee=t['base_fee']+50000),method='PUT').status_code==200
edit=refund|refund['parcel']|dict(phone='0900000000',quoted_fee=oldfee)
assert send(admin,'/api/orders/'+rid,edit,method='PUT').status_code==200
refund=admin.get('/api/orders/'+rid).json;assert refund['parcel']['shipping_fee']==oldfee
assert send(admin,'/api/orders/'+rid+'/fee',dict(version=refund['version'])).status_code==200
refund=customer.get('/api/orders/'+rid).json
assert send(customer,'/api/orders/'+rid+'/cancel',dict(version=refund['version'])).status_code==200
refund=admin.get('/api/orders/'+rid).json
r=send(admin,'/api/orders/'+rid+'/settlement',dict(kind='refund',version=refund['version'],reference='SQL-VALIDATION-REFUND',retained_fee=5000,note='Validation only'))
assert r.status_code==201 and r.json['amount']==oldfee-5000,r.json
assert customer.get('/api/state').json['stats']['cod_outstanding']==0
assert customer.get('/api/archive/orders').json['total']==2
notices=customer.get('/api/notifications').json;assert notices['unread']>0
assert send(customer,'/api/notifications',dict(ids=[e['id'] for e in notices['items']])).status_code==200
assert customer.get('/api/notifications').json['unread']==0
assert customer.get('/api/orders/'+rid+'/label').status_code==200
qr=customer.get('/api/orders/'+rid+'/qr');assert qr.status_code==200 and qr.data.startswith(bytes([137,80,78,71]))
summary=dict(database=os.environ['SQLSERVER_DATABASE'],engine='mssql',parcel=True,fee=True,photo=True,owner_scope=True,remittance=True,no_double_confirmation=True,payout=True,refund=True,tariff_snapshot_edit=True,archive=True,notifications=True,qr=True,deleted_rows=0)
print(json.dumps(summary))
