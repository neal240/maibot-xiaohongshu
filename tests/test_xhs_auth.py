import unittest
from types import SimpleNamespace
from xhs_auth import QRLogin, VerificationRequired


class Signer:
    def sign_headers_get(self, **kwargs): return {}


class AuthTests(unittest.TestCase):
    def test_status_challenge_is_sanitized_and_stops(self):
        calls = []
        def get(url, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status_code=471, headers={'Verifytype': '120', 'Verifyuuid': 'SECRET'})
        auth = QRLogin.__new__(QRLogin)
        auth.signer = Signer()
        auth.http = SimpleNamespace(cookies={}, get=get)
        auth.cookies = {'a1': 'fake'}
        auth.stopped = False
        with self.assertRaises(VerificationRequired) as context:
            auth._request('GET', '/api/sns/web/v1/login/qrcode/status', {'qr_id': 'fake'})
        self.assertEqual(context.exception.verification_type, '120')
        self.assertNotIn('SECRET', str(context.exception))
        self.assertTrue(auth.stopped)
        with self.assertRaises(Exception):
            auth._request('GET', '/api/sns/web/v1/login/qrcode/status', {'qr_id': 'fake'})
        self.assertEqual(len(calls), 1)
