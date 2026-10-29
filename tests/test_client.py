import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from session_store import SessionStore
from xhs_client import PlatformError, ReadOnlyClient
from xhs_policy import Policy

USER = 'b' * 24
OTHER = 'c' * 24
STATE = {'version': 1, 'shared_cookies': {'a1': 'a', 'web_session': 's'}}


class Signer:
    def sign_headers_get(self, **kwargs): return {}
    def sign_headers_post(self, **kwargs): return {}


class Response:
    def __init__(self, code, data): self.status_code, self.data = code, data
    def json(self): return self.data


class ClientTests(unittest.TestCase):
    def test_session_round_trip_in_new_store(self):
        with tempfile.TemporaryDirectory() as directory:
            SessionStore(Path(directory)).save(STATE)
            self.assertEqual(SessionStore(Path(directory)).load(), STATE)

    def test_nonwhitelist_causes_no_request(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(1)
            return Response(200, {'success': True, 'data': {'out_message_list': []}})
        client = ReadOnlyClient(STATE, Policy(frozenset({USER}), 1), signer=Signer(), request=request)
        with self.assertRaises(PermissionError): client.history(OTHER)
        self.assertEqual(calls, [])
        self.assertEqual(client.history(USER), [])
        self.assertEqual(len(calls), 1)

    def test_private_conversations_are_only_available_in_all_mode(self):
        account = 'a' * 24
        calls = []
        def request(*args, **kwargs):
            calls.append(kwargs['params']['page'])
            return Response(200, {'success': True, 'data': {'total': 1, 'chats': [
                {'user_id': account, 'chat_user_id': OTHER, 'last_msg_content': 'ignored'}]}})
        client = ReadOnlyClient(STATE, Policy(frozenset({USER}), 1), signer=Signer(), request=request)
        with self.assertRaises(PermissionError): client.private_conversations(account)
        self.assertEqual(calls, [])
        client = ReadOnlyClient(STATE, Policy(frozenset(), 1, allow_all=True), signer=Signer(), request=request)
        self.assertEqual(client.private_conversations(account), frozenset({OTHER}))
        self.assertEqual(calls, [0])

    def test_all_mode_list_paginates_and_fails_closed_on_invalid_scope(self):
        account = 'a' * 24
        users = [format(i, '024x') for i in range(21)]
        def request(*args, **kwargs):
            page = kwargs['params']['page']
            return Response(200, {'success': True, 'data': {'total': 21, 'chats': [
                {'user_id': account, 'chat_user_id': user} for user in users[page*20:(page+1)*20]]}})
        client = ReadOnlyClient(STATE, Policy(frozenset(), 1, allow_all=True), signer=Signer(), request=request)
        self.assertEqual(client.private_conversations(account), frozenset(users))
        def wrong_account(*args, **kwargs):
            return Response(200, {'success': True, 'data': {'total': 1, 'chats': [
                {'user_id': USER, 'chat_user_id': OTHER}]}})
        client = ReadOnlyClient(STATE, Policy(frozenset(), 1, allow_all=True), signer=Signer(), request=wrong_account)
        with self.assertRaises(PlatformError): client.private_conversations(account)

    def test_rejection_stops_client(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(1)
            return Response(406, {})
        client = ReadOnlyClient(STATE, Policy(frozenset({USER}), 1), signer=Signer(), request=request)
        with self.assertRaises(PlatformError): client.history(USER)
        with self.assertRaises(PlatformError): client.history(USER)
        self.assertEqual(len(calls), 1)

    def test_send_checks_whitelist_and_real_sender_and_never_retries(self):
        account = 'a' * 24
        calls = []
        def get(*args, **kwargs):
            calls.append('get')
            return Response(200, {'success': True, 'data': {'guest': False, 'user_id': account}})
        def post(*args, **kwargs):
            calls.append('post')
            raise TimeoutError()
        client = ReadOnlyClient(STATE, Policy(frozenset({USER}), 1), signer=Signer(), request=get, post=post)
        with self.assertRaises(PermissionError): client.send_text(OTHER, 'test', account_id=account)
        self.assertEqual(calls, [])
        with patch('im_wire.encrypt_payload', return_value=b'encrypted'):
            with self.assertRaises(PlatformError): client.send_text(USER, 'test', account_id=account)
            with self.assertRaises(PlatformError): client.send_text(USER, 'test', account_id=account)
        self.assertEqual(calls, ['get', 'post'])

    def test_history_paginates_inclusive_cursor_without_duplicate_and_rejects_unknown_users(self):
        messages = [{'id': str(i), 'store_id': i, 'created_at': i * 1000} for i in range(39, 0, -1)]
        calls = []
        def request(*args, **kwargs):
            cursor = kwargs['params']['last_id']
            calls.append(cursor)
            start = next((i for i, m in enumerate(messages) if m['store_id'] == cursor), 0) if cursor else 0
            return Response(200, {'success': True, 'data': {'out_message_list': messages[start:start + 20]}})
        client = ReadOnlyClient(STATE, Policy(frozenset({USER}), 1), signer=Signer(), request=request)
        with self.assertRaises(PermissionError): client.history_since(OTHER, 0)
        result = client.history_since(USER, 0)
        self.assertEqual(len(result), 39)
        self.assertEqual(len({m['id'] for m in result}), 39)
        self.assertEqual(len(calls), 3)

    def test_history_fails_closed_if_page_cap_is_exceeded(self):
        def request(*args, **kwargs):
            cursor = kwargs['params']['last_id'] or 100
            page = [{'id': str(i), 'store_id': i, 'created_at': i * 1000} for i in range(cursor, cursor - 20, -1)]
            return Response(200, {'success': True, 'data': {'out_message_list': page}})
        client = ReadOnlyClient(STATE, Policy(frozenset({USER}), 1), signer=Signer(), request=request)
        with self.assertRaises(PlatformError): client.history_since(USER, 0, max_pages=2)

    def test_public_interest_search_sends_no_account_cookies_and_resolves_id(self):
        opaque = 'A' * 44 + '=='
        calls = []
        def post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith('/result'):
                return Response(200, {'success': True, 'data': {'items': [{'modelType': 'note',
                    'note': {'id': opaque, 'title': '猫', 'desc': '猫的笔记'}}]}})
            return Response(200, {'success': True, 'data': {'resourceId': 'a' * 24}})
        client = ReadOnlyClient(STATE, Policy(frozenset(), 0), signer=Signer(), request=lambda *a, **k: None, post=post)
        notes = client.search_public_notes('猫', limit=5)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['note_card']['desc'], '猫的笔记')
        self.assertEqual(client.resolve_search_id(notes[0]['encrypted_id']), 'a' * 24)
        self.assertTrue(all('cookies' not in kw for _, kw in calls))
        self.assertTrue(all(url.startswith('https://bws.xiaohongshu.com/') for url, _ in calls))

    def test_public_search_stops_on_platform_rejection(self):
        calls = []
        def post(*args, **kwargs):
            calls.append(1)
            return Response(461, {})
        client = ReadOnlyClient(STATE, Policy(frozenset(), 0), signer=Signer(), request=lambda *a, **k: None, post=post)
        with self.assertRaises(PlatformError): client.search_public_notes('猫')
        with self.assertRaises(PlatformError): client.search_public_notes('猫')
        self.assertEqual(calls, [1])
