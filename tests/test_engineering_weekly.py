from contextlib import closing
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from reporting.agent_secretary import SecretaryArchive
from reporting.engineering_weekly import collect, packet
from reporting.incidents import IncidentStore


class EngineeringWeeklyTests(unittest.TestCase):
    def test_private_weekly_immutable_idempotent_no_backfill(self):
        with tempfile.TemporaryDirectory() as d:
            archive=SecretaryArchive(Path(d)/'a.sqlite3',clock=lambda:1794740000)
            store=IncidentStore(Path(d)/'r.sqlite3',clock=lambda:1794740000)
            sunday=datetime.fromisoformat('2026-11-15T17:00:00+00:00')
            self.assertEqual(collect(archive,store,now=sunday),1)
            self.assertEqual(collect(archive,store,now=sunday),0)
            key,data=packet(archive,sunday)
            self.assertFalse(data['desktop_chat_wakeup_connected'])
            self.assertIn('未找到上述类型记录',data['prompt'])
            self.assertEqual(collect(archive,store,now=datetime.fromisoformat('2026-11-16T17:00:00+00:00')),0)
            with closing(store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],1)

    def test_preview_does_not_freeze_weekly_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            now=datetime.fromisoformat('2026-11-15T17:00:00+00:00')
            archive=SecretaryArchive(Path(d)/'a.sqlite3',clock=now.timestamp)
            archive.append('unrelated:one','other-conversation',origin='MODEL',kind='PUBLIC_RESEARCH_RESULT',payload={'summary':'不得混入其他对话'})
            _,preview=packet(archive,now)
            self.assertNotIn('不得混入其他对话',preview['prompt'])
            with closing(archive.connect()) as c:self.assertEqual(c.execute("SELECT count(*) FROM secretary_events WHERE kind='ENGINEERING_WEEKLY'").fetchone()[0],0)
            archive.append('proposal:one','der-secretary',origin='MODEL',kind='ENGINEERING_PROPOSAL',payload={'title':'实际待验证问题'})
            archive.append('research:one','der-secretary',origin='MODEL',kind='PUBLIC_RESEARCH_RESULT',payload={'summary':'原生研究结果仍需核验'})
            _,final=packet(archive,now,persist=True)
            self.assertNotEqual(preview['evidence'],final['evidence'])
            self.assertIn('实际待验证问题',final['prompt'])
            self.assertIn('原生研究结果仍需核验',final['prompt'])
