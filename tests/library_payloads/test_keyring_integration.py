"""Exercise the real daemon on private buses, never the login user's bus/home.

These tests simulate PAM's --login handoff; they do not run a real login
conversation or qualify an X11/Chrome boot. No actual X display is needed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'ts/build/packages/gnome-core/build/extra/usr/bin/thinstation-keyring-session'
TOOLS = ('bash', 'busctl', 'flock', 'stat', 'timeout', 'gnome-keyring-daemon', 'dbus-run-session', 'secret-tool')

WORKER = r'''
import hashlib, os, signal, subprocess, sys
from pathlib import Path
helper = sys.argv[1]
case = sys.argv[2]
password = b'ThinStation-fixed-test-password'
pid = None

def run(args, **kwargs):
    p = subprocess.run(args, capture_output=True, timeout=15, **kwargs)
    if p.returncode:
        raise RuntimeError(str(args[:2]) + ': ' + p.stderr.decode(errors='replace'))
    return p.stdout.decode()

def bus(*args):
    return run(['busctl', '--user', '--auto-start=no', '--timeout=5', *args])

def hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(os.environ['HOME'])/'data/keyrings').glob('*') if p.is_file()}

try:
    if case in ('login', 'reopen', 'pam-no-password'):
        run(['gnome-keyring-daemon', '--daemonize', '--login',
             '--control-directory=' + os.environ['XDG_RUNTIME_DIR'] + '/keyring'],
            input=b'' if case == 'pam-no-password' else password)
        if case != 'pam-no-password':
            os.environ['TS_KEYRING_AUTH'] = 'password'
    if case == 'console':
        os.environ.pop('DISPLAY', None)
    before = hashes()
    p = subprocess.run(['bash', helper], capture_output=True, text=True, timeout=20)
    try:
        pid = int(bus('call', 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                      'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                      's', 'org.freedesktop.secrets').split()[1])
    except Exception:
        pass
    if case == 'locked':
        assert p.returncode != 0 and 'locked' in p.stderr, p.stderr
        assert before == hashes(), 'Changed an encrypted collection on refusal'
    elif case == 'console':
        assert p.returncode == 0 and pid is None, p.stderr
    else:
        assert p.returncode == 0, p.stderr
        env = dict(line.split('=', 1) for line in p.stdout.splitlines())
        assert env['TS_KEYRING_READY'] == '1'
        assert env['TS_KEYRING_STORAGE'] == ('login' if case in ('login', 'reopen') else 'session')
        os.environ.update(env)
        if 'SSH_AUTH_SOCK' in env:
            assert Path(env['SSH_AUTH_SOCK']).is_socket()
        if case != 'reopen':
            run(['secret-tool', 'store', '--label=ThinStation fixture',
                 'fixture', 'thinstation-keyring'], input=b'fixed-test-secret')
        assert run(['secret-tool', 'lookup', 'fixture', 'thinstation-keyring']) == 'fixed-test-secret'
        again = run(['bash', helper])
        assert 'TS_KEYRING_READY=1' in again
        current_pid = int(bus('call', 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                              'org.freedesktop.DBus', 'GetConnectionUnixProcessID',
                              's', 'org.freedesktop.secrets').split()[1])
        assert current_pid == pid, 'Repeated initialization replaced the daemon'
    print('PASS ' + case)
finally:
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
'''


@unittest.skipUnless(all(shutil.which(tool) for tool in TOOLS),
                     'GNOME Keyring, libsecret tools and a private D-Bus are required')
class RealKeyringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ts-keyring-home-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def check_case(self, case):
        # Executables remain in the source checkout; only sockets/state use /tmp.
        with tempfile.TemporaryDirectory(prefix='ts-kr-', dir='/tmp') as runtime:
            env = {k:v for k,v in os.environ.items()
                   if not k.startswith(('DBUS_', 'GNOME_KEYRING', 'SSH_AUTH', 'XDG_', 'TS_KEYRING', 'KEYRING_'))}
            env.update(HOME=str(self.home), XDG_RUNTIME_DIR=runtime,
                       XDG_DATA_HOME=str(self.home/'data'), XDG_CONFIG_HOME=str(self.home/'config'),
                       DISPLAY=':199', KEYRING_MODE='auto', LC_ALL='C')
            p = subprocess.run(['dbus-run-session', '--', sys.executable, '-c',
                                WORKER, str(HELPER), case], env=env,
                               text=True, capture_output=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('PASS ' + case, p.stdout)

    def test_autologin_transient_store_and_repeated_start(self):
        self.check_case('auto')

    def test_pam_no_password_handoff_does_not_create_empty_login_keyring(self):
        self.check_case('pam-no-password')
        self.assertFalse((self.home/'data/keyrings/login.keyring').exists())

    def test_password_handoff_persistence_and_locked_collection_preservation(self):
        self.check_case('login')
        self.assertTrue((self.home/'data/keyrings/login.keyring').is_file())
        self.check_case('locked')
        self.check_case('reopen')

    def test_console_only_does_not_start_daemon(self):
        self.check_case('console')


if __name__ == '__main__':
    unittest.main()
