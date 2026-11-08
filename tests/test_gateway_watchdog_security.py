from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import configparser
import json
import tempfile
import unittest
from unittest.mock import patch,Mock
from ops.cloud import gateway_watchdog as w
from trading.gateway_recovery import decide, ENDS

class WatchdogSecurityTests(unittest.TestCase):
 def test_root_or_mixed_real_effective_identity_is_refused_before_observation(self):
  for real,effective in ((0,0),(0,1001),(1001,0),(1002,1002)):
   with patch.object(w.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1001)),patch.object(w.os,'getuid',return_value=real),patch.object(w.os,'geteuid',return_value=effective),patch.object(w,'evidence') as evidence:
    with self.assertRaises(PermissionError):w.supervise()
    evidence.assert_not_called()
  with patch.object(w.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1001)),patch.object(w.os,'getuid',return_value=1001),patch.object(w.os,'geteuid',return_value=1001):w.require_service_user()

 def test_deployed_service_has_no_root_application_execution(self):
  path=Path(__file__).resolve().parents[1]/'ops/cloud/systemd/ibkr-gateway-watchdog.service'
  cfg=configparser.ConfigParser(interpolation=None,strict=False);cfg.read(path);s=cfg['Service']
  self.assertEqual(s['User'],'ibkr');self.assertEqual(s['Group'],'ibkr')
  self.assertEqual(s['NoNewPrivileges'],'yes');self.assertEqual(s['CapabilityBoundingSet'],'')
  self.assertFalse(s['ExecStart'].startswith(('+','!')))
  self.assertFalse(hasattr(w,'delegate'))

 def test_lock_covers_durable_reservation_recheck_and_unprivileged_submission(self):
  held=False
  @contextmanager
  def monitor(*args):
   nonlocal held
   held=True
   try:yield
   finally:held=False
  def failed(t):
   return dict(approved=True,hold=False,service='active',generation='1:100',native={'last_server_reply':0},
    readback=dict(complete=False,at=t,gateway_api_handshake=False))
  state={}
  for t in (1000,1300,1600):state,_=decide(state,failed(t),t)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'runtime').mkdir();p=root/'runtime/gateway-recovery-state.json';p.write_text(json.dumps(state))
   def invoke(command,**kwargs):
    self.assertTrue(held);self.assertEqual(json.loads(p.read_text())['operation'],'STARTED')
    self.assertEqual(command,['/usr/bin/systemctl','--no-ask-password','--no-block','restart','ibkr-gateway.service'])
    return Mock(returncode=0)
   with patch.object(w,'require_service_user'),patch.object(w,'monitoring_service',side_effect=monitor),patch.object(w,'evidence',return_value=failed(1900)),patch.object(w.time,'time',return_value=1900),patch.object(w,'RecoveryCoordinator'),patch.object(w,'IncidentStore'),patch.object(w,'gateway_generation',return_value='1:100'),patch.object(w,'unit',return_value={'ActiveState':'active'}),patch.object(w.subprocess,'run',side_effect=invoke):
    result=w.evaluate(root,submit=True)
   self.assertFalse(held);self.assertEqual(result['action'],'RESTART_SUBMITTED_REQUIRES_READBACK')
   self.assertEqual(json.loads(p.read_text())['operation'],'STARTED')


 def test_admin_install_rejects_untrusted_paths_hash_changes_and_symlink_temp(self):
  from ops.cloud import install_watchdog_permissions as admin
  import hashlib
  for uid,mode in ((1001,0o755),(0,0o775),(0,0o777)):
   with patch.object(Path,'lstat',return_value=SimpleNamespace(st_uid=uid,st_mode=mode)),patch.object(Path,'is_symlink',return_value=False):
    with self.assertRaises(PermissionError):admin.protected(Path('/etc/systemd/system/example.service'))
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.write_bytes(b'reviewed')
   self.assertEqual(admin.verified_bytes(source,hashlib.sha256(b'reviewed').hexdigest()),b'reviewed')
   with self.assertRaises(PermissionError):admin.verified_bytes(source,'0'*64)
   target=root/'unit';victim=root/'victim';victim.write_bytes(b'keep')
   (root/'.unit.new').symlink_to(victim)
   with patch.object(admin,'protected'):
    with self.assertRaises(FileExistsError):admin.install(b'new',target)
   self.assertEqual(victim.read_bytes(),b'keep')

 def test_admin_install_refuses_target_root_hooks_or_other_service_user(self):
  from ops.cloud import install_watchdog_permissions as admin
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'gateway.service'
   for line in ('ExecStart=+/mutable/code','ExecStart=-!:/mutable/code','ExecStartPre=/mutable/code'):
    p.write_text('[Service]\n'+line+'\n')
    props='User=ibkr\nGroup=ibkr\nNoNewPrivileges=yes\nFragmentPath='+str(p)+'\nDropInPaths=\n'
    with patch.object(admin,'protected'),patch.object(admin.subprocess,'run',return_value=Mock(stdout=props)):
     with self.assertRaises(PermissionError):admin.gateway_boundary()
   with patch.object(admin.subprocess,'run',return_value=Mock(stdout='User=root\nGroup=root\nNoNewPrivileges=yes\n')):
    with self.assertRaises(PermissionError):admin.gateway_boundary()

if __name__=='__main__':unittest.main()
