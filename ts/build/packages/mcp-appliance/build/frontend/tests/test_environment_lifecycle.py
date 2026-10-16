"""Non-destructive lifecycle tests: filesystem mutations and package execution are mocked."""
import hashlib, io, json, sys, unittest
from pathlib import Path
from unittest.mock import Mock, patch
BIN=Path(__file__).resolve().parents[3]/'usr/bin'
sys.path.insert(0,str(BIN))
import mcp_environment_actions as a
import mcp_environment_rebuild as b

class LifecycleTests(unittest.TestCase):
 def test_valid_versions(self):
  for base,release,tool in [('rocky','9.8','dnf'),('rocky','10.2','dnf'),('ubuntu','24.04','apt-get'),('ubuntu','26.04','apt-get'),('fedora','44','dnf5')]:
   with self.subTest(release=release),patch.object(Path,'read_text',return_value=f'ID={base}\nVERSION_ID="{release}"'),patch.object(Path,'exists',autospec=True,side_effect=lambda p:p.name==tool):
    self.assertEqual(a.distro_info('/fixture')[:2],(base,release))
 def test_invalid_release_rejected(self):
  with patch.object(Path,'read_text',return_value='VERSION_ID=bad'),self.assertRaises(ValueError):a.distro_info('/fixture')
 def test_apt_summary_counts(self):
  self.assertEqual(a.apt_result('2 upgraded, 1 newly installed, 0 to remove and 4 not upgraded.'),{'updates_available':True,'update_count':3,'held_count':4})
 def test_apt_zero_updates(self):
  self.assertFalse(a.apt_result('0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.')['updates_available'])
 def test_apt_unknown_output_is_not_current(self):
  with self.assertRaises(ValueError):a.apt_result('metadata refreshed')
 def exercise(self,base,manager,action):
  commands=[];saved={}
  def command(argv,log,**kw):
   commands.append(argv)
   return (0,'0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.') if manager=='apt' else (100,'curl.x86_64 1.2 repo')
  with patch.object(a,'distro_info',return_value=(base,'10.2' if base=='rocky' else '24.04' if base=='ubuntu' else '44',manager)),patch.object(a,'run_command',side_effect=command),patch.object(Path,'exists',return_value=True):
   a.package_operation(Path('/fixture'),action,io.StringIO(),lambda **kw:saved.update(kw),{'fedora_url':'https://mirror.example/$releasever/$basearch/'})
  return commands,saved
 def test_apt_update_runs_upgrade_then_simulates(self):
  cmds,saved=self.exercise('ubuntu','apt','update')
  self.assertEqual([c[-1] for c in cmds],['update','upgrade','upgrade']);self.assertIn('--no-remove',cmds[1]);self.assertIn('-s',cmds[2]);self.assertEqual(saved['check_state'],'succeeded');self.assertTrue(saved['checked_at'])
 def test_apt_check_does_not_upgrade(self):
  cmds,saved=self.exercise('ubuntu','apt','check');self.assertEqual(len(cmds),2);self.assertIn('-s',cmds[1]);self.assertTrue(all('-y' not in cmd for cmd in cmds))
 def test_rocky_never_uses_fedora_overrides(self):
  cmds,saved=self.exercise('rocky','dnf','check');self.assertEqual(cmds[0][0:2],['/usr/bin/chroot','/fixture']);self.assertEqual(cmds[0][-1],'check-update');self.assertTrue(all('mirror.example' not in arg for arg in cmds[0]));self.assertTrue(saved['updates_available']);self.assertEqual(saved['update_count'],1)
 def test_fedora_successful_exit_100_is_an_update_result(self):
  cmds,saved=self.exercise('fedora','dnf','check');self.assertEqual(cmds[0][-1],'check-upgrade');self.assertTrue(saved['updates_available'])
 def test_managed_and_internal_name_validation(self):
  self.assertTrue(a.NAME.fullmatch('media-team-1'));self.assertTrue(a.INTERNAL.fullmatch('.stage-'+'a'*32))
  for value in ('../escape','/root','a/b','.cache','UPPER'):
   self.assertFalse(a.NAME.fullmatch(value));self.assertFalse(a.INTERNAL.fullmatch(value))
 def test_delete_rejects_stale_token_before_mutation(self):
  target=Mock();job={'id':'a'*32,'name':'fixture','target_token':'old','confirmation':'DELETE fixture'}
  with patch.object(a,'target_path',return_value=target),patch.object(a,'fingerprint',return_value='new'),patch.object(a,'rename_new') as rename,patch.object(a.shutil,'rmtree') as remove:
   with self.assertRaisesRegex(ValueError,'changed'):a.delete_root(job,Path('/fixture'),Path('/state'),Path('/definitions'),io.StringIO())
   rename.assert_not_called();remove.assert_not_called()
 def test_delete_rejects_missing_confirmation_before_mutation(self):
  job={'id':'a'*32,'name':'fixture','target_token':'current','confirmation':'DELETE wrong'}
  with patch.object(a,'target_path',return_value=Mock()),patch.object(a,'fingerprint',return_value='current'),patch.object(a,'rename_new') as rename,patch.object(a.shutil,'rmtree') as remove:
   with self.assertRaises(ValueError):a.delete_root(job,Path('/fixture'),Path('/state'),Path('/definitions'),io.StringIO())
   rename.assert_not_called();remove.assert_not_called()
 def test_delete_refuses_active_job_before_mutation(self):
  job={'id':'a'*32,'name':'fixture','target_token':'current','confirmation':'DELETE fixture'}
  with patch.object(a,'target_path',return_value=Mock()),patch.object(a,'fingerprint',return_value='current'),patch.object(a,'busy_job',return_value={'state':'running'}),patch.object(a.shutil,'rmtree') as remove:
   with self.assertRaisesRegex(ValueError,'active'):a.delete_root(job,Path('/fixture'),Path('/state'),Path('/definitions'),io.StringIO())
   remove.assert_not_called()
 def test_delete_refuses_active_mount_before_mutation(self):
  job={'id':'a'*32,'name':'fixture','target_token':'current','confirmation':'DELETE fixture'}
  with patch.object(a,'target_path',return_value=Mock()),patch.object(a,'fingerprint',return_value='current'),patch.object(a,'busy_job',return_value=None),patch.object(a,'assert_unused',side_effect=ValueError('active mounts')),patch.object(a.shutil,'rmtree') as remove:
   with self.assertRaisesRegex(ValueError,'active mounts'):a.delete_root(job,Path('/fixture'),Path('/state'),Path('/definitions'),io.StringIO())
   remove.assert_not_called()
 def test_mount_detection(self):
  with patch.object(Path,'resolve',return_value=Path('/fixture')),patch.object(Path,'read_text',return_value='1 0 0:1 / /fixture/dev rw - tmpfs tmpfs rw'):
   with self.assertRaisesRegex(ValueError,'active mounts'):a.assert_unused(Path('/fixture'))
 def test_missing_mount_information_fails_closed(self):
  with patch.object(Path,'resolve',return_value=Path('/fixture')),patch.object(Path,'read_text',side_effect=OSError('unavailable')):
   with self.assertRaisesRegex(ValueError,'safety'):a.assert_unused(Path('/fixture'))
 def test_private_namespace_required_for_mounts(self):
  with patch.object(a.os,'readlink',return_value='same-namespace'),patch.object(a.subprocess,'run') as run:
   with self.assertRaisesRegex(ValueError,'private mount'):
    with a.package_mounts(Path('/fixture'),io.StringIO()):pass
   run.assert_not_called()
 def test_creation_plan_uses_exact_recipe(self):
  target=Mock();target.exists.return_value=False
  recipes={'media':{'bases':[{'id':'ubuntu','releases':['24.04'],'packages':['bash','ffmpeg'],'components':'main universe'}],'install_note':'fixture'}}
  with patch.object(a,'target_path',return_value=target),patch.object(Path,'exists',return_value=False),patch.object(Path,'is_symlink',return_value=False),patch.object(a,'catalog_recipes',return_value=recipes),patch.object(b,'resolve_source',return_value={'family':'apt','suite':'noble'}):
   result=a.create_plan({'name':'new-media','profile':'media','base':'ubuntu','release':'24.04'},Path('/fixture'),Path('/definitions'))
   self.assertEqual(result['manifest']['packages'],['bash','ffmpeg']);self.assertEqual(result['confirmation'],'CREATE new-media');self.assertEqual(len(result['manifest']['source_digest']),64)
 def test_creation_never_replaces_existing_name(self):
  target=Mock();target.exists.return_value=True
  with patch.object(a,'target_path',return_value=target),self.assertRaisesRegex(ValueError,'already exists'):
   a.create_plan({'name':'existing'},Path('/fixture'),Path('/definitions'))
 def test_creation_route_requires_admin_session(self):
  text=(BIN/'mcp-operator-web').read_text();self.assertLess(text.index('if not self.operator_auth(write=True):return',text.index('def do_POST')),text.index("path=='/api/operator/environments/plan'"))

if __name__=='__main__':unittest.main()
