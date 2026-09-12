"""Continuation regressions with isolated board and native-hook fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from test_hub import hub, ROOT


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agents-talk-listen-')
        hub.DATA = Path(self.temp.name)
        hub.BOARD = hub.DATA / 'board.jsonl'
        self.env = {**os.environ, 'AGENTS_TALK_DATA': self.temp.name, 'PYTHONUTF8': '1'}

    def tearDown(self):
        self.temp.cleanup()

    def post(self, who, typ, **kw):
        return hub.post({'from': who, 'type': typ, 'session': 'main', 'body': 'fixture evidence', **kw})

    def cli(self, *args, code=0, stdin=None):
        result = subprocess.run([sys.executable, str(ROOT / 'hub.py'), *args], env=self.env,
                                capture_output=True, text=True, encoding='utf-8', input=stdin, timeout=12)
        self.assertEqual(result.returncode, code, result.stderr)
        return json.loads(result.stdout) if code in (0, 3) else result.stderr

    def listen(self, aid='reasonix', **kw):
        return self.cli('listen', '--agent', aid, '--session', 'main', '--timeout', '1', '--poll', '.1', **kw)

    def state(self):
        return hub.derive(hub.load(), hub.config(), 'main')

    def test_repeated_idle_timeouts_then_codex_dispatch(self):
        hub.session_action({'action': 'settings', 'session': 'main', 'lead': 'codex'})
        self.listen()  # Deliver setting change, then no messages remain.
        for _ in range(3):
            r = self.listen()
            self.assertTrue(r['timeout'])
            self.assertEqual(r['continuation']['action'], 'listen')
            self.assertNotIn('tasks', r)
        self.post('codex', 'task', task='AFTER-IDLE', to=['reasonix'])
        self.assertEqual(self.listen()['continuation']['task_ids'], ['AFTER-IDLE'])
        r = self.listen()  # Cursor already consumed task, but work is still pending.
        self.assertEqual(r['continuation']['action'], 'execute')
        self.post('reasonix', 'claim', task='AFTER-IDLE')
        self.post('reasonix', 'done', task='AFTER-IDLE')
        self.assertTrue(self.listen()['timeout'])
        self.post('codex', 'review', task='AFTER-IDLE', verdict='fail')
        self.assertEqual(self.listen()['continuation']['action'], 'execute')

    def test_pause_resume_exit_and_join(self):
        hub.session_action({'action': 'paused', 'session': 'main'})
        r = self.listen(); self.assertEqual(r['continuation']['action'], 'ack')
        for m in r['pending_interventions']: self.post('reasonix', 'ack', reply_to=m['id'])
        self.assertEqual(self.listen()['continuation']['action'], 'paused_wait')
        hub.session_action({'action': 'active', 'session': 'main'})
        r = self.listen(); self.assertEqual(r['continuation']['action'], 'ack')
        for m in r['pending_interventions']: self.post('reasonix', 'ack', reply_to=m['id'])
        self.post('reasonix', 'leave')
        self.assertEqual(self.listen()['continuation']['action'], 'exit')
        self.assertTrue(self.state()['agents']['reasonix']['detached'])
        self.post('reasonix', 'join')
        self.assertEqual(self.listen()['continuation']['action'], 'listen')
        hub.session_action({'action': 'ended', 'session': 'main'})
        self.assertEqual(self.listen()['continuation']['action'], 'exit')
        self.assertFalse(self.state()['agents']['reasonix']['needs_attention'])

    def test_disabled_member_and_scope_are_preserved(self):
        self.assertEqual(self.listen('zcode')['continuation']['action'], 'exit')
        self.post('claude', 'task', task='PRIVATE', to=['codex'])
        r = self.listen()
        self.assertNotIn('PRIVATE', json.dumps(r))
        self.assertNotIn('team_health', r)
        self.assertIn('team_health', self.cli('read', '--agent', 'claude', '--session', 'main'))

    def test_only_agent_reads_refresh_read_heartbeat(self):
        self.post('reasonix', 'join')
        self.assertTrue(self.state()['agents']['reasonix']['needs_attention'])
        self.listen()
        p = hub.DATA / '.presence/main.reasonix.json'
        presence = json.loads(p.read_text())
        presence['read_time'] = time.time() - 130
        p.write_text(json.dumps(presence))
        self.post('reasonix', 'say')
        self.assertTrue(self.state()['agents']['reasonix']['needs_attention'])
        hub.agent_context(self.state(), 'reasonix')  # Web preview never records an agent read.
        self.assertEqual(json.loads(p.read_text())['read_time'], presence['read_time'])
        self.listen()
        self.assertFalse(self.state()['agents']['reasonix']['needs_attention'])

    def test_stop_hook_scoped_bounded_and_read_only(self):
        event = {'hook_event_name': 'Stop', 'session_id': 'native-fixture', 'stop_hook_active': False}
        self.assertEqual(hub.stop_guard(event), {})
        with self.assertRaises(hub.Reject): hub.bind_client('main', 'claude', 'native-fixture')
        self.post('claude', 'join')
        self.cli('bind', '--agent', 'claude', '--session', 'main', '--client-session', 'native-fixture')
        p = hub.DATA / '.presence/main.claude.json'; before = p.read_bytes()
        r = self.cli('stop-hook', stdin=json.dumps(event))
        self.assertEqual(r['decision'], 'block')
        self.assertEqual(p.read_bytes(), before)
        self.assertFalse((hub.DATA / '.seen').exists())
        self.assertEqual(hub.stop_guard({**event, 'session_id': 'other-window'}), {})
        self.assertEqual(hub.stop_guard({**event, 'stop_hook_active': True}), {})
        self.assertEqual(hub.stop_guard({**event, 'hook_event_name': 'StopFailure'}), {})
        self.post('claude', 'leave')
        self.assertEqual(hub.stop_guard(event), {})
        self.post('claude', 'join')
        self.assertEqual(hub.stop_guard(event)['decision'], 'block')
        hub.bind_client('main', 'claude', 'native-fixture', detach=True)
        self.assertEqual(hub.stop_guard(event), {})

    def test_hook_fail_open_and_bind_validation(self):
        self.assertEqual(self.cli('stop-hook', stdin='invalid json'), {})
        self.assertEqual(self.cli('stop-hook', stdin='[]'), {})
        self.assertEqual(self.cli('stop-hook', stdin=json.dumps({'hook_event_name': 'Stop', 'session_id': '../wrong'})), {})
        self.cli('bind', '--agent', 'reasonix', '--session', 'main', '--client-session', 'fixture', code=2)
        self.cli('listen', '--agent', 'reasonix', '--session', 'main', '--task', 'wrong', code=2)
        self.cli('listen', '--session', 'main', code=2)


if __name__ == '__main__':
    unittest.main()
