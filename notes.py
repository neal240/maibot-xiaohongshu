"""Bounded processing of untrusted note cards and images."""
from __future__ import annotations

import io
import json
import re
from urllib.parse import parse_qs, urlsplit

_ID = re.compile(r'^[0-9a-f]{24}$')


def shared_reference(content: object) -> tuple[str, str] | None:
    """Read only after the sender and private conversation have been authorized."""
    try:
        outer = json.loads(content) if isinstance(content, str) and len(content) <= 100_000 else None
        if not isinstance(outer, dict) or outer.get('content_type') != 3: return None
        card = outer.get('content')
        if isinstance(card, str) and len(card) <= 100_000: card = json.loads(card)
        if not isinstance(card, dict) or not isinstance(card.get('link'), str): return None
        url = urlsplit(card['link'])
        if url.scheme == 'xhsdiscover' and url.netloc == 'item':
            note_id = url.path.strip('/').lower()
        elif url.scheme == 'https' and url.hostname in {'www.xiaohongshu.com', 'xiaohongshu.com'}:
            parts = url.path.strip('/').split('/')
            if len(parts) == 2 and parts[0] == 'explore': note_id = parts[1].lower()
            elif len(parts) == 3 and parts[:2] == ['discovery', 'item']: note_id = parts[2].lower()
            else: return None
        else: return None
        token = parse_qs(url.query).get('xsec_token', [''])[0]
        if not _ID.fullmatch(note_id) or len(token) > 2048: return None
        return note_id, token
    except (ValueError, TypeError):
        return None


def image_url(image: object) -> str | None:
    if not isinstance(image, dict): return None
    candidates = [image.get('url_default'), image.get('url_pre')]
    info = image.get('info_list')
    if isinstance(info, list):
        candidates.extend(item.get('url') for item in info[:10] if isinstance(item, dict))
    for url in candidates:
        if not isinstance(url, str) or len(url) > 4096: continue
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError: continue
        host = (parsed.hostname or '').lower()
        if (parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password
                and port in (None, 80, 443)
                and (host == 'xhscdn.com' or host.endswith('.xhscdn.com')
                     or host == 'xiaohongshu.com' or host.endswith('.xiaohongshu.com'))):
            return parsed._replace(scheme='https', netloc=host).geturl()
    return None


def download_image(url: str, *, request=None) -> tuple[bytes, str]:
    if image_url({'url_default': url}) != url: raise ValueError('unsupported image URL')
    if request is None:
        from curl_cffi import requests
        request = requests.get
    response = request(url, stream=True, timeout=15, allow_redirects=False, impersonate='chrome')
    try:
        if response.status_code != 200 or not response.headers.get('Content-Type', '').lower().startswith('image/'):
            raise ValueError('image unavailable')
        chunks, total = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > 8 * 1024 * 1024: raise ValueError('image too large')
            chunks.append(chunk)
    finally:
        response.close()
    from PIL import Image
    with Image.open(io.BytesIO(b''.join(chunks))) as image:
        if image.width * image.height > 20_000_000: raise ValueError('image dimensions too large')
        image.seek(0)
        image.thumbnail((1024, 1024))
        output = io.BytesIO()
        image.convert('RGB').save(output, format='JPEG', quality=85)
    return output.getvalue(), 'image/jpeg'


def note_text(note: dict) -> str:
    title = note.get('title') or note.get('display_title') or ''
    desc = note.get('desc') or ''
    title = title[:200] if isinstance(title, str) else ''
    desc = desc[:6000] if isinstance(desc, str) else ''
    return f'标题：{title}\n正文：{desc}'
