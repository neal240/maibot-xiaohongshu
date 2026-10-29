"""Experimental creator upload and owner-visible image note submission.

Protocol fields are derived from publicly documented third-party interface
descriptions; this module does not import the earlier research client.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

if __package__:
    from .xhs_client import UA, PlatformError
    from .notes import download_image, image_url
else:
    from xhs_client import UA, PlatformError
    from notes import download_image, image_url


class CreatorClient:
    def __init__(self, state: dict, account: str, *, signer=None, http=None):
        if not re.fullmatch(r'[0-9a-f]{24}', account): raise ValueError('invalid account')
        self.account = account
        self.cookies = dict(state['shared_cookies'])
        self.cookies.update((state.get('host_cookies') or {}).get('creator.xiaohongshu.com', {}))
        if not self.cookies.get('a1') or not self.cookies.get('web_session'):
            raise ValueError('missing session')
        if signer is None:
            from xhshow import Xhshow
            signer = Xhshow()
        if http is None:
            from curl_cffi import requests
            http = requests
        self.signer, self.http, self.stopped = signer, http, False

    def _get(self, path: str, params: dict | None = None) -> dict:
        if self.stopped: raise PlatformError('creator client is stopped')
        headers = self.signer.sign_headers_get(uri=path, cookies=self.cookies, xsec_appid='ugc', params=params)
        headers.update({'User-Agent': UA, 'Origin': 'https://creator.xiaohongshu.com',
                        'Referer': 'https://creator.xiaohongshu.com/publish/publish?source=official'})
        try:
            response = self.http.get('https://creator.xiaohongshu.com' + path, params=params,
                                     headers=headers, cookies=self.cookies, timeout=12,
                                     impersonate='chrome', allow_redirects=False)
            if response.status_code != 200: raise PlatformError(f'creator rejected (HTTP {response.status_code})')
            data = response.json()
            if not isinstance(data, dict) or data.get('success') is not True:
                raise PlatformError('creator request unsuccessful')
            return data.get('data') or {}
        except Exception as exc:
            self.stopped = True
            if isinstance(exc, PlatformError): raise
            raise PlatformError('creator request failed') from None

    def verify(self) -> None:
        data = self._get('/api/galaxy/user/info')
        if data.get('userId') != self.account:
            self.stopped = True
            raise PlatformError('creator account does not match signed-in account')

    def text_card(self, text: str, *, style_index: int = 0) -> bytes:
        """Generate one creator-native text illustration; does not publish a note."""
        if self.stopped: raise PlatformError('creator client is stopped')
        if not isinstance(text, str) or not text.strip() or len(text) > 140:
            raise ValueError('text card content must contain at most 140 characters')
        if not isinstance(style_index, int) or not 0 <= style_index <= 9:
            raise ValueError('invalid text card style')
        self.verify()
        path = '/api/galaxy/v2/creator/post/inspiration/text2imgv3'
        attrs = {'edit_content': text, 'text_list': [text], 'text_size': 0,
                 'line_space': 0, 'word_space': 0, 'use_system_fonts': 0}
        payload = {'page_type': 'cover', 'text_config_list': [{'index': 0, 'text': text,
                   'text_attribute': json.dumps(attrs, ensure_ascii=False, separators=(',', ':'))}],
                   'style_json': '', 'page_num': 1, 'request_id': self.signer.get_search_request_id(), 'extra_info': ''}
        headers = self.signer.sign_headers_post(uri=path, cookies=self.cookies, xsec_appid='ugc', payload=payload)
        headers.update({'User-Agent': UA, 'Origin': 'https://creator.xiaohongshu.com',
                        'Referer': 'https://creator.xiaohongshu.com/publish/publish?target=image',
                        'Content-Type': 'application/json'})
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        try:
            response = self.http.post('https://creator.xiaohongshu.com' + path, headers=headers,
                                      cookies=self.cookies, data=body, timeout=20,
                                      impersonate='chrome', allow_redirects=False)
            if response.status_code != 200: raise PlatformError(f'text card rejected (HTTP {response.status_code})')
            result = response.json()
            if not isinstance(result, dict) or result.get('success') is not True:
                raise PlatformError('text card generation unsuccessful')
            styles = (result.get('data') or {}).get('text2_img_type_results') or []
            if not isinstance(styles, list) or len(styles) <= style_index or not isinstance(styles[style_index], dict):
                raise PlatformError('text card style unavailable')
            url = image_url({'url_default': styles[style_index].get('img_url')})
            if not url: raise PlatformError('invalid text card image URL')
            image, _ = download_image(url, request=self.http.get)
            return image
        except Exception as exc:
            self.stopped = True
            if isinstance(exc, PlatformError): raise
            raise PlatformError('text card generation failed') from None

    def upload(self, path: Path) -> dict:
        from PIL import Image
        raw = path.read_bytes()
        if not raw or len(raw) > 8 * 1024 * 1024: raise ValueError('image size outside limit')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 20_000_000: raise ValueError('image dimensions too large')
            image.verify()
            mime = Image.MIME.get(image.format)
        if mime not in {'image/png', 'image/jpeg', 'image/webp'}: raise ValueError('unsupported image')
        permit = self._get('/api/media/v1/upload/web/permit',
                           {'biz_name': 'spectrum', 'scene': 'image', 'file_count': 1,
                            'version': '1', 'source': 'web'})
        permits = permit.get('uploadTempPermits') or []
        if not permits or not isinstance(permits[0], dict): raise PlatformError('upload permit missing')
        record = permits[0]
        file_id = (record.get('fileIds') or [''])[0]
        token = record.get('token')
        if not isinstance(file_id, str) or not re.fullmatch(r'[A-Za-z0-9_/-]{1,300}', file_id) or '..' in file_id:
            raise PlatformError('invalid upload file ID')
        if not isinstance(token, str) or not token: raise PlatformError('invalid upload token')
        try:
            response = self.http.put('https://ros-upload.xiaohongshu.com/' + file_id,
                                     headers={'X-Cos-Security-Token': token, 'Content-Type': mime},
                                     data=raw, timeout=20, impersonate='chrome', allow_redirects=False)
            if response.status_code not in (200, 201, 204):
                raise PlatformError(f'image upload rejected (HTTP {response.status_code})')
        except Exception as exc:
            self.stopped = True
            if isinstance(exc, PlatformError): raise
            raise PlatformError('image upload failed') from None
        return {'file_id': file_id, 'metadata': {'source': -1},
                'stickers': {'version': 2, 'floating': []},
                'extra_info_json': json.dumps({'mimeType': mime}, separators=(',', ':'))}

    def publish_private(self, title: str, text: str, images: list[Path]) -> bool:
        return self.publish(title, text, images, private=True)

    def publish(self, title: str, text: str, images: list[Path], *, private: bool = True) -> bool:
        if not isinstance(title, str) or not title.strip() or len(title) > 20:
            raise ValueError('invalid note title')
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ValueError('invalid note text')
        if not 1 <= len(images) <= 9: raise ValueError('one to nine images are required')
        self.verify()
        uploaded = [self.upload(path) for path in images]
        path = '/web_api/sns/v2/note'
        binds = {'version': 1, 'noteId': 0, 'noteOrderBind': {},
                 'notePostTiming': {'postTime': None}, 'noteCollectionBind': {'id': ''}}
        payload = {'common': {'type': 'normal', 'title': title, 'note_id': '', 'desc': text,
                   'source': '{"type":"web","ids":"","extraInfo":"{\\"subType\\":\\"official\\"}"}',
                   'business_binds': json.dumps(binds, separators=(',', ':')), 'ats': [], 'hash_tag': [],
                   'privacy_info': {'op_type': 1, 'type': int(private)}},
                   'image_info': {'images': uploaded}, 'video_info': None}
        headers = self.signer.sign_headers_post(uri=path, cookies=self.cookies, xsec_appid='ugc',
                                                payload=payload, x_rap=True, user_id=self.account)
        headers.update({'User-Agent': UA, 'Origin': 'https://creator.xiaohongshu.com',
                        'Referer': 'https://creator.xiaohongshu.com/', 'Content-Type': 'application/json'})
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        try:
            response = self.http.post('https://edith.xiaohongshu.com' + path, headers=headers,
                                      cookies=self.cookies, data=body, timeout=20,
                                      impersonate='chrome', allow_redirects=False)
            if response.status_code != 200:
                raise PlatformError(f'publication rejected or uncertain (HTTP {response.status_code})')
            data = response.json()
            if not isinstance(data, dict) or data.get('success') is not True:
                code = (data.get('code') if isinstance(data.get('code'), int) else data.get('result')) if isinstance(data, dict) else None
                raise PlatformError(f'publication not confirmed (code {code if isinstance(code, int) else "unknown"})')
            return True
        except Exception as exc:
            self.stopped = True
            if isinstance(exc, PlatformError): raise
            raise PlatformError('publication result uncertain; never retry automatically') from None
