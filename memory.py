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
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(notes)')}
        for name, definition in (('title', "TEXT NOT NULL DEFAULT ''"),
                                 ('body', "TEXT NOT NULL DEFAULT ''"),
                                 ('status', "TEXT NOT NULL DEFAULT 'complete'")):
            if name not in columns: self.db.execute(f'ALTER TABLE notes ADD COLUMN {name} {definition}')
        self.db.execute("UPDATE notes SET status='failed' WHERE status='reading'")
        self.db.commit()

    def contains(self, account: str, note_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM notes WHERE account=? AND note_id=? AND saved_at>=? AND status='complete'",
                               (account, note_id, int(time.time()) - 30 * 86400)).fetchone() is not None

    def put(self, account: str, note_id: str, keyword: str, summary: str) -> None:
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO notes (account,note_id,keyword,summary,saved_at) VALUES (?,?,?,?,?)',
                            (account, note_id, keyword[:80], summary[:2000], int(time.time())))
            self._prune(account)

    def _prune(self, account: str) -> None:
        self.db.execute('DELETE FROM notes WHERE saved_at < ?', (int(time.time()) - 30 * 86400,))
        self.db.execute('''DELETE FROM notes WHERE rowid IN
            (SELECT rowid FROM notes WHERE account=? ORDER BY saved_at DESC, rowid DESC LIMIT -1 OFFSET 500)''',
            (account,))

    def record_view(self, account: str, note_id: str, keyword: str, title: str, body: str) -> None:
        with self.db:
            self.db.execute('''INSERT INTO notes (account,note_id,keyword,summary,saved_at,title,body,status)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(account,note_id) DO UPDATE SET
                keyword=excluded.keyword,summary='',saved_at=excluded.saved_at,title=excluded.title,
                body=excluded.body,status=excluded.status''',
                (account, note_id, keyword[:80], '', int(time.time()), title[:200], body[:6000], 'reading'))
            self._prune(account)

    def finish_view(self, account: str, note_id: str, summary: str | None) -> None:
        text = summary.strip()[:2000] if isinstance(summary, str) else ''
        with self.db:
            self.db.execute('UPDATE notes SET summary=?,status=? WHERE account=? AND note_id=?',
                            (text, 'complete' if text else 'failed', account, note_id))

    def history(self, account: str, query: str = '', offset: int = 0, limit: int = 10) -> dict:
        if not isinstance(query, str) or len(query) > 80: raise ValueError('invalid search query')
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 500: raise ValueError('invalid offset')
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10: raise ValueError('invalid limit')
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        like = '%' + escaped + '%'
        cutoff = int(time.time()) - 30 * 86400
        where = "account=? AND saved_at>=? AND (keyword LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')"
        params = (account, cutoff, like, like, like, like)
        total = self.db.execute('SELECT count(*) FROM notes WHERE ' + where, params).fetchone()[0]
        rows = self.db.execute('SELECT note_id,keyword,summary,saved_at,title,body,status FROM notes WHERE ' + where +
                               ' ORDER BY saved_at DESC,rowid DESC LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
        keys = ('note_id', 'keyword', 'summary', 'saved_at', 'title', 'body', 'status')
        return {'total': total, 'offset': offset, 'limit': limit, 'items': [dict(zip(keys, row)) for row in rows]}

    def search(self, account: str, query: str, limit: int = 5) -> list[tuple[str, str, str]]:
        # Escape LIKE wildcards; content is data, not SQL.
        escaped = query[:80].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        return self.db.execute('''SELECT note_id, keyword, summary FROM notes WHERE account=? AND saved_at>=? AND status='complete'
            AND (summary LIKE ? ESCAPE '\\' OR keyword LIKE ? ESCAPE '\\')
            ORDER BY saved_at DESC LIMIT ?''', (account, int(time.time()) - 30 * 86400,
                                                '%' + escaped + '%', '%' + escaped + '%', limit)).fetchall()

    def close(self) -> None:
        self.db.close()
