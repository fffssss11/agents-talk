"""Source-backed workflow metadata, independent review and integration sequencing."""
import json
from pathlib import Path
import tempfile
import unittest
from test_hub import hub


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agents-talk-workflow-')
        hub.DATA = Path(self.temp.name); hub.BOARD = hub.DATA / 'board.jsonl'

    def tearDown(self): self.temp.cleanup()

    def post(self, who, typ, **kw):
        return hub.post({'session': 'main', 'from': who, 'type': typ, 'body': 'fixture', **kw})

    def task(self, tid='BUILD', **kw):
        return self.post('claude', 'task', task=tid, to=['codex'], **kw)

    def current(self, tid='BUILD'):
        return next(t for t in hub.read_state('main')['tasks'] if t['id'] == tid)

    def arrange(self, tid='BUILD', **kw):
        return self.post('claude', 'workflow', task=tid, task_revision=hub.task_digest(self.current(tid))['revision'], **kw)

    def test_legacy_metadata_stays_unknown_without_rewriting_board(self):
        self.task()
        before = hub.BOARD.read_bytes()
        self.assertNotIn('reviewer', self.current())
        self.assertNotIn('stage', hub.task_digest(self.current()))
        self.assertEqual(hub.BOARD.read_bytes(), before)

    def test_reviewer_validation_and_independent_designation(self):
        for reviewer in ('pi', 'zcode', 'human', 'codex', [], None):
            with self.assertRaises(hub.Reject): self.task(reviewer=reviewer)
        self.task(reviewer='reasonix')
        self.post('codex', 'claim', task='BUILD'); self.post('codex', 'done', task='BUILD')
        with self.assertRaisesRegex(hub.Reject, '指定验收人'): self.post('claude', 'review', task='BUILD', verdict='pass')
        with self.assertRaisesRegex(hub.Reject, '自己'): self.post('codex', 'review', task='BUILD', verdict='pass')
        review = self.post('reasonix', 'review', task='BUILD', verdict='pass')
        digest = hub.task_digest(self.current())
        self.assertEqual(digest['reviewer'], 'reasonix')
        self.assertEqual(digest['review']['by'], 'reasonix')
        self.assertEqual(digest['review']['source_id'], review['id'])

    def test_workflow_update_requires_lead_fresh_revision_and_open_task(self):
        created = self.task(); revision = hub.task_digest(self.current())['revision']
        with self.assertRaises(hub.Reject): self.post('reasonix', 'workflow', task='BUILD', task_revision=revision, reviewer='claude')
        with self.assertRaises(hub.Reject): self.post('claude', 'workflow', task='BUILD', reviewer='reasonix')
        event = self.arrange(reviewer='reasonix', request_id='same-plan')
        repeat = self.post('claude', 'workflow', task='BUILD', task_revision=revision, reviewer='reasonix', request_id='same-plan')
        self.assertEqual(repeat['id'], event['id'])
        with self.assertRaisesRegex(hub.Reject, 'revision'): self.post('claude', 'workflow', task='BUILD', task_revision=revision, reviewer='claude')
        self.assertEqual(self.current()['source_id'], created['id'])
        self.assertNotIn('reviewer', next(m for m in hub.load() if m['id'] == created['id']))
        self.arrange(integration_plan='Deliver the verified module to the integration owner')
        self.assertEqual(self.current()['reviewer'], 'reasonix', 'patch must preserve unrelated metadata')
        self.arrange(reviewer='')
        self.assertEqual(self.current()['reviewer'], '')
        self.post('codex', 'claim', task='BUILD'); self.post('codex', 'done', task='BUILD')
        self.post('claude', 'review', task='BUILD', verdict='pass')
        with self.assertRaisesRegex(hub.Reject, '已完成'): self.arrange(reviewer='reasonix')

    def test_metadata_only_on_task_or_workflow_and_integration_requires_dependencies(self):
        for data in ({'stage': 'other'}, {'stage': 'integration'}, {'integration_plan': 'x' * 401}, {'integration_plan': []}):
            with self.assertRaises(hub.Reject): self.task(**data)
        self.task()
        with self.assertRaises(hub.Reject): self.arrange(stage='integration')
        with self.assertRaises(hub.Reject): self.arrange()
        with self.assertRaises(hub.Reject): self.post('codex', 'say', task='BUILD', reviewer='reasonix')
        with self.assertRaises(hub.Reject): self.arrange(depends_on=['BUILD'], reviewer='reasonix')

    def test_integration_waits_for_actual_review_and_reports_own_review(self):
        self.task(reviewer='reasonix')
        self.post('claude', 'task', task='INTEGRATE', to=['claude'], depends_on=['BUILD'],
                  stage='integration', reviewer='codex', integration_plan='Merge module, run end-to-end checks, publish output')
        with self.assertRaises(hub.Reject): self.post('claude', 'claim', task='INTEGRATE')
        self.post('codex', 'claim', task='BUILD'); self.post('codex', 'done', task='BUILD')
        self.assertFalse(self.current('INTEGRATE')['ready'])
        self.post('reasonix', 'review', task='BUILD', verdict='fail')
        self.assertFalse(self.current('INTEGRATE')['ready'])
        self.post('codex', 'claim', task='BUILD'); self.post('codex', 'done', task='BUILD')
        self.post('reasonix', 'review', task='BUILD', verdict='pass')
        self.post('claude', 'claim', task='INTEGRATE'); self.post('claude', 'done', task='INTEGRATE')
        self.post('codex', 'review', task='INTEGRATE', verdict='pass')
        self.assertEqual(self.current('INTEGRATE')['state'], '已完成')
        self.assertEqual(hub.task_digest(self.current('INTEGRATE'))['stage'], 'integration')

    def test_designated_reviewer_does_not_expand_focused_context(self):
        self.post('claude', 'task', task='PEER', to=['reasonix'], reviewer='codex', body='PRIVATE_PEER_BODY')
        st = hub.agent_context(hub.read_state('main'), 'codex')
        self.assertNotIn('PRIVATE_PEER_BODY', json.dumps(st))
        self.assertNotIn('PEER', [t['id'] for t in st['tasks']])

    def test_reassign_cannot_create_self_review(self):
        self.task(reviewer='reasonix')
        with self.assertRaisesRegex(hub.Reject, '验收人'):
            hub.session_action({'session': 'main', 'action': 'reassign', 'task': 'BUILD', 'to': 'reasonix'})
        self.arrange(reviewer='claude')
        hub.session_action({'session': 'main', 'action': 'reassign', 'task': 'BUILD', 'to': 'reasonix'})
        self.assertEqual(self.current()['owner'], 'reasonix')

    def test_pause_and_controls_still_gate_workflow_changes(self):
        self.task()
        hub.session_action({'session': 'main', 'action': 'paused'})
        with self.assertRaises(hub.Reject): self.arrange(reviewer='reasonix')
        hub.session_action({'session': 'main', 'action': 'active'})
        with self.assertRaisesRegex(hub.Reject, 'ack'): self.arrange(reviewer='reasonix')
        for m in hub.pending(hub.load(), 'main', 'claude'):
            self.post('claude', 'ack', reply_to=m['id'])
        self.arrange(reviewer='reasonix')
