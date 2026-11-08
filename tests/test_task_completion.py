import json
from pathlib import Path
import unittest

from engineering.task_completion import handle, locate_project
from tests import test_workspace_maintenance as fixtures


class TaskCompletionTests(unittest.TestCase):
    git = fixtures.WorkspaceMaintenanceTests.git
    project = fixtures.WorkspaceMaintenanceTests.project
    def setUp(self):
        fixtures.WorkspaceMaintenanceTests.setUp(self)
        self.project_root, config = self.project()
        self.registry = {'projects': [config]}
        self.state_dir = self.root / 'events'

    def event(self, kind, turn='one', **extra):
        return {'hook_event_name': kind, 'cwd': str(self.project_root), 'session_id': 'fixture', 'turn_id': turn, **extra}

    def call(self, kind, turn='one', **extra):
        return handle(self.event(kind, turn, **extra), self.registry, self.workspace, self.state_dir)

    def test_question_and_unchanged_source_do_not_continue(self):
        self.assertEqual(self.call('UserPromptSubmit'), {})
        self.assertEqual(self.call('Stop'), {})

    def test_edit_continues_once_and_maintenance_edits_do_not_loop(self):
        self.call('UserPromptSubmit')
        (self.project_root / 'src/b.py').write_text('value=2')
        result = self.call('Stop')
        self.assertEqual(result['decision'], 'block')
        self.assertIn('OpenSpec', result['reason'])
        (self.project_root / 'src/b.py').write_text('value=3')
        self.assertEqual(self.call('Stop', stop_hook_active=True), {})
        self.assertEqual(self.call('Stop'), {})
        self.call('UserPromptSubmit', 'two')
        self.assertEqual(self.call('Stop', 'two'), {})

    def test_manual_change_before_next_prompt_is_detected(self):
        self.call('UserPromptSubmit'); self.call('Stop')
        (self.project_root / 'README.md').write_text('manual design change')
        self.call('UserPromptSubmit', 'two')
        self.assertEqual(self.call('Stop', 'two')['decision'], 'block')

    def test_context_only_change_does_not_continue(self):
        self.call('UserPromptSubmit')
        (self.project_root / '.der/context/task-closeout.md').write_text('evidence only')
        self.assertEqual(self.call('Stop'), {})

    def test_external_cwd_and_unknown_event_do_not_write_state(self):
        self.assertEqual(handle(self.event('Stop', cwd=str(self.root)), self.registry, self.workspace, self.state_dir), {})
        self.assertEqual(self.call('PostToolUse'), {})
        self.assertFalse(self.state_dir.exists())

    def test_linked_worktree_maps_to_owner_and_is_observed_separately(self):
        linked = self.root / 'linked'
        self.git(self.project_root, 'worktree', 'add', '-b', 'fixture-linked', str(linked))
        config, root = locate_project(linked, self.workspace, self.registry['projects'])
        self.assertEqual(config['id'], 'one'); self.assertEqual(root, linked.resolve())
        self.call('UserPromptSubmit', cwd=str(linked))
        (linked / 'src/b.py').write_text('value=22')
        self.assertEqual(self.call('Stop', cwd=str(linked))['decision'], 'block')
        self.assertEqual((self.project_root / 'src/b.py').read_text(), 'value=1\n')

    def test_events_store_no_prompt_or_final_answer(self):
        self.call('UserPromptSubmit', prompt='private prompt', last_assistant_message='private answer')
        data = (self.state_dir / 'state.json').read_text()
        self.assertNotIn('private prompt', data); self.assertNotIn('private answer', data)

    def test_first_stop_only_establishes_baseline_and_preserves_dirty_unborn_source(self):
        unborn, cfg = self.project('unborn', commit=False)
        before = (unborn / 'src/a.py').read_text()
        self.assertEqual(handle(self.event('Stop', cwd=str(unborn)), {'projects': [cfg]}, self.workspace, self.state_dir), {})
        self.assertEqual((unborn / 'src/a.py').read_text(), before)
        self.assertEqual(self.git(unborn, 'status', '--porcelain').splitlines()[0][:2], '??')
