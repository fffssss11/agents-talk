"""Task ordering, retired identities and listener isolation. Never touches the real board."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_hub import hub, ROOT


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agents-talk-order-')
        hub.DATA = Path(self.temp.name); hub.BOARD = hub.DATA / 'board.jsonl'
        self.env = {**os.environ, 'AGENTS_TALK_DATA': self.temp.name, 'PYTHONUTF8': '1'}

    def tearDown(self): self.temp.cleanup()

    def post(self, who, typ, **kw):
        return hub.post({'session': 'main', 'from': who, 'type': typ, 'body': 'fixture', **kw})

    def task(self, tid, owner='codex', **kw):
        return self.post('claude', 'task', task=tid, to=[owner], **kw)

    def state(self): return hub.read_state('main')

    def view(self, aid='codex', **kw): return hub.agent_context(self.state(), aid, **kw)

    def revision(self, tid): return next(t['revision'] for t in self.view()['tasks'] if t['id'] == tid)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'hub.py'), *args], env=self.env,
                              capture_output=True, text=True, encoding='utf-8', timeout=8)

    def test_dependencies_gate_claim_and_update_focused_digest(self):
        self.task('API', 'reasonix', body='PEER_PRIVATE_IMPLEMENTATION')
        self.task('UI', depends_on=['API'])
        before = self.view()['context']['revision']
        self.assertEqual(self.view()['continuation']['action'], 'listen')
        with self.assertRaisesRegex(hub.Reject, '前置'): self.post('codex', 'claim', task='UI')
        self.post('reasonix', 'claim', task='API'); self.post('reasonix', 'done', task='API')
        with self.assertRaises(hub.Reject): self.post('codex', 'claim', task='UI')
        self.post('claude', 'review', task='API', verdict='pass')
        delta = self.view(since=before)
        self.assertEqual([t['id'] for t in delta['tasks']], ['UI'])
        self.assertTrue(delta['tasks'][0]['ready'])
        self.assertNotIn('PEER_PRIVATE_IMPLEMENTATION', json.dumps(delta))
        self.assertEqual(delta['continuation']['task_ids'], ['UI'])
        self.post('codex', 'claim', task='UI')

    def test_invalid_dependencies_and_cli_creation(self):
        for deps in (['SELF'], ['FUTURE'], {}, 0, False, None, ['']):
            with self.assertRaises(hub.Reject): self.task('SELF', depends_on=deps)
        self.task('FIRST')
        r = self.cli('post', '--from', 'claude', '--session', 'main', '--type', 'task', '--to', 'reasonix',
                     '--task', 'NEXT', '--depends-on', 'FIRST', '--body', 'fixture')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['depends_on'], ['FIRST'])
        with self.assertRaises(hub.Reject): self.post('codex', 'progress', task='FIRST', depends_on=['NEXT'])

    def test_task_lock_requires_claim_fresh_revision_and_scope(self):
        self.task('EDIT', files=['workspace/edit.py'])
        old = self.revision('EDIT')
        with self.assertRaises(hub.Reject): self.post('codex', 'lock', task='EDIT', task_revision=old, files=['workspace/edit.py'])
        self.post('codex', 'claim', task='EDIT')
        with self.assertRaisesRegex(hub.Reject, 'revision'): self.post('codex', 'lock', task='EDIT', task_revision=old, files=['workspace/edit.py'])
        with self.assertRaises(hub.Reject): self.post('codex', 'lock', files=['workspace/edit.py'])
        with self.assertRaises(hub.Reject): self.post('codex', 'lock', task='EDIT', task_revision=self.revision('EDIT'), files=['workspace/other.py'])
        self.post('codex', 'lock', task='EDIT', task_revision=self.revision('EDIT'), files=['workspace/edit.py'])
        self.post('codex', 'done', task='EDIT', files=['workspace/edit.py'])
        with self.assertRaisesRegex(hub.Reject, '占用'): self.post('claude', 'review', task='EDIT', verdict='pass')
        self.post('codex', 'unlock', task='EDIT')
        self.post('claude', 'review', task='EDIT', verdict='pass')
        self.assertEqual(self.state()['tasks'][0]['state'], '已完成')

    def test_same_agent_different_tasks_cannot_share_write_lock(self):
        self.task('ONE', files=['workspace/shared.py'])
        self.task('TWO', files=['workspace/shared.py'])
        for tid in ('ONE', 'TWO'): self.post('codex', 'claim', task=tid)
        self.post('codex', 'lock', task='ONE', task_revision=self.revision('ONE'), files=['workspace/shared.py'])
        with self.assertRaises(hub.Reject): self.post('codex', 'lock', task='TWO', task_revision=self.revision('TWO'), files=['workspace/shared.py'])
        self.post('codex', 'unlock', task='TWO')
        self.assertTrue(self.state()['locks'])
        with self.assertRaises(hub.Reject): self.post('codex', 'progress', task='TWO', files=['workspace/shared.py'])
        self.post('codex', 'unlock', task='ONE')
        self.post('codex', 'lock', task='TWO', task_revision=self.revision('TWO'), files=['workspace/shared.py'])

    def test_progress_file_report_requires_own_task_lock(self):
        self.task('EDIT'); self.post('codex', 'claim', task='EDIT')
        with self.assertRaises(hub.Reject): self.post('codex', 'done', task='EDIT', files=['workspace/edit.py'])
        with self.assertRaises(hub.Reject): self.task('ESCAPE', files=['../outside.py'])
        self.post('codex', 'lock', task='EDIT', task_revision=self.revision('EDIT'), files=['workspace/edit.py'])
        self.post('codex', 'progress', task='EDIT', files=['workspace/edit.py'])

    def test_legacy_in_progress_task_can_report_and_upgrade_own_lock(self):
        self.task('OLD'); self.post('codex', 'claim', task='OLD')
        self.post('codex', 'lock', files=['workspace/old.py'])
        self.post('codex', 'progress', task='OLD', files=['workspace/old.py'])
        self.post('codex', 'lock', task='OLD', task_revision=self.revision('OLD'), files=['workspace/old.py'])
        self.assertEqual(next(iter(self.state()['locks'].values()))['task'], 'OLD')

    def test_one_listener_slot_and_normal_read_can_coexist(self):
        hub.DATA.mkdir(exist_ok=True)
        with hub.listener_slot('main', 'reasonix'):
            r = self.cli('listen', '--agent', 'reasonix', '--session', 'main', '--timeout', '1')
            self.assertEqual(r.returncode, 2); self.assertIn('重复监听', r.stderr)
            r = self.cli('read', '--agent', 'reasonix', '--session', 'main')
            self.assertEqual(r.returncode, 0, r.stderr)
        r = self.cli('listen', '--agent', 'reasonix', '--session', 'main', '--timeout', '1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)['timeout'])

    def test_listener_slot_recovers_after_killed_process(self):
        script = "import hub,time;\nwith hub.listener_slot('main','reasonix'):\n print('READY',flush=True); time.sleep(30)"
        p = subprocess.Popen([sys.executable, '-c', script], cwd=ROOT, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), 'READY')
            p.kill(); p.wait(timeout=5)
            r = self.cli('listen', '--agent', 'reasonix', '--session', 'main', '--timeout', '1')
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            if p.poll() is None: p.kill(); p.wait(timeout=5)
            p.stdout.close(); p.stderr.close()

    def test_retired_pi_history_ownership_usage_and_locks_not_transferred(self):
        path = hub.canonical_file('workspace/legacy.py')
        hub.append({'session': 'main', 'from': 'claude', 'to': ['pi'], 'type': 'task', 'task': 'OLD', 'body': 'legacy'})
        hub.append({'session': 'main', 'from': 'pi', 'to': ['all'], 'type': 'lock', 'files': [path], 'body': 'legacy lock'})
        before = hub.BOARD.read_bytes()
        self.assertEqual(self.state()['tasks'][0]['owner'], 'pi')
        self.assertEqual(self.state()['locks'][path]['agent'], 'pi')
        self.assertEqual(hub.BOARD.read_bytes(), before)
        self.assertNotIn('pi', self.state()['agents'])
        with self.assertRaises(hub.Reject): self.post('pi', 'join')
        self.post('zcode', 'unlock')  # Cannot release another identity's files.
        self.assertIn(path, self.state()['locks'])
        self.post('pi', 'unlock')
        hub.session_action({'session': 'main', 'action': 'reassign', 'task': 'OLD', 'to': 'codex'})
        self.assertEqual(self.state()['tasks'][0]['owner'], 'codex')
        self.post('pi', 'usage', usage_id='old-call', input_tokens=10, output_tokens=5,
                  provider='fixture', model='fixture', usage_source='fixture')
        self.assertEqual(self.state()['retired_token_usage']['pi']['total'], 15)
        self.assertIsNone(self.state()['token_usage']['zcode']['total'])

    def test_retired_lead_requires_human_selection(self):
        hub.append({'session': 'main', 'from': 'human', 'to': ['all'], 'type': 'settings', 'body': 'legacy',
                    'lead': 'pi', 'participants': ['pi', 'codex']})
        self.assertTrue(self.state()['session']['migration_required'])
        self.assertEqual(self.state()['session']['participants'], ['codex'])
        with self.assertRaises(hub.Reject): self.post('codex', 'lock', files=['workspace/x.py'])
        self.assertEqual(self.view()['continuation']['action'], 'paused_wait')
        hub.session_action({'session': 'main', 'action': 'settings', 'lead': 'codex'})
        self.assertFalse(self.state()['session']['migration_required'])

    def test_zcode_no_media_and_independent_reviewer(self):
        hub.session_action({'session': 'main', 'action': 'settings', 'participants': ['claude', 'codex', 'zcode']})
        self.post('zcode', 'join')
        for kind in ('image_generate', 'image_edit', 'video_generate'):
            with self.assertRaises(hub.Reject): self.task('MEDIA', 'zcode', kind=kind)
        self.task('CODE'); self.post('codex', 'claim', task='CODE'); self.post('codex', 'done', task='CODE')
        self.post('zcode', 'review', task='CODE', verdict='pass')
        self.assertEqual(self.state()['tasks'][0]['state'], '已完成')

    def test_session_request_retry_is_deduplicated_and_conflicts_rejected(self):
        payload = {'action': 'create', 'title': 'fixture session', 'request_id': 'session-request-1'}
        first = hub.session_action(payload)
        self.assertEqual(hub.session_action(payload), first)
        self.assertEqual(len(hub.load()), 1)
        with self.assertRaises(hub.Reject): hub.session_action({**payload, 'title': 'different'})
        end = {'action': 'ended', 'session': first['session'], 'request_id': 'session-request-2'}
        hub.session_action(end)
        self.assertEqual(hub.session_action(end), first)
        self.assertEqual(len(hub.load()), 2)


if __name__ == '__main__': unittest.main()
