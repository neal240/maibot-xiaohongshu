import json
import tempfile
import unittest
from pathlib import Path
from receiver import prepare_text
from xhs_policy import Decisions, Policy

A, B, C = 'a' * 24, 'b' * 24, 'c' * 24


class ReceiverTests(unittest.TestCase):
    def test_rejects_nonwhitelisted_and_groups_before_reading_content(self):
        class NoRead(dict):
            def get(self, key, default=None):
                if key == 'content': raise AssertionError('content should not be read')
                return super().get(key, default)
        with tempfile.TemporaryDirectory() as d:
            db = Decisions(Path(d) / 'a.sqlite')
            msg = NoRead(sender_id=C, receiver_id=A, group_chat=False)
            self.assertIsNone(prepare_text(msg, A, C, Policy(frozenset({B}), 1), db, not_before_ms=0))
            msg = NoRead(sender_id=B, receiver_id=A, group_chat=True)
            self.assertIsNone(prepare_text(msg, A, B, Policy(frozenset({B}), 1), db, not_before_ms=0))
            db.close()

    def test_only_new_allowlisted_direct_text_is_delivered_once(self):
        with tempfile.TemporaryDirectory() as d:
            db = Decisions(Path(d) / 'a.sqlite')
            msg = {'sender_id': B, 'receiver_id': A, 'group_chat': False, 'revoked': False,
                   'id': '1', 'created_at': 1234,
                   'content': json.dumps({'content_type': 1, 'content': 'hello'})}
            policy = Policy(frozenset({B}), 1)
            self.assertIsNone(prepare_text(msg, A, B, policy, db, not_before_ms=1235))
            result = prepare_text(msg, A, B, policy, db, not_before_ms=1234)
            self.assertEqual(result['raw_message'][0]['data'], 'hello')
            db.acknowledge(A, '1')
            self.assertIsNone(prepare_text(msg, A, B, policy, db, not_before_ms=1234))
            msg['id'] = '2'; msg['content'] = json.dumps({'content_type': 3, 'content': 'card'})
            self.assertIsNone(prepare_text(msg, A, B, policy, db, not_before_ms=0))
            db.close()

    def test_forwarded_note_only_after_whitelist_check(self):
        with tempfile.TemporaryDirectory() as d:
            db = Decisions(Path(d) / 'a.sqlite')
            card = json.dumps({'content_type': 3, 'content': json.dumps({'link':
                'xhsdiscover://item/' + C + '?xsec_token=secret'})})
            msg = {'sender_id': B, 'receiver_id': A, 'group_chat': False, 'id': 'card',
                   'created_at': 1234, 'content': card}
            seen = []
            result = prepare_text(msg, A, B, Policy(frozenset({B}), 0), db, not_before_ms=0,
                                  on_note=lambda *v: seen.append(v))
            self.assertIn(C, result['raw_message'][0]['data'])
            self.assertEqual(seen, [(B, C, 'secret')])
            self.assertFalse(db.reply_allowed(A, B))
            db.close()
