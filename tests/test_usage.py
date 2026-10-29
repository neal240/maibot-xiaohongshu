import tempfile
import unittest
from datetime import date
from pathlib import Path
from usage import Usage


class UsageTests(unittest.TestCase):
    def test_counts_are_persisted_and_isolated_by_account_day_and_kind(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'usage.sqlite'
            db = Usage(path)
            day = date(2026, 10, 30)
            db.record('a', day, 'browse', {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150})
            db.record('a', day, 'browse', {'prompt_tokens': 20, 'completion_tokens': 5})
            db.record('a', day, 'browse', {'success': False})
            self.assertEqual(db.get('a', day, 'browse'), {'calls': 3, 'input_tokens': 120,
                'output_tokens': 55, 'total_tokens': 175, 'unknown_calls': 1})
            self.assertEqual(db.get('a', day, 'publish')['calls'], 0)
            self.assertEqual(db.get('b', day, 'browse')['calls'], 0)
            db.close()
            db = Usage(path)
            self.assertEqual(db.get('a', day, 'browse')['total_tokens'], 175)
            db.close()
