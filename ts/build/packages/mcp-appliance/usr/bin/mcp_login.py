"""Non-secret login identity validation shared by vault and web administration."""
import json
import re
LOGIN_TYPES = {'ssh-key', 'active-directory', 'password'}
def login_name(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@\\$-]{0,255}',value.strip()):
        raise ValueError('Enter the login username on the credential, not on the inventory host.')
    return value.strip()
def password_identity(raw,ctype):
    try: data=json.loads(raw)
    except (TypeError,ValueError): raise ValueError('This credential needs a username and password object. Replace it in Credentials.') from None
    if not isinstance(data,dict): raise ValueError('The login credential must contain a username and password.')
    username=login_name(data.get('username'));password=data.get('password');domain=''
    if not isinstance(password,str) or not password or len(password)>16384 or any(c in password for c in '\x00\r\n'):
        raise ValueError('The password is empty or unsupported by noninteractive authentication.')
    if ctype=='active-directory':
        domain=data.get('domain')
        if not isinstance(domain,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',domain.strip()):
            raise ValueError('The Active Directory credential needs its domain or realm.')
        domain=domain.strip()
        if '@' not in username and '\\' not in username: username+='@'+domain
    return {'username':username,'password':password,'domain':domain}

def target_rank(meta,target,inventory):
    """Host > group > unrestricted; nonmatching assignments cannot be used."""
    if not isinstance(inventory,dict) or not isinstance(inventory.get('hosts',{}),dict) or not isinstance(inventory.get('groups',{}),dict):
        raise ValueError('Invalid inventory; credential target matching refused.')
    key=lambda value:str(value or '').strip().lower().rstrip('.')
    target=key(target);identities={target};aliases=[]
    for name,row in inventory.get('hosts',{}).items():
        if not isinstance(row,dict):raise ValueError('Invalid host entry.')
        names={key(name),key(row.get('address')),key(row.get('hostname'))}-{''}
        if target in names:aliases.append(key(name));identities.update(names)
    if len(aliases)>1:raise ValueError('Multiple inventory hosts match the credential target.')
    alias=aliases[0] if aliases else target
    allowed={key(x) for x in meta.get('allowed_hosts',[]) if key(x)}
    if not allowed:return 1
    if allowed.intersection(identities|{'host:'+x for x in identities}):return 3
    for name,row in inventory.get('groups',{}).items():
        if not isinstance(row,dict) or not isinstance(row.get('hosts',[]),list):raise ValueError('Invalid inventory group.')
        if 'group:'+key(name) in allowed and alias in {key(x) for x in row.get('hosts',[])}:return 2
    return -1
