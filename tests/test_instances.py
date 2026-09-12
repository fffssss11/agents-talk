"""Independent roles/windows of the same client. All state is temporary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_hub import hub, ROOT


class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agents-talk-instances-')
        hub.DATA = Path(self.temp.name); hub.BOARD = hub.DATA / 'board.jsonl'
        self.env = {**os.environ, 'AGENTS_TALK_DATA': self.temp.name, 'PYTHONUTF8': '1'}

    def tearDown(self): self.temp.cleanup()
    def state(self, sid='main'): return hub.read_state(sid)
    def create(self, client='codex', role='worker', **kw):
        return hub.session_action({'action': 'instance_create', 'session': 'main', 'client': client,
            'name': client + ' fixture', 'model': 'gpt6', 'role': role,
            'expected_revision': self.state()['session']['instance_revision'], **kw})['instance']
    def edit(self, aid, **kw):
        a = self.state()['agents'][aid]
        return hub.session_action({'action': 'instance_update', 'session': 'main', 'instance': aid,
            'name': a['name'], 'model': a['model'], 'role': 'lead' if aid == self.state()['lead'] else 'worker',
            'expected_revision': self.state()['session']['instance_revision'], **kw})
    def post(self, who, typ, **kw):
        return hub.post({'session': 'main', 'from': who, 'type': typ, 'body': 'fixture', **kw})
    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'hub.py'), *args], env=self.env,
                              capture_output=True, text=True, encoding='utf-8', timeout=8)
    def revision(self, tid):
        return hub.task_digest(next(t for t in self.state()['tasks'] if t['id'] == tid))['revision']

    def test_registry_persists_unique_ids_roles_models_without_joining_clients(self):
        lead = self.create(role='lead'); worker = self.create(); reviewer = self.create(role='reviewer')
        st = self.state()
        self.assertEqual(len({lead, worker, reviewer, 'codex'}), 4)
        self.assertEqual(st['lead'], lead)
        for aid in (lead, worker, reviewer):
            self.assertEqual(st['agents'][aid]['client'], 'codex')
            self.assertEqual(st['agents'][aid]['model'], 'gpt6')
            self.assertIn(aid, st['session']['participants'])
            self.assertFalse(st['agents'][aid]['online'])
        self.assertFalse((hub.DATA / '.presence').exists(), 'registration must not fake a join/read heartbeat')
        self.assertEqual(hub.agent_context(st, lead)['identity']['role'], 'lead')
        self.assertEqual(hub.agent_context(st, worker)['identity']['role'], 'worker')
        self.assertEqual(hub.agent_context(st, reviewer)['identity']['role'], 'reviewer')
        self.assertFalse(st['session']['migration_required'])

    def test_original_ids_history_and_config_are_not_rewritten(self):
        self.post('claude', 'task', task='OLD', to=['codex'])
        old = hub.BOARD.read_bytes(); config = hub.CONFIG.read_bytes()
        self.create(role='lead')
        self.assertTrue(hub.BOARD.read_bytes().startswith(old))
        self.assertEqual(self.state()['tasks'][0]['owner'], 'codex')
        self.assertEqual(hub.CONFIG.read_bytes(), config)

    def test_registration_retry_and_stale_edits_are_guarded(self):
        data = {'action': 'instance_create', 'session': 'main', 'client': 'codex', 'model': 'gpt6',
                'name': 'same intent', 'role': 'worker', 'expected_revision': -1, 'request_id': 'retry-instance'}
        first = hub.session_action(data); self.assertEqual(first, hub.session_action(data))
        self.assertEqual(len(self.state()['agents']), 5)
        with self.assertRaises(hub.Reject): hub.session_action({**data, 'model': 'different'})
        with self.assertRaisesRegex(hub.Reject, '变化'):
            self.edit(first['instance'], expected_revision=-1)
        self.edit(first['instance'], name='renamed', model='user-selected-model')
        self.assertEqual(self.state()['agents'][first['instance']]['model'], 'user-selected-model')

    def test_registry_fields_and_privilege_validation(self):
        for fields in ({'client': '../codex'}, {'client': 'pi'}, {'client': 'codex-fake'}, {'role': 'owner'},
                       {'name': ''}, {'name': 'x\ny'}, {'model': ['gpt6']}, {'model': 'x' * 101}, {'expected_revision': True}):
            with self.assertRaises(hub.Reject): self.create(**fields)
        worker = self.create()
        with self.assertRaises(hub.Reject): self.edit(worker, client='claude')
        with self.assertRaises(hub.Reject): self.post(worker, 'instance', instance={'id': worker, 'role': 'lead'})
        with self.assertRaises(hub.Reject): self.post('codex-forged', 'join')
        with self.assertRaises(hub.Reject): self.edit('claude', role='worker')

    def test_same_client_task_ownership_and_independent_review(self):
        lead = self.create(role='lead'); worker = self.create(); reviewer = self.create(role='reviewer')
        self.post(lead, 'task', task='W', to=[worker], reviewer=reviewer)
        for wrong in ('codex', lead, reviewer):
            with self.assertRaises(hub.Reject): self.post(wrong, 'claim', task='W')
        self.post(worker, 'claim', task='W'); self.post(worker, 'done', task='W')
        with self.assertRaises(hub.Reject): self.post(worker, 'review', task='W', verdict='pass')
        self.post(reviewer, 'review', task='W', verdict='pass')
        self.assertEqual(self.state()['tasks'][0]['state'], '已完成')

    def test_same_client_workers_keep_focused_scopes_and_refresh_on_lead_change(self):
        lead = self.create(role='lead'); a = self.create(); b = self.create()
        self.post(lead, 'task', task='A', to=[a], body='OWN_A')
        self.post(lead, 'task', task='B', to=[b], body='PRIVATE_PEER')
        self.post(b, 'say', body='PRIVATE_PEER_MESSAGE')
        view = hub.agent_context(self.state(), a)
        self.assertNotIn('PRIVATE_PEER', json.dumps(view)); self.assertEqual([t['id'] for t in view['tasks']], ['A'])
        self.assertEqual(set(view['session']['instances']), {lead, a})
        self.assertEqual(len(hub.agent_context(self.state(), lead)['tasks']), 2)
        revision = view['context']['revision']; self.edit(b, role='lead')
        view = hub.agent_context(self.state(), a, since=revision)
        self.assertTrue(view['context']['refresh'])
        self.assertEqual(view['session']['lead'], b)

    def test_distinct_windows_cannot_release_or_reuse_siblings_locks(self):
        a = self.create(); b = self.create()
        for aid, tid in ((a, 'A'), (b, 'B')):
            self.post('claude', 'task', task=tid, to=[aid], files=['workspace/shared.py'])
            self.post(aid, 'claim', task=tid)
        self.post(a, 'lock', task='A', task_revision=self.revision('A'), files=['workspace/shared.py'])
        self.post(b, 'unlock')
        self.assertEqual(next(iter(self.state()['locks'].values()))['agent'], a)
        with self.assertRaises(hub.Reject): self.post(b, 'lock', task='B', task_revision=self.revision('B'), files=['workspace/shared.py'])
        self.post(a, 'unlock', task='A')
        self.post(b, 'lock', task='B', task_revision=self.revision('B'), files=['workspace/shared.py'])

    def test_media_family_gate_and_capability_are_instance_specific(self):
        a = self.create(); b = self.create(); r = self.create(client='reasonix')
        self.post(a, 'capability', kind='image_generate', availability='available')
        with self.assertRaises(hub.Reject): self.post(r, 'capability', kind='image_generate', availability='available')
        with self.assertRaises(hub.Reject): self.post('claude', 'task', task='BAD', to=[r], kind='image_generate')
        self.post('claude', 'task', task='IMAGE', to=[b], kind='image_generate')
        with self.assertRaises(hub.Reject): self.post(b, 'claim', task='IMAGE')
        self.post(b, 'capability', kind='image_generate', availability='available')
        self.post(b, 'claim', task='IMAGE')
        self.assertNotIn('image_generate', self.state()['agents']['codex']['capabilities'])

    def test_usage_is_separate_per_instance_and_aggregated_without_collisions(self):
        a = self.create(); b = self.create()
        fields = dict(usage_id='same-native-call-number', input_tokens=10, output_tokens=5,
                      provider='fixture', model='actual-model-from-usage', usage_source='fixture record')
        for aid in (a, b, 'codex'): self.post(aid, 'usage', **fields)
        self.post(a, 'usage', **fields)
        st = self.state(); self.assertEqual(st['token_usage'][a]['total'], 15)
        self.assertEqual(st['token_usage'][b]['total'], 15)
        self.assertEqual(st['token_usage_clients']['codex']['total'], 45)
        self.assertEqual(st['token_usage_clients']['codex']['reports'], 3)
        self.assertEqual(set(hub.agent_context(st, a)['token_usage']), {a})
        sid = hub.session_action({'action': 'create', 'title': 'separate'})['session']
        other = self.state(sid)
        self.assertNotIn(a, other['agents']); self.assertIn(a, other['usage_agents_all_sessions'])
        self.assertEqual(other['token_usage_clients_all_sessions']['codex']['total'], 45)
        self.assertIsNone(other['token_usage_clients']['codex']['total'])

    def test_cli_ids_listener_slots_and_unread_cursors_are_independent(self):
        a = self.create(); b = self.create()
        for aid in (a, b): self.post('claude', 'say', to=[aid], body='ONLY_' + aid)
        with hub.listener_slot('main', a):
            self.assertEqual(self.cli('listen', '--agent', a, '--session', 'main', '--timeout', '1').returncode, 2)
            r = self.cli('listen', '--agent', b, '--session', 'main', '--timeout', '1')
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((hub.DATA / '.seen' / f'main.{b}.txt').exists())
        self.assertFalse((hub.DATA / '.seen' / f'main.{a}.txt').exists())
        r = self.cli('listen', '--agent', a, '--session', 'main', '--timeout', '1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('ONLY_' + a, r.stdout); self.assertNotIn('ONLY_' + b, r.stdout)
        self.assertEqual(json.loads(r.stdout)['identity']['id'], a)
        self.assertFalse((hub.DATA / '.seen' / 'main.codex.txt').exists())

    def test_claude_native_bindings_are_one_to_one_per_instance(self):
        a = self.create(client='claude'); b = self.create(client='claude')
        for aid in (a, b): self.post(aid, 'join')
        hub.bind_client('main', a, 'native-a'); hub.bind_client('main', b, 'native-b')
        with self.assertRaises(hub.Reject): hub.bind_client('main', a, 'native-b')
        with self.assertRaises(hub.Reject): hub.bind_client('main', a, 'native-c')
        result = hub.stop_guard({'hook_event_name': 'Stop', 'session_id': 'native-a'})
        self.assertIn(a, result['reason']); self.assertNotIn(b, result['reason'])
        hub.bind_client('main', a, 'native-a', detach=True); hub.bind_client('main', a, 'native-c')

    def test_disabled_instances_stop_without_retiring_other_windows(self):
        a = self.create(); b = self.create()
        members = [x for x in self.state()['session']['participants'] if x != a]
        hub.session_action({'session': 'main', 'action': 'settings', 'participants': members})
        self.assertEqual(hub.agent_context(self.state(), a)['continuation']['action'], 'exit')
        self.assertTrue(self.state()['agents'][b]['enabled'])
        with self.assertRaises(hub.Reject): self.post(a, 'say')
        self.post(a, 'unlock'); self.post(b, 'say')
        sid = hub.session_action({'action': 'create', 'title': 'other'})['session']
        r = self.cli('read', '--agent', a, '--session', sid)
        self.assertEqual(r.returncode, 2)
        self.assertFalse((hub.DATA / '.presence' / f'{sid}.{a}.json').exists())

    def test_concurrent_distinct_cli_lock_attempts_have_one_winner(self):
        a = self.create(); b = self.create()
        processes = [subprocess.Popen([sys.executable, str(ROOT / 'hub.py'), 'post', '--from', aid,
            '--session', 'main', '--type', 'lock', '--files', 'workspace/concurrent.py', '--body', 'fixture'],
            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for aid in (a, b)]
        for p in processes: p.communicate(timeout=8)
        self.assertEqual(sorted(p.returncode for p in processes), [0, 2])
