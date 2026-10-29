import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path

from login_controller import LoginController
from session_store import SessionStore
from xhs_auth import VerificationRequired


class FakeAuth:
    def __init__(self, fail=False):
        self.polls = 0
        self.fail = fail
        self.closed = False

    def create(self): return 'xhsdiscover://synthetic'
    def poll(self):
        self.polls += 1
        return 2
    def finish(self):
        if self.fail: raise VerificationRequired(471, '120')
        return {'version': 1, 'shared_cookies': {'a1': 'new', 'web_session': 'secret'}}
    def close(self): self.closed = True


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_stores_state_without_returning_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            actions = []
            async def prepare(): actions.append('prepare')
            async def success(): actions.append('success')
            auth = FakeAuth()
            manager = LoginController(Path(d), prepare=prepare, on_success=success,
                                      factory=lambda: auth, render=lambda _: 'data:image/png;base64,AA==',
                                      poll_seconds=.01, timeout_seconds=1)
            self.assertEqual(manager.start()['phase'], 'starting')
            self.assertEqual(manager.start()['phase'], 'starting')
            await manager._task
            status = manager.status()
            self.assertEqual(status['phase'], 'logged_in')
            self.assertTrue(status['saved_session'])
            self.assertNotIn('secret', str(status))
            self.assertTrue(auth.closed)
            self.assertEqual(actions, ['prepare', 'success'])

    async def test_471_stops_and_preserves_existing_session(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            old = {'version': 1, 'shared_cookies': {'a1': 'old', 'web_session': 'old-secret'}}
            store = SessionStore(directory / 'auth')
            store.save(old)
            async def noop(): pass
            auth = FakeAuth(fail=True)
            manager = LoginController(directory, prepare=noop, on_success=noop,
                                      factory=lambda: auth, render=lambda _: 'data:image/png;base64,AA==',
                                      poll_seconds=.01, timeout_seconds=1)
            manager.start()
            await manager._task
            status = manager.status()
            self.assertEqual(status['phase'], 'verification_required')
            self.assertEqual(status['http_status'], 471)
            self.assertIsNone(status['qr_image'])
            self.assertEqual(store.load(), old)
            self.assertEqual(auth.polls, 1)
            self.assertTrue(auth.closed)

    async def test_cancel_clears_qr_and_closes_client(self):
        with tempfile.TemporaryDirectory() as d:
            async def noop(): pass
            auth = FakeAuth()
            manager = LoginController(Path(d), prepare=noop, on_success=noop, factory=lambda: auth,
                                      render=lambda _: 'data:image/png;base64,AA==', poll_seconds=5)
            manager.start()
            for _ in range(100):
                if manager.status()['phase'] == 'waiting_scan': break
                await asyncio.sleep(.005)
            self.assertEqual(manager.status()['phase'], 'waiting_scan')
            manager.cancel()
            await manager.shutdown()
            self.assertEqual(manager.status()['phase'], 'cancelled')
            self.assertIsNone(manager.status()['qr_image'])
            self.assertTrue(auth.closed)

    async def test_cancel_waits_for_inflight_request_before_close(self):
        class SlowAuth(FakeAuth):
            def __init__(self):
                super().__init__()
                self.started = threading.Event()
                self.finished = False
                self.closed_early = False
            def poll(self):
                self.started.set()
                time.sleep(.1)
                self.finished = True
                return 0
            def close(self):
                self.closed_early = not self.finished
                super().close()
        with tempfile.TemporaryDirectory() as d:
            async def noop(): pass
            auth = SlowAuth()
            manager = LoginController(Path(d), prepare=noop, on_success=noop, factory=lambda: auth,
                                      render=lambda _: 'data:image/png;base64,AA==', poll_seconds=.001)
            manager.start()
            for _ in range(100):
                if auth.started.is_set(): break
                await asyncio.sleep(.005)
            self.assertTrue(auth.started.is_set())
            manager.cancel()
            await manager.shutdown()
            self.assertTrue(auth.closed)
            self.assertFalse(auth.closed_early)

    async def test_cancel_during_client_construction_closes_new_client(self):
        with tempfile.TemporaryDirectory() as d:
            async def noop(): pass
            auth = FakeAuth()
            started = threading.Event()
            def factory():
                started.set()
                time.sleep(.08)
                return auth
            manager = LoginController(Path(d), prepare=noop, on_success=noop, factory=factory,
                                      render=lambda _: 'data:image/png;base64,AA==')
            manager.start()
            for _ in range(100):
                if started.is_set(): break
                await asyncio.sleep(.005)
            self.assertTrue(started.is_set())
            manager.cancel()
            await manager.shutdown()
            self.assertTrue(auth.closed)
