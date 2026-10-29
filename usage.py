"""Aggregate model usage; never store prompts or message contents."""
from __future__ import annotations
import sqlite3
from datetime import date, timedelta
from pathlib import Path


class Usage:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute('''CREATE TABLE IF NOT EXISTS usage (
            account TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
            calls INTEGER NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
            unknown_calls INTEGER NOT NULL, PRIMARY KEY(account, day, kind))''')
        self.db.commit()

    def record(self, account: str, day: date, kind: str, result: object) -> None:
        r = result if isinstance(result, dict) else {}
        def count(key):
            value = r.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
        inp, out, total = count('prompt_tokens'), count('completion_tokens'), count('total_tokens')
        if not total: total = inp + out
        unknown = int(total <= 0)
        with self.db:
            self.db.execute('''INSERT INTO usage VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(account,day,kind)
                DO UPDATE SET calls=calls+1,input_tokens=input_tokens+excluded.input_tokens,
                output_tokens=output_tokens+excluded.output_tokens,total_tokens=total_tokens+excluded.total_tokens,
                unknown_calls=unknown_calls+excluded.unknown_calls''',
                (account, day.isoformat(), kind, 1, inp, out, total, unknown))
            self.db.execute('DELETE FROM usage WHERE day<?', ((day - timedelta(days=90)).isoformat(),))

    def get(self, account: str, day: date, kind: str) -> dict:
        row = self.db.execute('''SELECT calls,input_tokens,output_tokens,total_tokens,unknown_calls FROM usage
            WHERE account=? AND day=? AND kind=?''', (account, day.isoformat(), kind)).fetchone()
        return dict(zip(('calls', 'input_tokens', 'output_tokens', 'total_tokens', 'unknown_calls'), row or (0, 0, 0, 0, 0)))

    def close(self) -> None: self.db.close()
