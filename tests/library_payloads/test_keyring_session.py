"""Keyring orchestration without touching the host's login/keyring state."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GNOME = ROOT / 'ts/build/packages/gnome-core'
HELPER = GNOME / 'build/extra/usr/bin/thinstation-keyring-session'
CONFIGURE = GNOME / 'build/configure-keyring'
CHROME = ROOT / 'ts/build/packages/chrome/build/extra/usr/bin/chrome'

STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p=Path(os.environ['KEYRING_TEST_STATE']); state=json.loads(p.read_text())
args=sys.argv[1:]; name=Path(sys.argv[0]).name
session='/org/freedesktop/secrets/collection/session'
if name=='gnome-keyring-daemon':
    state['starts'].append(args); state['owner']=True
    print(os.environ.get('KEYRING_TEST_OUTPUT', 'GNOME_KEYRING_CONTROL='+os.environ['XDG_RUNTIME_DIR']+'/keyring'))
elif 'GetId' in args: print('s "private-fixture"')
elif 'NameHasOwner' in args: print('b '+str(state['owner']).lower())
elif 'ReadAlias' in args: print('o '+json.dumps(state.get(args[-1], '/')))
elif 'SetAlias' in args:
    state[args[-2]]=args[-1]; state['alias_writes']+=1
elif 'get-property' in args:
    path=args[args.index('get-property')+2]
    print('b '+str(state.get('locked',{}).get(path,False)).lower())
else: raise SystemExit('Unexpected fixture invocation: '+repr(args))
p.write_text(json.dumps(state))
'''


class KeyringPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ts-keyring-test-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        # UNIX-domain socket paths must stay below the kernel path limit.
        # Only sockets/state live here; executable fixtures stay in ROOT.
        runtime = tempfile.TemporaryDirectory(prefix='ts-keyring-runtime-', dir='/tmp')
        self.addCleanup(runtime.cleanup)
        self.runtime = Path(runtime.name)
        self.bin = self.work / 'bin'
        self.bin.mkdir()
        for name in ('busctl', 'gnome-keyring-daemon'):
            path = self.bin / name
            path.write_text(STUB)
            path.chmod(0o755)
        self.statefile = self.work / 'state.json'
        self.statefile.write_text(json.dumps(dict(owner=False, starts=[], alias_writes=0)))
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('GNOME_KEYRING', 'SSH_AUTH', 'XDG_', 'DBUS_', 'TS_KEYRING', 'KEYRING_'))}
        self.env.update(PATH=str(self.bin)+os.pathsep+os.environ['PATH'], DISPLAY=':199',
                        HOME=str(self.work), XDG_RUNTIME_DIR=str(self.runtime),
                        DBUS_SESSION_BUS_ADDRESS='unix:path='+str(self.runtime/'bus'),
                        KEYRING_TEST_STATE=str(self.statefile), KEYRING_MODE='auto')

    def state(self, **changes):
        data = json.loads(self.statefile.read_text())
        if changes:
            data.update(changes)
            self.statefile.write_text(json.dumps(data))
        return data

    def run_helper(self, **env):
        return subprocess.run(['bash', str(HELPER)], env=dict(self.env, **env),
                              text=True, capture_output=True, timeout=20)

    def test_passwordless_session_is_ready_and_repeated_start_is_idempotent(self):
        for _ in range(2):
            p = self.run_helper()
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('TS_KEYRING_STORAGE=session', p.stdout)
            self.assertIn('TS_KEYRING_READY=1', p.stdout)
        state = self.state()
        self.assertEqual(len(state['starts']), 1)
        self.assertIn('--daemonize', state['starts'][0])
        self.assertEqual(state['alias_writes'], 1)

    def test_pam_socket_is_initialized_not_replaced(self):
        control = self.runtime / 'keyring'
        control.mkdir(mode=0o700)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(control/'control'))
            login = '/org/freedesktop/secrets/collection/login'
            self.state(login=login)
            p = self.run_helper(TS_KEYRING_AUTH='password')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('--start', self.state()['starts'][0])
        self.assertNotIn('--replace', self.state()['starts'][0])
        self.assertIn('TS_KEYRING_STORAGE=login', p.stdout)

    def test_password_login_never_silently_uses_session_storage(self):
        p = self.run_helper(TS_KEYRING_AUTH='password')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('login keyring is absent', p.stderr)
        self.assertEqual(self.state()['alias_writes'], 0)

    def test_locked_persistent_collection_is_not_replaced(self):
        login = '/org/freedesktop/secrets/collection/login'
        self.state(owner=True, default=login, login=login, locked={login:True})
        p = self.run_helper()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('persistent keyring is locked', p.stderr)
        self.assertEqual(self.state()['default'], login)
        self.assertEqual(self.state()['alias_writes'], 0)
        self.assertEqual(self.state()['starts'], [])

    def test_explicit_session_mode_preserves_existing_login_keyring(self):
        self.state(owner=True, login='/org/freedesktop/secrets/collection/login')
        p = self.run_helper(KEYRING_MODE='session')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.state()['alias_writes'], 0)

    def test_unlocked_persistent_default_is_reused(self):
        login = '/org/freedesktop/secrets/collection/login'
        self.state(owner=True, default=login, login=login)
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('TS_KEYRING_STORAGE=login', p.stdout)
        self.assertEqual(self.state()['starts'], [])
        self.assertEqual(self.state()['alias_writes'], 0)

    def test_non_graphical_session_does_not_start_keyring(self):
        p = self.run_helper(DISPLAY='')
        self.assertEqual(p.returncode, 0)
        self.assertNotIn('TS_KEYRING_READY=1', p.stdout)
        self.assertEqual(self.state()['starts'], [])

    def test_explicit_opt_out_does_not_start_keyring(self):
        p = self.run_helper(KEYRING_MODE='off')
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.state()['starts'], [])

    def test_invalid_mode_is_rejected(self):
        self.assertNotEqual(self.run_helper(KEYRING_MODE='typo').returncode, 0)
        self.assertEqual(self.state()['starts'], [])

    def test_missing_bus_fails_before_daemon_launch(self):
        self.assertNotEqual(self.run_helper(DBUS_SESSION_BUS_ADDRESS='').returncode, 0)
        self.assertEqual(self.state()['starts'], [])

    def test_shared_runtime_is_rejected(self):
        self.runtime.chmod(0o755)
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertEqual(self.state()['starts'], [])

    def test_lock_symlink_is_rejected(self):
        (self.runtime/'thinstation-keyring.lock').symlink_to(self.work/'victim')
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse((self.work/'victim').exists())

    def test_daemon_output_is_not_executed(self):
        p = self.run_helper(KEYRING_TEST_OUTPUT='BAD=$(touch '+str(self.work/'injected')+')')
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.work/'injected').exists())

    def test_external_ssh_agent_is_not_overwritten(self):
        p = self.run_helper(SSH_AUTH_SOCK='/some/existing/agent')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('SSH_AUTH_SOCK=', p.stdout)


class KeyringPackagingTests(unittest.TestCase):
    def test_pam_and_xdg_migration_is_idempotent_and_scoped(self):
        with tempfile.TemporaryDirectory(prefix='ts-keyring-packaging-', dir=ROOT) as tmp:
            root = Path(tmp)
            pam = root/'etc/pam.d'
            pam.mkdir(parents=True)
            original = ('auth substack system-auth\n-auth optional pam_gnome_keyring.so\n'
                        'account include system-auth\nsession include system-auth\n'
                        'session optional pam_hooks.so /usr/bin/session\n'
                        '-session optional pam_gnome_keyring.so auto_start\n')
            for name in ('login', 'lightdm'):
                (pam/name).write_text(original)
            for name in ('lightdm-autologin', 'system-auth', 'sshd'):
                (pam/name).write_text('auth required pam_unix.so\n')
            snapshots = []
            for _ in range(2):
                p = subprocess.run(['bash', str(CONFIGURE), str(root)], text=True, capture_output=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                snapshots.append({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertEqual(snapshots[0], snapshots[1])
            for name in ('login', 'lightdm'):
                text = (pam/name).read_text()
                self.assertEqual(text.count('pam_gnome_keyring.so'), 2)
                self.assertIn('pam_env.so conffile=/etc/security/thinstation-keyring-auth.conf readenv=0 user_readenv=0', text)
                self.assertLess(text.index('pam_hooks.so'), text.index('-session optional pam_gnome_keyring.so auto_start'))
                self.assertIn('auth substack system-auth', text)
            for name in ('lightdm-autologin', 'system-auth', 'sshd'):
                self.assertEqual((pam/name).read_text(), 'auth required pam_unix.so\n')
            for p in auto.glob('*.desktop'):
                self.assertIn('OnlyShowIn=GNOME;Unity;MATE;', p.read_text())
                self.assertIn('Exec=vendor', p.read_text())

    def test_chrome_explicitly_depends_on_keyring_provider(self):
        self.assertIn('gnome-core', (ROOT/'ts/build/packages/chrome/dependencies').read_text().splitlines())

    def test_x11_hook_and_xfce_override_do_not_require_lightdm(self):
        hook = (GNOME/'build/extra/etc/X11/xinit/xinitrc.d/90-thinstation-keyring.sh').read_text()
        self.assertIn('thinstation_keyring_init', hook)
        self.assertIn('DISPLAY', hook)
        self.assertNotIn('systemctl start', hook)
        policy = (GNOME/'build/extra/etc/xfwm4.d/90-keyring').read_text()
        self.assertIn('/compat/LaunchGNOME -t bool -s false', policy)

    def test_source_contains_no_keyring_file_fabrication_or_empty_unlock(self):
        self.assertNotIn('login.keyring', CHROME.read_text())
        self.assertNotIn('array:string:', CHROME.read_text())
        self.assertNotIn('--unlock', HELPER.read_text())
        commands = '\n'.join(line for line in HELPER.read_text().splitlines()
                             if not line.lstrip().startswith('#'))
        self.assertNotRegex(commands, r'(^|[;\s])eval\s')


class ChromeKeyringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ts-chrome-keyring-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.globalfile = self.root/'global'
        self.globalfile.write_text(':\n')
        self.functions = self.root/'functions'
        self.functions.write_text('thinstation_keyring_init() { export TS_KEYRING_READY=1; }\n')
        self.browser = self.root/'browser'
        self.browser.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        self.browser.chmod(0o755)
        self.wrapper = self.root/'chrome'
        self.wrapper.write_text(CHROME.read_text().replace('/etc/thinstation.global', str(self.globalfile))
                                .replace('/etc/thinstation-keyring.functions', str(self.functions))
                                .replace('/opt/google/chrome/google-chrome', str(self.browser))
                                .replace('/etc/skel', str(self.root/'skel')))

    def run_chrome(self, *args, **env):
        e = dict(os.environ, HOME=str(self.root), DISPLAY=':199', KEYRING_MODE='auto')
        e.update(env)
        return subprocess.run(['bash', str(self.wrapper), *args], env=e, text=True, capture_output=True, timeout=15)

    def test_standalone_gui_selects_libsecret_and_preserves_argument_boundaries(self):
        p = self.run_chrome('--kiosk', 'https://example.invalid/a b')
        self.assertEqual(p.returncode, 0, p.stderr)
        args = json.loads(p.stdout)
        self.assertIn('--password-store=gnome-libsecret', args)
        self.assertIn('--user-data-dir='+str(self.root/'.config/google-chrome'), args)
        self.assertIn('https://example.invalid/a b', args)

    def test_existing_profile_option_is_not_duplicated(self):
        p = self.run_chrome('--user-data-dir', '/path with spaces')
        args = json.loads(p.stdout)
        self.assertEqual(sum(x.startswith('--user-data-dir') for x in args), 1)
        self.assertIn('/path with spaces', args)

    def test_keyring_failure_blocks_gui_browser(self):
        self.functions.write_text('thinstation_keyring_init() { return 1; }\n')
        p = self.run_chrome()
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout, '')

    def test_conflicting_password_store_is_not_silently_selected(self):
        self.assertNotEqual(self.run_chrome('--password-store=basic').returncode, 0)

    def test_headless_does_not_require_graphical_keyring(self):
        self.functions.unlink()
        p = self.run_chrome('--headless=new', DISPLAY='')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('--password-store=gnome-libsecret', json.loads(p.stdout))

    def test_explicit_off_policy_does_not_force_a_store(self):
        self.functions.unlink()
        p = self.run_chrome(KEYRING_MODE='off')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('--password-store=gnome-libsecret', json.loads(p.stdout))

    def test_existing_kiosk_profile_is_never_replaced(self):
        profile = self.root/'.config/google-chrome'
        profile.mkdir(parents=True)
        marker = profile/'existing-user-file'
        marker.write_text('preserve')
        self.assertEqual(self.run_chrome('--kiosk').returncode, 0)
        self.assertEqual(marker.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
