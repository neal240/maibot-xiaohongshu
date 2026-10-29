"""Local session persistence. Never use for logs, repository files or WebUI output."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


class SessionStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / 'session.json'

    def save(self, state: dict) -> None:
        if state.get('version') != 1 or not isinstance(state.get('shared_cookies'), dict):
            raise ValueError('invalid session')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == 'posix':
            os.chmod(self.directory, 0o700)
        fd, name = tempfile.mkstemp(prefix='.session-', dir=self.directory)
        try:
            if os.name == 'posix': os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, separators=(',', ':'))
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        except BaseException:
            try: os.unlink(name)
            except FileNotFoundError: pass
            raise

    def load(self) -> dict:
        state = json.loads(self.path.read_text(encoding='utf-8'))
        if state.get('version') != 1 or not isinstance(state.get('shared_cookies'), dict):
            raise ValueError('invalid session')
        return state
