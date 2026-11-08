from pathlib import Path
import fcntl
import json
import subprocess
import tempfile
import unittest

from engineering.workspace_maintenance import collect_project, refresh, write_snapshot


class WorkspaceMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.workspace=self.root/'workspace';self.workspace.mkdir()

    def git(self,path,*args):
        return subprocess.check_output(['git','-C',str(path),'-c','core.hooksPath=/dev/null',*args],stderr=subprocess.DEVNULL,text=True).strip()

    def project(self,name='one',commit=True):
        p=self.workspace/name;p.mkdir();self.git(p,'init');self.git(p,'config','user.name','Offline fixture');self.git(p,'config','user.email','fixture@example.invalid')
        (p/'README.md').write_text('Fixture\n');(p/'src').mkdir();(p/'src/a.py').write_text('from . import b\n');(p/'src/b.py').write_text('value=1\n')
        (p/'.der/context').mkdir(parents=True);(p/'.der/context/project-digest.md').write_text('Generated: 2026-07-29\nStatus: registered\n')
        if commit:self.git(p,'add','.');self.git(p,'commit','-m','Offline fixture')
        return p,{'id':name,'name':name,'root':name,'goal':'Maintain scoped project evidence','test_command':['offline-fixture'],'epochs':[{'id':'local-history','status':'HISTORICAL'},{'id':'cloud-monitoring','status':'CURRENT'}]}

    def test_projects_have_separate_state_and_no_inferred_pass(self):
        _,one=self.project('one');_,two=self.project('two')
        result=refresh({'projects':[one,two]},self.workspace,self.root/'out')
        self.assertEqual(set(result['projects']),{'one','two'})
        for item in result['projects'].values():
            self.assertEqual(item['verification']['tests'],'UNKNOWN')
            self.assertEqual(item['verification']['deployment'],'UNKNOWN')
            self.assertIn('SOURCE_REVISION_MISSING',item['context']['issues'])
            self.assertEqual(item['epochs'][0]['status'],'HISTORICAL')
        self.assertTrue((self.root/'out/projects/one/state.json').is_file())
        self.assertTrue((self.root/'out/projects/two/next-task.txt').is_file())

    def test_unborn_repository_is_retained_and_never_called_empty(self):
        p,cfg=self.project(commit=False);result=collect_project(self.workspace,cfg)
        self.assertEqual(result['git']['state'],'UNBORN')
        self.assertTrue(result['inventory'])
        self.assertEqual(result['next_task']['id'],'SOURCE_BASELINE')
        self.assertTrue((p/'src/a.py').exists())

    def test_dirty_work_is_reported_without_overwriting_or_committing(self):
        p,cfg=self.project();(p/'README.md').write_text('uncommitted owner work\n');head=self.git(p,'rev-parse','HEAD')
        result=collect_project(self.workspace,cfg)
        self.assertTrue(result['git']['dirty'])
        self.assertEqual((p/'README.md').read_text(),'uncommitted owner work\n')
        self.assertEqual(self.git(p,'rev-parse','HEAD'),head)

    def test_private_files_and_external_symlinks_are_not_hashed(self):
        p,cfg=self.project();(p/'.env').write_text('OFFLINE_PLACEHOLDER=example\n');outside=self.root/'outside';outside.write_text('never-read')
        (p/'outside-link.py').symlink_to(outside);self.git(p,'add','.env','outside-link.py');self.git(p,'commit','-m','Protected fixture')
        item=collect_project(self.workspace,cfg)
        bypath={x['path']:x for x in item['inventory']}
        for name in ('.env','outside-link.py'):
            self.assertEqual(bypath[name]['kind'],'protected')
            self.assertIsNone(bypath[name].get('sha256'))
        self.assertNotIn('never-read',json.dumps(item))

    def test_diagram_without_dependency_provenance_is_not_called_fresh(self):
        p,cfg=self.project();(p/'docs/diagrams').mkdir(parents=True);(p/'docs/diagrams/flow.svg').write_text('<svg/>')
        item=collect_project(self.workspace,cfg)
        self.assertEqual(item['diagrams'][0]['status'],'NEEDS_DEPENDENCY_BASELINE')
        self.assertNotIn('delete',item['diagrams'][0])

    def test_context_edits_do_not_trigger_source_update_loop(self):
        p,cfg=self.project();before=collect_project(self.workspace,cfg)
        (p/'.der/context/project-digest.md').write_text('Generated: 2026-11-08\n')
        after=collect_project(self.workspace,cfg)
        self.assertEqual(before['source_fingerprint'],after['source_fingerprint'])
        (p/'src/b.py').write_text('value=2\n')
        self.assertNotEqual(after['source_fingerprint'],collect_project(self.workspace,cfg)['source_fingerprint'])

    def test_second_snapshot_is_idempotent_and_lock_prevents_second_writer(self):
        _,cfg=self.project();out=self.root/'out'
        first=refresh({'projects':[cfg]},self.workspace,out);second=refresh({'projects':[cfg]},self.workspace,out)
        self.assertEqual(second['changed_projects'],[])
        with (out/'maintenance.lock').open() as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):write_snapshot(second,out)

    def test_registry_cannot_escape_workspace(self):
        _,cfg=self.project();cfg['root']='../outside'
        with self.assertRaises(ValueError):collect_project(self.workspace,cfg)

    def test_output_symlinks_cannot_redirect_lock_or_change_log(self):
        _,cfg=self.project();outside=self.root/'outside';outside.write_text('owner data')
        out=self.root/'out';out.mkdir();(out/'maintenance.lock').symlink_to(outside)
        with self.assertRaises(ValueError):refresh({'projects':[cfg]},self.workspace,out)
        (out/'maintenance.lock').unlink();(out/'changes.jsonl').symlink_to(outside)
        with self.assertRaises(ValueError):refresh({'projects':[cfg]},self.workspace,out)
        self.assertEqual(outside.read_text(),'owner data')

    def test_diagram_receipt_detects_input_and_output_drift(self):
        p,cfg=self.project();(p/'flow.svg').write_text('<svg/>')
        before=collect_project(self.workspace,cfg);files={x['path']:x for x in before['inventory']}
        manifest=p/'.der/maintenance';manifest.mkdir()
        receipt={'diagrams':[{'path':'flow.svg','output_sha256':files['flow.svg']['sha256'],'inputs':{'src/b.py':files['src/b.py']['sha256']}}]}
        (manifest/'diagram-dependencies.json').write_text(json.dumps(receipt))
        self.assertEqual(collect_project(self.workspace,cfg)['diagrams'][0]['status'],'CONTENT_MATCHES_RECEIPT')
        (p/'src/b.py').write_text('value=2')
        self.assertEqual(collect_project(self.workspace,cfg)['diagrams'][0]['status'],'STALE_CONTENT')
        (p/'src/b.py').write_text('value=1\n');(p/'flow.svg').write_text('<svg>changed</svg>')
        self.assertEqual(collect_project(self.workspace,cfg)['diagrams'][0]['status'],'STALE_CONTENT')
