"""Certificate form metadata and inventory target selection."""
from urllib.parse import urlsplit, urlunsplit
import re
CHALLENGES = [
    {'value':'dns-01', 'label':'DNS-01', 'enabled':True, 'port':None},
    {'value':'http-01', 'label':'HTTP-01', 'enabled':True, 'port':80},
    {'value':'tls-alpn-01', 'label':'TLS-ALPN-01', 'enabled':True, 'port':443},
]
AD_FIELDS = ('ad_host','ad_server','ad_zone','ad_realm','ad_ttl','ad_propagation_timeout')
HTTP_FIELDS = ('http_mode','http_ready','http_source_networks','http_public_access')

def directory(value):
    if not isinstance(value,str) or not value.strip() or len(value)>2048 or any(c.isspace() or ord(c)<32 for c in value):
        raise ValueError('Enter the CA address and directory path without spaces.')
    if '://' not in value: value='https://'+value
    try:
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment: raise ValueError()
        if parsed.port is not None and not 1<=parsed.port<=65535: raise ValueError()
    except ValueError:
        raise ValueError('The ACME CA address must use HTTPS, without credentials, query, or fragment.') from None
    return urlunsplit(('https',parsed.netloc.lower(),parsed.path or '/', '', ''))

def bare_name(value):
    if not isinstance(value,str): raise ValueError('Certificate names must be text.')
    value=value.strip()
    if '://' not in value: return value
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port is not None or parsed.path not in ('','/') or parsed.query or parsed.fragment: raise ValueError()
    except ValueError:
        raise ValueError('Use a hostname without a port, path, credentials, query, or fragment.') from None
    return parsed.hostname

def active_fields(cfg,defaults):
    challenge=cfg.get('challenge')
    if challenge not in ('dns-01','http-01','tls-alpn-01'):
        raise ValueError('Select a supported validation method.')
    if challenge!='dns-01':
        for field in (*AD_FIELDS,'dns_provider','dns_hook','credential'): cfg[field]=defaults[field]
    else:
        if cfg.get('dns_provider')=='custom':
            for field in AD_FIELDS: cfg[field]=defaults[field]
        elif cfg.get('dns_provider')=='active-directory': cfg['dns_hook']=''
    if challenge!='http-01':
        for field in HTTP_FIELDS: cfg[field]=defaults[field]
    if challenge!='tls-alpn-01':
        for field in ('alpn_ready','alpn_source_networks','alpn_public_access'): cfg[field]=defaults[field]
    if challenge=='http-01' and cfg.get('http_mode')=='external':
        cfg['http_source_networks']=[]; cfg['http_public_access']=False
    return cfg


def candidates(inventory,validate_domain):
    if not isinstance(inventory,dict) or not isinstance(inventory.get('hosts',{}),dict) or not isinstance(inventory.get('groups',{}),dict):
        raise ValueError('Inventory is unavailable or invalid.')
    result=[]
    for alias,row in sorted(inventory.get('hosts',{}).items()):
        if not isinstance(alias,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,99}',alias) or not isinstance(row,dict) or row.get('platform')!='windows': continue
        try: hostname=validate_domain(row.get('hostname') or row.get('address') or '')
        except (ValueError,TypeError): continue
        groups=[name for name,group in inventory.get('groups',{}).items() if isinstance(group,dict) and isinstance(group.get('hosts',[]),list) and alias in group.get('hosts',[])]
        result.append({'alias':alias,'hostname':hostname,'address':str(row.get('address') or ''),'groups':sorted(groups)})
    return result

def bind_inventory(cfg,inventory,validate_domain,strict=False):
    cfg=dict(cfg)
    if cfg.get('challenge')!='dns-01' or cfg.get('dns_provider')!='active-directory': return cfg
    hosts=candidates(inventory,validate_domain)
    alias=cfg.get('ad_host',''); legacy=cfg.get('ad_server','')
    matches=[row for row in hosts if (row['alias']==alias if alias else row['hostname']==legacy)]
    if len(matches)==1:
        cfg['ad_host']=matches[0]['alias']; cfg['ad_server']=matches[0]['hostname']
    else:
        cfg['ad_server']=''
        if strict and (alias or legacy):
            raise ValueError('Select an existing Windows host with a full DNS hostname from Inventory. The saved AD server is missing, invalid, or ambiguous.')
    return cfg
