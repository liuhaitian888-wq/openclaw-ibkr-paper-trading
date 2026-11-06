from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from reporting.health import MODULE_DEPENDENCIES,resolve_modules
from reporting.recovery import RecoveryCoordinator

class DeliveryRouteTests(unittest.TestCase):
 def test_inactive_feishu_cannot_block_telegram_but_telegram_failure_does(self):
  now=datetime.now(timezone.utc)
  obs={k:dict(state='HEALTHY',freshness='FRESH',observed_at=now.isoformat()) for k in MODULE_DEPENDENCIES}
  obs['DELIVERY']['delivery_transport']='telegram';obs['FEISHU']['state']='FAILED'
  view=resolve_modules(obs,now=now)
  self.assertEqual(view['DELIVERY']['state'],'HEALTHY');self.assertFalse(view['FEISHU']['active'])
  self.assertEqual(view['SYSTEM']['state'],'HEALTHY')
  obs['TELEGRAM']['state']='OFFLINE'
  self.assertEqual(resolve_modules(obs,now=now)['DELIVERY']['blocking_dependency'],['TELEGRAM'])
 def test_route_survives_restart_and_configuration_never_promotes_health(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'r.sqlite3';c=RecoveryCoordinator(path);c.configure_delivery_transport('telegram')
   c=RecoveryCoordinator(path)
   self.assertEqual(c.observations()['DELIVERY']['delivery_transport'],'telegram')
   self.assertEqual(c.observations()['DELIVERY']['state'],'DEGRADED')
   c.observe('DELIVERY','HEALTHY',freshness='FRESH');c.observe('FEISHU','FAILED')
   self.assertEqual(c.observations()['DELIVERY']['state'],'HEALTHY')
   c.observe('TELEGRAM','OFFLINE')
   self.assertEqual(c.observations()['DELIVERY']['state'],'DEGRADED')
