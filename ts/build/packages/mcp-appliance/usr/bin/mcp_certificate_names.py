"""Internal certificate-name policy and nonblocking local FQDN discovery."""
from pathlib import Path
import re
import socket
from urllib.parse import urlsplit


def short_names_allowed(cfg):
    if cfg.get('internal_ca') is not True:
        return False
    host = (urlsplit(cfg.get('directory_url', '')).hostname or '').lower().rstrip('.')
    return bool(host) and host != 'letsencrypt.org' and not host.endswith('.letsencrypt.org')


def appliance_identity(hostname=None, resolver_text=None):
    """Derive a default from configuration, never from browser input or reverse DNS."""
    name = (socket.gethostname() if hostname is None else hostname).strip().lower().rstrip('.')
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    def valid(value):
        return (len(value) <= 253 and re.fullmatch(label + r'(?:\.' + label + ')*', value)
                and not all(part.isdigit() for part in value.split('.'))
                and value != 'localhost' and not value.endswith('.localhost')
                and value != 'localhost.localdomain')
    if not valid(name):
        return {'hostname': '', 'fqdn': '', 'source': 'unavailable'}
    if '.' in name:
        return {'hostname': name.split('.')[0], 'fqdn': name, 'source': 'system hostname'}
    if resolver_text is None:
        try:
            resolver_text = Path('/etc/resolv.conf').read_text()
        except OSError:
            resolver_text = ''
    domains = []
    for line in resolver_text.splitlines():
        words = re.split(r'[;#]', line, maxsplit=1)[0].split()
        if words and words[0] in ('search', 'domain'):
            domains = words[1:] if words[0] == 'search' else words[1:2]
    domains = list(dict.fromkeys(d.lower().rstrip('.') for d in domains))
    domains = [d for d in domains if valid(d) and '.' in d and not d.startswith('~')]
    if len(domains) == 1 and valid(name + '.' + domains[0]):
        return {'hostname': name, 'fqdn': name + '.' + domains[0], 'source': 'system hostname and DNS search domain'}
    return {'hostname': name, 'fqdn': '', 'source': 'DNS search domain is missing or ambiguous'}
