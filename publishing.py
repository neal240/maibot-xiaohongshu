"""Durable publish attempt guard and safe selection of local user assets."""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path


class PublishState:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute('''CREATE TABLE IF NOT EXISTS attempts
            (account TEXT PRIMARY KEY, state TEXT NOT NULL, attempted_at INTEGER NOT NULL)''')
        self.db.commit()

    def status(self, account: str) -> dict:
        row = self.db.execute('SELECT state,attempted_at FROM attempts WHERE account=?', (account,)).fetchone()
        return {'state': row[0], 'attempted_at': row[1]} if row else {'state': 'idle', 'attempted_at': 0}

    def begin(self, account: str, interval: int, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else now
        with self.db:
            status = self.status(account)
            if status['state'] in {'submitting', 'uncertain'}: return False
            if status['attempted_at'] and now - status['attempted_at'] < interval: return False
            self.db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)', (account, 'submitting', now))
            return True

    def finish(self, account: str, *, success: bool) -> None:
        with self.db:
            self.db.execute('UPDATE attempts SET state=? WHERE account=? AND state=?',
                            ('published' if success else 'uncertain', account, 'submitting'))

    def clear_uncertain(self, account: str) -> bool:
        with self.db:
            result = self.db.execute('DELETE FROM attempts WHERE account=? AND state IN (?,?)',
                                     (account, 'submitting', 'uncertain'))
            return bool(result.rowcount)

    def close(self) -> None: self.db.close()


def image_paths(directory: Path, names: list[str]) -> list[Path]:
    if not 1 <= len(names) <= 9: raise ValueError('需要配置 1 至 9 张素材图片')
    root = directory.resolve()
    result = []
    for name in names:
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ValueError('素材只接受文件名')
        candidate = (root / name).resolve()
        if candidate.parent != root or not candidate.is_file():
            raise ValueError('素材文件不存在或路径不安全')
        result.append(candidate)
    return result
