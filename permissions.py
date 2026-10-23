"""Explicit role/method allowlists; resource ownership is checked in app.py."""
COMMON = {
    'archive_orders':{'GET'},'notifications':{'GET','POST'},'shipping_label':{'GET'},'label_qr':{'GET'},
    'me': {'GET'}, 'logout': {'POST'}, 'password': {'POST'}, 'profile': {'PUT'},
    'state': {'GET'}, 'order_detail': {'GET'}, 'events': {'GET'}, 'export_orders': {'GET'}, 'delivery_proof':{'GET'},
}
DELIVERY = {
    'status': {'POST'}, 'cod': {'POST'}, 'optimize': {'POST'},
    'history': {'GET'}, 'detail': {'GET'}, 'export': {'GET'}, 'trip_action': {'POST'},
    'deliver':{'POST'},'collect_fee':{'POST'},'return_order':{'POST'},'billing':{'GET'},'submit_remittance':{'POST'},
}
ROLES = {
    'admin': COMMON | DELIVERY | {
        'record_settlement':{'POST'},'users': {'GET','POST'}, 'update_user': {'PATCH'}, 'dashboard': {'GET'},
        'admin_report': {'GET'}, 'bulk_assign': {'POST'}, 'depot': {'PUT'},
        'add': {'POST'}, 'edit': {'PUT'}, 'assign': {'POST'}, 'import_csv': {'POST'}, 'sample': {'POST'},
        'shipping_quote':{'POST'},'pricing':{'GET','PUT'},'review_remittance':{'POST'},
    },
    'staff': COMMON | DELIVERY,
    'customer': COMMON | {'add': {'POST'}, 'customer_cancel': {'POST'},'shipping_quote':{'POST'}},
}
TABS = {
    'admin': ['admin-page','planner','orders-page','history','employees-page','billing-page','profile-page'],
    'staff': ['planner','orders-page','history','billing-page','profile-page'],
    'customer': ['my-orders-page','profile-page'],
}
PUBLIC = {'me','login','setup'}


def allowed(role, endpoint, method, args=None):
    method = 'GET' if method == 'HEAD' else method
    if method not in ROLES.get(role, {}).get(endpoint, set()):
        return False
    if endpoint == 'trip_action':
        actions = {'start','complete','cancel'} if role == 'admin' else {'start','complete'}
        return (args or {}).get('action') in actions
    return True
