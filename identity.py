"""Explicit, account-scoped links; never store messages or profile contents."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

XHS_ID = re.compile(r'^[0-9a-f]{24}$')
QQ_ID = re.compile(r'^[0-9]{5,20}$')


def valid_xhs(value: object) -> bool:
    return isinstance(value, str) and bool(XHS_ID.fullmatch(value))


def valid_qq(value: object) -> bool:
    return isinstance(value, str) and bool(QQ_ID.fullmatch(value))


class IdentityLinks:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        if os.name == 'posix': os.chmod(path, 0o600)
        self.db.execute('''CREATE TABLE IF NOT EXISTS links (
            account TEXT NOT NULL, xhs_user TEXT NOT NULL, qq_user TEXT NOT NULL,
            PRIMARY KEY(account, xhs_user))''')
        self.db.commit()

    def list(self, account: str) -> list[dict[str, str]]:
        if not valid_xhs(account): raise ValueError('invalid account')
        rows = self.db.execute('SELECT xhs_user,qq_user FROM links WHERE account=? ORDER BY xhs_user',
                               (account,)).fetchall()
        return [{'xhs_user': xhs, 'qq_user': qq} for xhs, qq in rows]

    def get(self, account: str, xhs_user: str) -> str | None:
        if not valid_xhs(account) or not valid_xhs(xhs_user): raise ValueError('invalid account or user')
        row = self.db.execute('SELECT qq_user FROM links WHERE account=? AND xhs_user=?',
                              (account, xhs_user)).fetchone()
        return row[0] if row else None

    def set(self, account: str, xhs_user: str, qq_user: str) -> None:
        if not valid_xhs(account) or not valid_xhs(xhs_user) or not valid_qq(qq_user):
            raise ValueError('invalid identity')
        with self.db:
            count = self.db.execute('SELECT count(*) FROM links WHERE account=?', (account,)).fetchone()[0]
            if count >= 500 and self.get(account, xhs_user) is None: raise ValueError('too many links')
            self.db.execute('''INSERT INTO links(account,xhs_user,qq_user) VALUES(?,?,?)
                ON CONFLICT(account,xhs_user) DO UPDATE SET qq_user=excluded.qq_user''',
                (account, xhs_user, qq_user))

    def delete(self, account: str, xhs_user: str) -> None:
        if not valid_xhs(account) or not valid_xhs(xhs_user): raise ValueError('invalid identity')
        with self.db:
            self.db.execute('DELETE FROM links WHERE account=? AND xhs_user=?', (account, xhs_user))

    def close(self) -> None:
        self.db.close()
