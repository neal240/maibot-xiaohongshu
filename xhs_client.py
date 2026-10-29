"""Experimental client with explicit private-message scope checks."""
from __future__ import annotations

from typing import Any
import json
import re
import secrets
import time
if __package__:
    from .xhs_policy import Policy
else:
    from xhs_policy import Policy

HOST = 'https://edith.xiaohongshu.com'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')


class PlatformError(RuntimeError):
    pass


class ReadOnlyClient:
    def __init__(self, state: dict, policy: Policy, *, signer=None, request=None, post=None):
        if state.get('version') != 1 or not isinstance(state.get('shared_cookies'), dict):
            raise ValueError('invalid session')
        self._cookies = dict(state['shared_cookies'])
        self._cookies.update((state.get('host_cookies') or {}).get('edith.xiaohongshu.com', {}))
        if not self._cookies.get('a1') or not self._cookies.get('web_session'):
            raise ValueError('session has no login credentials')
        if signer is None:
            from xhshow import Xhshow
            signer = Xhshow()
        if request is None:
            from curl_cffi import requests
            request = requests.get
        self._signer = signer
        self._request = request
        self._post_request = post
        self._policy = policy
        self._stopped = False

    def _get(self, path: str, params: dict | None = None) -> dict:
        if self._stopped: raise PlatformError('client is stopped')
        headers = self._signer.sign_headers_get(uri=path, cookies=self._cookies, params=params)
        headers.update({'User-Agent': UA, 'Referer': 'https://www.xiaohongshu.com/',
                        'Origin': 'https://www.xiaohongshu.com'})
        response = self._request(HOST + path, params=params, headers=headers,
                                 cookies=self._cookies, timeout=12, impersonate='chrome',
                                 allow_redirects=False)
        if response.status_code != 200:
            self._stopped = True
            raise PlatformError(f'platform request rejected (HTTP {response.status_code})')
        try: data = response.json()
        except ValueError:
            self._stopped = True
            raise PlatformError('platform returned invalid JSON') from None
        if not isinstance(data, dict) or data.get('success') is not True:
            self._stopped = True
            raise PlatformError('platform request unsuccessful')
        return data

    def _post(self, path: str, payload: dict) -> dict:
        if self._stopped: raise PlatformError('client is stopped')
        if self._post_request is None:
            from curl_cffi import requests
            self._post_request = requests.post
        headers = self._signer.sign_headers_post(uri=path, cookies=self._cookies, payload=payload,
                                                 x_rap=path == '/api/sns/web/v1/search/notes')
        headers.update({'User-Agent': UA, 'Referer': 'https://www.xiaohongshu.com/',
                        'Origin': 'https://www.xiaohongshu.com', 'Content-Type': 'application/json'})
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        try:
            response = self._post_request(HOST + path, data=body, headers=headers,
                                          cookies=self._cookies, timeout=12, impersonate='chrome',
                                          allow_redirects=False)
            if response.status_code != 200:
                raise PlatformError(f'platform request rejected (HTTP {response.status_code})')
            data = response.json()
            if not isinstance(data, dict) or data.get('success') is not True:
                raise PlatformError('platform request unsuccessful')
            return data
        except Exception as exc:
            self._stopped = True
            if isinstance(exc, PlatformError): raise
            raise PlatformError('platform request failed') from None

    def search_notes(self, keyword: str, *, limit: int = 10) -> list[dict]:
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 80:
            raise ValueError('invalid interest keyword')
        if not 1 <= limit <= 20: raise ValueError('invalid result limit')
        result = self._post('/api/sns/web/v1/search/notes', {
            'keyword': keyword.strip(), 'page': 1, 'page_size': limit,
            'search_id': self._signer.get_search_id(), 'sort': 'general', 'note_type': 0,
        })
        items = (result.get('data') or {}).get('items') or []
        if not isinstance(items, list): raise PlatformError('invalid search response')
        return [item for item in items[:limit] if isinstance(item, dict)]

    def home_feed(self, *, limit: int = 5) -> list[dict]:
        if not 1 <= limit <= 10: raise ValueError('invalid result limit')
        result = self._post('/api/sns/web/v1/homefeed', {
            'cursor_score': '', 'num': limit, 'refresh_type': 1, 'note_index': 0,
            'unread_begin_note_id': '', 'unread_end_note_id': '', 'unread_note_count': 0,
            'category': 'homefeed_recommend', 'search_key': '', 'need_num': limit,
            'image_scenes': ['FD_PRV_WEBP', 'FD_WM_WEBP'],
        })
        items = (result.get('data') or {}).get('items') or []
        if not isinstance(items, list): raise PlatformError('invalid home feed response')
        return [item for item in items[:limit] if isinstance(item, dict)]

    def _public_search_post(self, path: str, payload: dict) -> dict:
        if self._stopped: raise PlatformError('client is stopped')
        if path not in {'/api/growth/browser/search/result', '/api/growth/resource/decrypt'}:
            raise ValueError('unsupported public search endpoint')
        if self._post_request is None:
            from curl_cffi import requests
            self._post_request = requests.post
        try:
            response = self._post_request('https://bws.xiaohongshu.com' + path,
                data=json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
                headers={'User-Agent': UA, 'Accept': 'application/json, text/plain, */*',
                         'Content-Type': 'application/json;charset=UTF-8', 'uuid': '000000'},
                timeout=12, impersonate='chrome', allow_redirects=False)
            if response.status_code != 200:
                raise PlatformError(f'public search rejected (HTTP {response.status_code})')
            result = response.json()
            if not isinstance(result, dict) or result.get('success') is not True:
                raise PlatformError('public search request unsuccessful')
            data = result.get('data')
            if not isinstance(data, dict): raise PlatformError('invalid public search response')
            return data
        except Exception as exc:
            self._stopped = True
            if isinstance(exc, PlatformError): raise
            raise PlatformError('public search request failed') from None

    def search_public_notes(self, keyword: str, *, limit: int = 5) -> list[dict]:
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 80:
            raise ValueError('invalid interest keyword')
        if not 1 <= limit <= 10: raise ValueError('invalid result limit')
        request_id = format(int(time.time() * 1000), 'x') + secrets.token_hex(3)
        data = self._public_search_post('/api/growth/browser/search/result', {
            'keyword': keyword.strip(), 'page': 1, 'pageSize': limit, 'scene': 'ecology',
            'source': 'ecology', 'searchId': request_id, 'requestId': request_id, 'pagePos': 0,
            'sessionId': secrets.token_hex(1), 'xhsBrowserChannel': 'default',
        })
        items = data.get('items') or []
        if not isinstance(items, list): raise PlatformError('invalid public search items')
        result = []
        for item in items[:limit]:
            if not isinstance(item, dict) or not isinstance(item.get('note'), dict): continue
            note = item['note']
            opaque = note.get('id')
            if not isinstance(opaque, str) or not re.fullmatch(r'[A-Za-z0-9_=-]{46}', opaque): continue
            result.append({'encrypted_id': opaque, 'note_card': {
                'display_title': note.get('title'), 'title': note.get('title'), 'desc': note.get('desc'),
                'image_list': note.get('imagesList') or []}})
        return result

    def resolve_search_id(self, encrypted_id: str) -> str:
        if not isinstance(encrypted_id, str) or not re.fullmatch(r'[A-Za-z0-9_=-]{46}', encrypted_id):
            raise ValueError('invalid encrypted search ID')
        result = self._public_search_post('/api/growth/resource/decrypt',
                                          {'resourceId': encrypted_id, 'resourceType': 1})
        note_id = result.get('resourceId')
        if not isinstance(note_id, str) or not re.fullmatch(r'[0-9a-f]{24}', note_id):
            raise PlatformError('invalid decoded note ID')
        return note_id

    def note_detail(self, note_id: str, token: str, *, source: str = 'app_share') -> dict:
        if not isinstance(note_id, str) or not re.fullmatch(r'[0-9a-f]{24}', note_id):
            raise ValueError('invalid note ID')
        if not isinstance(token, str) or len(token) > 2048:
            raise ValueError('invalid note token')
        if source not in {'app_share', 'pc_search', 'pc_feed'}: raise ValueError('invalid note source')
        result = self._post('/api/sns/web/v1/feed', {
            'source_note_id': note_id, 'image_formats': ['jpg', 'webp'],
            'extra': {'need_body_topic': 1}, 'xsec_source': source, 'xsec_token': token,
        })
        items = (result.get('data') or {}).get('items') or []
        if not items or not isinstance(items[0], dict) or not isinstance(items[0].get('note_card'), dict):
            raise PlatformError('note unavailable')
        return items[0]['note_card']

    def authenticated(self) -> bool:
        return bool(self.identity())

    def identity(self) -> str:
        data = self._get('/api/sns/web/v2/user/me')
        user = data.get('data') or {}
        user_id = user.get('user_id')
        if user.get('guest') is not False or not isinstance(user_id, str) or not re.fullmatch(r'[0-9a-f]{24}', user_id):
            raise PlatformError('session is not authenticated')
        return user_id

    def private_conversations(self, account_id: str, *, max_pages: int = 10) -> frozenset[str]:
        if not self._policy.allow_all: raise PermissionError('all-users mode is disabled')
        if not re.fullmatch(r'[0-9a-f]{24}', account_id) or not 1 <= max_pages <= 10:
            raise ValueError('invalid account or page limit')
        users = set()
        for page in range(max_pages):
            response = self._get('/api/im/web/v3/chats',
                                 {'limit': 20, 'complete': 'true', 'page': page, 'source': 'pc'})
            data = response.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('chats'), list):
                raise PlatformError('invalid private conversation list')
            chats = data['chats']
            total = data.get('total')
            if not isinstance(total, int) or isinstance(total, bool) or total < 0 or total > 20 * max_pages:
                raise PlatformError('private conversation list exceeds bounded limit or has no total')
            for item in chats:
                if not isinstance(item, dict) or item.get('user_id') != account_id:
                    raise PlatformError('invalid private conversation account')
                user = item.get('chat_user_id')
                if not isinstance(user, str) or not re.fullmatch(r'[0-9a-f]{24}', user) or user == account_id:
                    raise PlatformError('invalid private conversation user')
                users.add(user)
            if len(users) > total: raise PlatformError('inconsistent private conversation count')
            if len(users) == total: return frozenset(users)
            if len(chats) < 20: raise PlatformError('incomplete private conversation list')
        raise PlatformError('private conversation list exceeds bounded page limit')

    def history(self, user_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        if not self._policy.permits(user_id, user_id, group=False):
            raise PermissionError('user is not on the whitelist')
        if not 1 <= limit <= 20: raise ValueError('limit outside allowed range')
        data = self._get('/api/im/web/messages/history',
                         {'chat_user_id': user_id, 'last_id': 0, 'start_id': 0, 'limit': limit})
        messages = (data.get('data') or {}).get('out_message_list') or []
        if not isinstance(messages, list): raise PlatformError('invalid history response')
        return messages

    def history_since(self, user_id: str, not_before_ms: int, *, max_pages: int = 10) -> list[dict[str, Any]]:
        if not self._policy.permits(user_id, user_id, group=False):
            raise PermissionError('user is not on the whitelist')
        if not 1 <= max_pages <= 10: raise ValueError('invalid page limit')
        cursor, collected, ids = 0, [], set()
        for _ in range(max_pages):
            result = self._get('/api/im/web/messages/history',
                               {'chat_user_id': user_id, 'last_id': cursor, 'start_id': 0, 'limit': 20})
            page = (result.get('data') or {}).get('out_message_list') or []
            if not isinstance(page, list): raise PlatformError('invalid history response')
            for item in page:
                if not isinstance(item, dict): raise PlatformError('invalid history message')
                message_id = item.get('id')
                if not isinstance(message_id, str) or not message_id: raise PlatformError('history message ID missing')
                if message_id not in ids:
                    ids.add(message_id)
                    collected.append(item)
            if not page or len(page) < 20: return collected
            times = [item.get('created_at') for item in page]
            if any(not isinstance(v, int) or isinstance(v, bool) for v in times):
                raise PlatformError('history timestamp missing')
            oldest_index = min(range(len(page)), key=lambda i: times[i])
            if times[oldest_index] < not_before_ms: return collected
            next_cursor = page[oldest_index].get('store_id')
            if not isinstance(next_cursor, int) or isinstance(next_cursor, bool) or next_cursor <= 0 or next_cursor == cursor:
                raise PlatformError('history cursor unavailable')
            cursor = next_cursor
        raise PlatformError('history backlog exceeds bounded page limit; no messages delivered')

    def send_text(self, user_id: str, content: str, *, account_id: str) -> bool:
        if not self._policy.permits(user_id, user_id, group=False):
            raise PermissionError('user is not on the whitelist')
        if not isinstance(account_id, str) or not re.fullmatch(r'[0-9a-f]{24}', account_id):
            raise ValueError('invalid sender ID')
        if not isinstance(content, str) or not content.strip() or len(content.encode('utf-8')) > 2000:
            raise ValueError('invalid text')
        if self._stopped: raise PlatformError('client is stopped')
        if self.identity() != account_id:
            self._stopped = True
            raise PlatformError('sender does not match authenticated account')
        if self._post_request is None:
            from curl_cffi import requests
            self._post_request = requests.post
        if __package__:
            from .im_wire import encode_text, encrypt_payload
        else:
            from im_wire import encode_text, encrypt_payload
        path = '/api/im/web/short_link/send_message'
        payload = {'message': encrypt_payload(encode_text(account_id, user_id, content)).decode('latin-1')}
        headers = self._signer.sign_headers_post(uri=path, cookies=self._cookies, payload=payload)
        headers.update({'User-Agent': UA, 'Referer': 'https://www.xiaohongshu.com/',
                        'Origin': 'https://www.xiaohongshu.com', 'Content-Type': 'application/json'})
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        try:
            response = self._post_request(HOST + path, data=body, headers=headers,
                                          cookies=self._cookies, timeout=12, impersonate='chrome',
                                          allow_redirects=False)
            if response.status_code != 200:
                raise PlatformError(f'send rejected or uncertain (HTTP {response.status_code})')
            data = response.json()
            if not isinstance(data, dict) or data.get('success') is not True:
                raise PlatformError('send not confirmed')
            return True
        except PlatformError:
            self._stopped = True
            raise
        except Exception:
            # A timeout or ambiguous response may already have sent the message.
            self._stopped = True
            raise PlatformError('send failed or result uncertain; no automatic retry') from None
