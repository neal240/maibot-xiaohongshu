"""Experimental independent QR flow. Uses MIT xhshow and public crypto APIs."""
from __future__ import annotations

import base64
import re

if __package__:
    from .xhs_client import HOST, UA, PlatformError, ReadOnlyClient
    from .xhs_policy import Policy
else:
    from xhs_client import HOST, UA, PlatformError, ReadOnlyClient
    from xhs_policy import Policy


class VerificationRequired(PlatformError):
    """Platform requested human verification; identifiers are not exposed."""

    def __init__(self, status: int, verification_type: str = ''):
        self.status = status
        self.verification_type = verification_type
        super().__init__('平台要求人工验证')


class QRLogin:
    def __init__(self):
        from curl_cffi import requests
        from xhshow import Xhshow
        self.signer = Xhshow()
        self.http = requests.Session(impersonate='chrome')
        a1 = self.signer.generate_a1()
        self.cookies = {'a1': a1, 'webId': self.signer.generate_web_id(a1),
                        'xsecappid': 'xhs-pc-web'}
        self.http.cookies.update(self.cookies)
        self.qr_id = self.qr_code = ''
        self.stopped = False
        self.last_stage = ''
        self.last_http = None
        self.last_code = None
        self.last_verify_type = ''

    def close(self):
        self.http.close()

    def _request(self, method, path, payload):
        if self.stopped: raise PlatformError('login is stopped')
        self.last_stage = path
        self.last_http = self.last_code = None
        current = dict(self.cookies)
        current.update(dict(self.http.cookies))
        if method == 'POST':
            headers = self.signer.sign_headers_post(uri=path, cookies=current, payload=payload)
        else:
            headers = self.signer.sign_headers_get(uri=path, cookies=current, params=payload)
        headers.update({'User-Agent': UA, 'Referer': 'https://www.xiaohongshu.com/',
                        'Origin': 'https://www.xiaohongshu.com', 'Content-Type': 'application/json'})
        if method == 'POST':
            response = self.http.post(HOST + path, headers=headers, json=payload,
                                      timeout=12, allow_redirects=False)
        else:
            response = self.http.get(HOST + path, headers=headers, params=payload,
                                     timeout=12, allow_redirects=False)
        self.last_http = response.status_code
        if response.status_code in (461, 471):
            self.stopped = True
            raw_type = response.headers.get('Verifytype', '')
            self.last_verify_type = raw_type if re.fullmatch(r'\d{1,4}', raw_type) else ''
            raise VerificationRequired(response.status_code, self.last_verify_type)
        if response.status_code != 200:
            self.stopped = True
            raise PlatformError('QR request rejected')
        try: result = response.json()
        except ValueError:
            self.stopped = True
            raise PlatformError('invalid QR response') from None
        if isinstance(result, dict): self.last_code = result.get('code')
        if not isinstance(result, dict) or result.get('success') is not True:
            self.stopped = True
            raise PlatformError('QR request unsuccessful')
        return result.get('data') or {}

    def create(self):
        result = self._request('POST', '/api/sns/web/v1/login/qrcode/create', {})
        self.qr_id, self.qr_code = result['qr_id'], result['code']
        return result['url']

    def poll(self):
        if not self.qr_id or not self.qr_code: raise ValueError('QR not created')
        result = self._request('POST', '/api/qrcode/userinfo',
                               {'qrId': self.qr_id, 'code': self.qr_code})
        status = result.get('codeStatus')
        if status not in (0, 1, 2, 3): raise PlatformError('unknown QR status')
        return status

    def finish(self):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        key = X25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        params = {'qr_id': self.qr_id, 'code': self.qr_code,
                  'client_public_key_base64': base64.b64encode(key).decode('ascii')}
        result = self._request('GET', '/api/sns/web/v1/login/qrcode/status', params)
        if result.get('code_status') != 2:
            raise PlatformError('QR was not confirmed')
        token = (result.get('login_info') or {}).get('session')
        if not token: raise PlatformError('QR response has no session')
        cookies = dict(self.cookies)
        cookies.update(dict(self.http.cookies))
        cookies['web_session'] = token
        state = {'version': 1, 'shared_cookies': cookies, 'host_cookies': {}}
        self.last_stage = 'verify_account'
        if not ReadOnlyClient(state, Policy(frozenset(), 0)).authenticated():
            raise PlatformError('account verification failed')
        return state
