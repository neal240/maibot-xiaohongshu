"""Convert verified one-to-one text messages into gateway-ready envelopes."""
from __future__ import annotations

import json
import re
from typing import Any
if __package__:
    from .xhs_policy import Decisions, Policy
    from .notes import shared_reference, image_url
else:
    from xhs_policy import Decisions, Policy
    from notes import shared_reference, image_url

_ID = re.compile(r'^[0-9a-f]{24}$')


def prepare_text(message: dict[str, Any], account_id: str, conversation_user: str,
                 policy: Policy, decisions: Decisions, *, not_before_ms: int,
                 on_note=None, on_sticker=None) -> dict | None:
    # Do not decode content until sender, recipient and private-chat scope pass.
    if not isinstance(message, dict) or not _ID.fullmatch(account_id): return None
    sender = message.get('sender_id')
    if message.get('group_chat') is not False: return None
    if message.get('receiver_id') != account_id: return None
    if not isinstance(sender, str) or not policy.permits(sender, conversation_user, group=False): return None
    if message.get('revoked'): return None
    timestamp = message.get('created_at')
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < not_before_ms: return None
    message_id = message.get('id')
    if not isinstance(message_id, str) or not message_id: return None
    content = message.get('content')
    if not isinstance(content, str) or len(content) > 100_000: return None
    try: payload = json.loads(content)
    except (ValueError, TypeError): return None
    if not isinstance(payload, dict): return None
    if payload.get('content_type') == 1:
        text = payload.get('content')
        if not isinstance(text, str) or not text.strip() or len(text) > 10000: return None
    elif payload.get('content_type') == 3:
        ref = shared_reference(content)
        if ref is None or on_note is None: return None
        text = f'用户转发了一篇小红书笔记（ID：{ref[0]}）。请使用小红书笔记查看工具阅读文字和图片。'
    elif payload.get('content_type') == 16:
        if on_sticker is None: return None
        sticker = payload.get('content')
        if isinstance(sticker, str):
            if len(sticker) > 100_000: return None
            try: sticker = json.loads(sticker)
            except (ValueError, TypeError): return None
        url = image_url({'url_default': sticker.get('url')}) if isinstance(sticker, dict) else None
        if not url: return None
        text = '用户发送了一个小红书表情包。'
    else: return None
    if not decisions.claim(account_id, message_id, sender, conversation_user, False, policy): return None
    if payload.get('content_type') == 3:
        on_note(sender, *ref)
    elif payload.get('content_type') == 16:
        on_sticker(sender, url)
    return {
        'message_id': message_id,
        'platform': 'xiaohongshu',
        'account_id': account_id,
        'timestamp': str(timestamp / 1000),
        'message_info': {'user_info': {'user_id': sender, 'user_nickname': sender},
                         'additional_config': {}},
        'raw_message': [{'type': 'text', 'data': text}],
    }
