"""Account-scoped, bounded note summaries, not model training."""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path


class NoteMemory:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute('''CREATE TABLE IF NOT EXISTS notes (
            account TEXT NOT NULL, note_id TEXT NOT NULL, keyword TEXT NOT NULL,
            summary TEXT NOT NULL, saved_at INTEGER NOT NULL,
            PRIMARY KEY (account, note_id))''')
        self.db.commit()

    def contains(self, account: str, note_id: str) -> bool:
        return self.db.execute('SELECT 1 FROM notes WHERE account=? AND note_id=? AND saved_at>=?',
                               (account, note_id, int(time.time()) - 30 * 86400)).fetchone() is not None

    def put(self, account: str, note_id: str, keyword: str, summary: str) -> None:
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?)',
                            (account, note_id, keyword[:80], summary[:2000], int(time.time())))
            self.db.execute('DELETE FROM notes WHERE saved_at < ?', (int(time.time()) - 30 * 86400,))
            self.db.execute('''DELETE FROM notes WHERE rowid IN
                (SELECT rowid FROM notes WHERE account=? ORDER BY saved_at DESC LIMIT -1 OFFSET 500)''',
                (account,))

    def search(self, account: str, query: str, limit: int = 5) -> list[tuple[str, str, str]]:
        # Escape LIKE wildcards; content is data, not SQL.
        escaped = query[:80].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        return self.db.execute('''SELECT note_id, keyword, summary FROM notes WHERE account=? AND saved_at>=?
            AND (summary LIKE ? ESCAPE '\\' OR keyword LIKE ? ESCAPE '\\')
            ORDER BY saved_at DESC LIMIT ?''', (account, int(time.time()) - 30 * 86400,
                                                '%' + escaped + '%', '%' + escaped + '%', limit)).fetchall()

    def close(self) -> None:
        self.db.close()
