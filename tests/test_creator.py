import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from unittest.mock import patch

from creator import CreatorClient
from xhs_client import PlatformError

ACCOUNT = 'a' * 24
STATE = {'shared_cookies': {'a1': 'a', 'web_session': 's'}}


class Signer:
    def sign_headers_get(self, **kwargs): return {}
    def sign_headers_post(self, **kwargs): return {}
    def get_search_request_id(self): return 'synthetic'


class Response:
    status_code = 200
    def __init__(self, data): self.data = data
    def json(self): return self.data


class HTTP:
    def __init__(self, account=ACCOUNT, fail_submit=False):
        self.account, self.fail_submit, self.calls = account, fail_submit, []
    def get(self, url, **kwargs):
        self.calls.append('get')
        if url.endswith('/user/info'): return Response({'success': True, 'data': {'userId': self.account}})
        return Response({'success': True, 'data': {'uploadTempPermits': [{'fileIds': ['spectrum/abc'], 'token': 'x'}]}})
    def put(self, url, **kwargs): self.calls.append('put'); return Response({})
    def post(self, url, **kwargs):
        self.calls.append('post')
        self.payload = json.loads(kwargs['data'])
        if url.endswith('/text2imgv3'):
            return Response({'success': True, 'data': {'text2_img_type_results': [
                {'img_url': 'https://ci.xhscdn.com/card.jpg'}]}})
        if self.fail_submit: raise TimeoutError()
        return Response({'success': True})


class CreatorTests(unittest.TestCase):
    def test_private_and_explicit_public_privacy_fields(self):
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / 'image.png'
            Image.new('RGB', (4, 4), 'white').save(image)
            for private in (True, False):
                http = HTTP()
                client = CreatorClient(STATE, ACCOUNT, signer=Signer(), http=http)
                self.assertTrue(client.publish('标题', '正文', [image], private=private))
                self.assertEqual(http.payload['common']['privacy_info']['type'], int(private))
                self.assertEqual(http.calls, ['get', 'get', 'put', 'post'])

    def test_wrong_creator_account_never_uploads(self):
        http = HTTP(account='b' * 24)
        client = CreatorClient(STATE, ACCOUNT, signer=Signer(), http=http)
        with self.assertRaises(PlatformError): client.publish('标题', '正文', [Path('unused')])
        self.assertEqual(http.calls, ['get'])

    def test_timeout_does_not_retry_submission(self):
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / 'image.png'
            Image.new('RGB', (4, 4), 'white').save(image)
            http = HTTP(fail_submit=True)
            client = CreatorClient(STATE, ACCOUNT, signer=Signer(), http=http)
            with self.assertRaises(PlatformError): client.publish_private('标题', '正文', [image])
            with self.assertRaises(PlatformError): client.publish_private('标题', '正文', [image])
            self.assertEqual(http.calls.count('post'), 1)

    def test_native_text_card_is_generated_without_note_submission(self):
        http = HTTP()
        client = CreatorClient(STATE, ACCOUNT, signer=Signer(), http=http)
        with patch('creator.download_image', return_value=(b'jpeg', 'image/jpeg')):
            self.assertEqual(client.text_card('你好'), b'jpeg')
        self.assertEqual(http.calls, ['get', 'post'])
        self.assertEqual(http.payload['text_config_list'][0]['text'], '你好')

    def test_submit_result_code_is_reported_without_response_body(self):
        class Rejected(HTTP):
            def post(self, url, **kwargs):
                self.calls.append('post')
                return Response({'success': False, 'result': -9059, 'msg': 'not for logs'})
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / 'image.png'
            Image.new('RGB', (4, 4), 'white').save(image)
            client = CreatorClient(STATE, ACCOUNT, signer=Signer(), http=Rejected())
            with self.assertRaisesRegex(PlatformError, r'code -9059'):
                client.publish_private('标题', '正文', [image])


if __name__ == '__main__': unittest.main()
