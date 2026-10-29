import sqlite3
import tempfile
import unittest
from pathlib import Path

from xhs_policy import Decisions, Policy

A = 'a' * 24
B = 'b' * 24
C = 'c' * 24


class PolicyTests(unittest.TestCase):
    def test_only_allowlisted_sender_in_matching_private_conversation(self):
        p = Policy(frozenset({B}), 1)
        self.assertTrue(p.permits(B, B, group=False))
        self.assertFalse(p.permits(C, C, group=False))
        self.assertFalse(p.permits(B, C, group=False))
        self.assertFalse(p.permits(B, B, group=True))
        self.assertFalse(Policy(frozenset(), 1).permits(B, B, group=False))

    def test_invalid_configuration_fails_closed(self):
        for p in (-0.1, 1.1, float('nan')):
            with self.assertRaises(ValueError): Policy(frozenset(), p)
        with self.assertRaises(ValueError): Policy(frozenset({'123456'}), 1)

    def test_restart_deduplication_and_no_nonwhitelist_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite'
            db = Decisions(path)
            p = Policy(frozenset({B}), 0.6)
            self.assertFalse(db.claim(A, 'other', C, C, False, p, lambda: 0))
            self.assertFalse(db.claim(A, 'group', B, B, True, p, lambda: 0))
            self.assertTrue(db.claim(A, 'm1', B, B, False, p, lambda: 0.1))
            db.acknowledge(A, 'm1')
            self.assertTrue(db.claim(A, 'm2', B, B, False, p, lambda: 0.9))
            self.assertFalse(db.reply_allowed(A, B))
            db.acknowledge(A, 'm2')
            db.close()
            db = Decisions(path)
            self.assertFalse(db.claim(A, 'm1', B, B, False, p, lambda: 0.1))
            self.assertFalse(db.claim(A, 'm2', B, B, False, p, lambda: 0.1))
            self.assertFalse(db.claim(A, 'm3', B, B, False, Policy(frozenset(), 1), lambda: 0))
            self.assertEqual(db.conn.execute('SELECT count(*) FROM decisions').fetchone()[0], 2)
            db.close()

    def test_probability_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Decisions(Path(directory) / 'state.sqlite')
            self.assertTrue(db.claim(A, 'zero', B, B, False, Policy(frozenset({B}), 0), lambda: 0))
            self.assertFalse(db.reply_allowed(A, B))
            self.assertTrue(db.claim(A, 'all', B, B, False, Policy(frozenset({B}), 1), lambda: .999999))
            self.assertTrue(db.reply_allowed(A, B))
            db.close()

    def test_unacknowledged_delivery_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite'
            p = Policy(frozenset({B}), 0)
            db = Decisions(path)
            self.assertTrue(db.claim(A, 'pending', B, B, False, p))
            db.close()
            db = Decisions(path)
            self.assertTrue(db.claim(A, 'pending', B, B, False, p))
            self.assertFalse(db.reply_allowed(A, B))
            db.acknowledge(A, 'pending')
            self.assertFalse(db.claim(A, 'pending', B, B, False, p))
            db.close()

    def test_inflight_is_not_automatically_replayed_after_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite'
            policy = Policy(frozenset({B}), 1)
            db = Decisions(path)
            self.assertTrue(db.claim(A, 'inflight', B, B, False, policy))
            db.mark_inflight(A, 'inflight')
            db.close()
            db = Decisions(path)
            self.assertEqual(db.uncertain_count(A), 1)
            self.assertFalse(db.claim(A, 'inflight', B, B, False, policy))
            db.acknowledge(A, 'inflight')
            self.assertEqual(db.uncertain_count(A), 0)
            db.close()

    def test_new_whitelist_member_gets_new_baseline_after_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Decisions(Path(directory) / 'state.sqlite')
            self.assertEqual(db.sync_baselines(A, frozenset({B}), 100), {B: 100})
            self.assertEqual(db.sync_baselines(A, frozenset({B, C}), 200), {B: 100, C: 200})
            self.assertEqual(db.sync_baselines(A, frozenset({C}), 300), {C: 200})
            self.assertEqual(db.sync_baselines(A, frozenset({B, C}), 400), {B: 400, C: 200})
            db.close()


if __name__ == '__main__':
    unittest.main()
