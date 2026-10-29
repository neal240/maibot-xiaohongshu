"""Fail-closed policy for a single account's one-to-one messages.

This module contains no network client or MaiBot dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import secrets
import sqlite3
from pathlib import Path
from typing import Callable

_ID = re.compile(r"^[0-9a-f]{24}$")


@dataclass(frozen=True)
class Policy:
    allowed_users: frozenset[str]
    reply_probability: float = 0.0
    allow_all: bool = False

    def __post_init__(self) -> None:
        if any(not _ID.fullmatch(user) for user in self.allowed_users):
            raise ValueError('white list must contain stable 24-character user IDs')
        if not isinstance(self.allow_all, bool): raise ValueError('invalid DM mode')
        if not math.isfinite(self.reply_probability) or not 0 <= self.reply_probability <= 1:
            raise ValueError('reply probability must be between 0 and 1')

    def permits(self, sender: str, conversation_user: str, *, group: bool) -> bool:
        return (group is False and isinstance(sender, str) and bool(_ID.fullmatch(sender))
                and sender == conversation_user and (self.allow_all or sender in self.allowed_users))


class Decisions:
    """Persist one decision per account/message; stores no message content."""
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute('''CREATE TABLE IF NOT EXISTS decisions (
            account TEXT NOT NULL, message_id TEXT NOT NULL,
            sender TEXT NOT NULL, selected INTEGER NOT NULL,
            claimed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (account, message_id)
        )''')
        self.conn.execute('''CREATE TABLE IF NOT EXISTS baselines (
            account TEXT NOT NULL, user_id TEXT NOT NULL, started_ms INTEGER NOT NULL,
            PRIMARY KEY (account, user_id)
        )''')
        self.conn.execute('''CREATE TABLE IF NOT EXISTS access_modes (
            account TEXT PRIMARY KEY, mode TEXT NOT NULL, started_ms INTEGER NOT NULL
        )''')
        if 'inflight' not in {row[1] for row in self.conn.execute('PRAGMA table_info(decisions)')}:
            self.conn.execute('ALTER TABLE decisions ADD COLUMN inflight INTEGER NOT NULL DEFAULT 0')
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def sync_mode(self, account: str, mode: str, now_ms: int) -> int:
        if not _ID.fullmatch(account) or mode not in {'whitelist', 'all'}:
            raise ValueError('invalid account or mode')
        with self.conn:
            row = self.conn.execute('SELECT mode,started_ms FROM access_modes WHERE account=?', (account,)).fetchone()
            if row and row[0] == mode: return row[1]
            if row or mode == 'all':
                self.conn.execute('DELETE FROM baselines WHERE account=?', (account,))
            self.conn.execute('INSERT OR REPLACE INTO access_modes VALUES(?,?,?)', (account, mode, now_ms))
            return now_ms

    def disable_mode(self, account: str) -> None:
        if not _ID.fullmatch(account): raise ValueError('invalid account')
        with self.conn:
            self.conn.execute('DELETE FROM access_modes WHERE account=?', (account,))
            self.conn.execute('DELETE FROM baselines WHERE account=?', (account,))

    def ensure_baselines(self, account: str, users: frozenset[str], started_ms: int) -> dict[str, int]:
        if not _ID.fullmatch(account) or any(not _ID.fullmatch(user) for user in users):
            raise ValueError('invalid account or conversation')
        with self.conn:
            for user in users:
                self.conn.execute('INSERT OR IGNORE INTO baselines VALUES(?,?,?)', (account, user, started_ms))
            all_baselines = dict(self.conn.execute('SELECT user_id,started_ms FROM baselines WHERE account=?', (account,)))
            return {user: all_baselines[user] for user in users}

    def sync_baselines(self, account: str, users: frozenset[str], now_ms: int) -> dict[str, int]:
        if not _ID.fullmatch(account): raise ValueError('invalid account')
        if any(not _ID.fullmatch(user) for user in users): raise ValueError('invalid whitelist')
        with self.conn:
            existing = self.conn.execute('SELECT user_id FROM baselines WHERE account=?', (account,)).fetchall()
            for (user,) in existing:
                if user not in users:
                    self.conn.execute('DELETE FROM baselines WHERE account=? AND user_id=?', (account, user))
                    self.conn.execute('DELETE FROM decisions WHERE account=? AND sender=?', (account, user))
            for user in users:
                self.conn.execute('INSERT OR IGNORE INTO baselines VALUES(?,?,?)', (account, user, now_ms))
            return dict(self.conn.execute('SELECT user_id,started_ms FROM baselines WHERE account=?', (account,)))

    def advance_baseline(self, account: str, user: str, timestamp: int) -> None:
        with self.conn:
            self.conn.execute('UPDATE baselines SET started_ms=max(started_ms, ?) WHERE account=? AND user_id=?',
                              (timestamp, account, user))

    def claim(self, account: str, message_id: str, sender: str,
              conversation_user: str, group: bool, policy: Policy,
              draw: Callable[[], float] | None = None) -> bool:
        # Identity is checked before storage, sampling or message-body access.
        if not _ID.fullmatch(account) or not message_id or len(message_id) > 256:
            return False
        if not policy.permits(sender, conversation_user, group=group):
            return False
        with self.conn:
            row = self.conn.execute(
                'SELECT sender, selected, claimed, inflight FROM decisions WHERE account=? AND message_id=?',
                (account, message_id),
            ).fetchone()
            if row is None:
                value = draw() if draw else secrets.randbelow(1_000_000) / 1_000_000
                if not 0 <= value < 1:
                    raise ValueError('random sample must be in [0, 1)')
                selected = value < policy.reply_probability
                self.conn.execute(
                    'INSERT INTO decisions(account,message_id,sender,selected,claimed) VALUES(?,?,?,?,?)',
                    (account, message_id, sender, int(selected), 0),
                )
                return True
            # Pending entries may be retried with the same Host deduplication key.
            if row[0] != sender or row[2] or row[3]:
                return False
            return True

    def mark_inflight(self, account: str, message_id: str) -> None:
        with self.conn:
            self.conn.execute('UPDATE decisions SET inflight=1 WHERE account=? AND message_id=? AND claimed=0',
                              (account, message_id))

    def uncertain_count(self, account: str) -> int:
        return self.conn.execute('SELECT count(*) FROM decisions WHERE account=? AND inflight=1 AND claimed=0',
                                 (account,)).fetchone()[0]

    def acknowledge(self, account: str, message_id: str) -> None:
        with self.conn:
            self.conn.execute('UPDATE decisions SET claimed=1,inflight=0 WHERE account=? AND message_id=?',
                              (account, message_id))

    def reply_allowed(self, account: str, sender: str) -> bool:
        # The newest ingested DM determines the gate for this conversation.
        row = self.conn.execute('''SELECT selected FROM decisions WHERE account=? AND sender=?
            ORDER BY rowid DESC LIMIT 1''', (account, sender)).fetchone()
        return bool(row and row[0])
