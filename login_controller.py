"""A bounded, non-blocking QR login task for the plugin's WebUI."""
from __future__ import annotations

import asyncio
import base64
import io
import time
from pathlib import Path
from typing import Any, Callable

if __package__:
    from .session_store import SessionStore
    from .xhs_auth import QRLogin, VerificationRequired
else:
    from session_store import SessionStore
    from xhs_auth import QRLogin, VerificationRequired


def make_qr_data_url(url: str) -> str:
    import qrcode
    if not isinstance(url, str) or not 0 < len(url) <= 2048:
        raise ValueError('invalid QR data')
    output = io.BytesIO()
    qrcode.make(url).save(output, format='PNG')
    value = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
    if len(value) > 24000: raise ValueError('QR image exceeds limit')
    return value


class LoginController:
    """The QR and in-progress credentials exist only in the current task."""
    def __init__(self, data_dir: Path, *, prepare: Callable, on_success: Callable,
                 factory: Callable = QRLogin, render: Callable = make_qr_data_url,
                 poll_seconds: float = 5, timeout_seconds: float = 240):
        self._store = SessionStore(data_dir / 'auth')
        self._prepare = prepare
        self._on_success = on_success
        self._factory = factory
        self._render = render
        self._poll_seconds = poll_seconds
        self._timeout_seconds = timeout_seconds
        self._task: asyncio.Task | None = None
        self._state: dict[str, Any] = {'phase': 'idle', 'qr_image': None}

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        return {**self._state, 'saved_session': self._store.path.is_file()}

    def start(self) -> dict[str, Any]:
        if self.busy: return self.status()
        self._state = {'phase': 'starting', 'qr_image': None}
        self._task = asyncio.create_task(self._run(), name='xhs-qr-login')
        return self.status()

    def cancel(self) -> dict[str, Any]:
        if self.busy and self._state['phase'] != 'cancelling':
            self._state = {'phase': 'cancelling', 'qr_image': None}
            self._task.cancel()
        return self.status()

    async def shutdown(self) -> None:
        if self.busy:
            if self._state.get('phase') != 'cancelling':
                self._state = {'phase': 'cancelling', 'qr_image': None}
                self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass

    @staticmethod
    async def _call(function: Callable, *args, cleanup_on_cancel: Callable | None = None):
        # A cancelled to_thread call continues in its worker. Wait for it to
        # finish before closing the shared HTTP session or starting another QR.
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                result = await task
                if cleanup_on_cancel is not None:
                    await asyncio.to_thread(cleanup_on_cancel, result)
            except Exception: pass
            raise

    async def _run(self):
        auth = None
        try:
            await self._prepare()
            auth = await self._call(self._factory, cleanup_on_cancel=lambda value: value.close())
            qr_url = await self._call(auth.create)
            image = await self._call(self._render, qr_url)
            self._state = {'phase': 'waiting_scan', 'qr_image': image}
            deadline = time.monotonic() + self._timeout_seconds
            while time.monotonic() < deadline:
                await asyncio.sleep(self._poll_seconds)
                status = await self._call(auth.poll)
                if status == 0:
                    self._state = {'phase': 'waiting_scan', 'qr_image': image}
                elif status == 1:
                    self._state = {'phase': 'waiting_confirm', 'qr_image': image}
                elif status == 2:
                    self._state = {'phase': 'verifying', 'qr_image': None}
                    session = await self._call(auth.finish)
                    await self._call(self._store.save, session)
                    self._state = {'phase': 'logged_in', 'qr_image': None}
                    try: await self._on_success()
                    except Exception: self._state['gateway_restart_failed'] = True
                    return
                elif status == 3:
                    self._state = {'phase': 'expired', 'qr_image': None}
                    return
                else:
                    raise ValueError('unexpected QR status')
            self._state = {'phase': 'expired', 'qr_image': None}
        except asyncio.CancelledError:
            self._state = {'phase': 'cancelled', 'qr_image': None}
            raise
        except VerificationRequired as exc:
            self._state = {'phase': 'verification_required', 'qr_image': None,
                           'http_status': exc.status,
                           'verification_type': exc.verification_type}
        except Exception:
            self._state = {'phase': 'error', 'qr_image': None}
        finally:
            if auth is not None:
                await self._call(auth.close)
