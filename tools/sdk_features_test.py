"""Integration checks using the installed SDK and isolated fake services."""
import asyncio
import json
import logging
import tempfile
import time
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plugin
from memory import NoteMemory
from publishing import PublishState

ME, USER, NOTE = 'a' * 24, 'b' * 24, 'c' * 24


class Gateway:
    def __init__(self): self.messages, self.event = [], asyncio.Event()
    async def update_state(self, **kwargs): return True
    async def route_message(self, **kwargs):
        self.messages.append(kwargs['message'])
        self.event.set()
        return True


class FakeClient:
    def __init__(self, state, policy): pass
    def identity(self): return ME
    def history(self, user, *, limit):
        return [{'sender_id': USER, 'receiver_id': ME, 'group_chat': False,
                 'id': 'one', 'created_at': int(time.time() * 1000) + 100,
                 'content': json.dumps({'content_type': 1, 'content': 'synthetic'})}]
    def history_since(self, user, not_before): return self.history(user, limit=20)
    def home_feed(self, **kwargs):
        return [{'id': NOTE, 'xsec_token': 'example', 'note_card': {'display_title': '猫的日常'}}]
    def search_public_notes(self, *args, **kwargs): return []
    def note_detail(self, *args, **kwargs):
        return {'title': '猫的日常', 'desc': '一只猫',
                'image_list': [{'url_default': 'https://ci.xhscdn.com/synthetic.jpg'}]}
    def send_text(self, *args, **kwargs): raise AssertionError('rate zero must block sending')


class FakeLLM:
    async def generate(self, prompt, **kwargs):
        if '规划一篇' in prompt:
            return {'success': True, 'response': '{"publish":true,"title":"标题","text":"正文"}',
                    'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}
        return {'success': True, 'response': '摘要：一只猫。', 'prompt_tokens': 10,
                'completion_tokens': 10, 'total_tokens': 20}


class FakeCreator:
    calls = []
    def __init__(self, *args): pass
    def text_card(self, title, *, style_index): return b'native-image'
    def publish(self, title, text, images, *, private):
        assert images and images[0].is_file()
        self.calls.append((title, text, private, len(images)))
        return True


async def main():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / 'auth').mkdir()
        (root / 'auth' / 'session.json').write_text(json.dumps({'version': 1, 'shared_cookies': {}}))
        (root / 'publish-images').mkdir()
        (root / 'publish-images' / 'cover.png').write_bytes(b'dummy')
        gateway = Gateway()
        context = SimpleNamespace(paths=SimpleNamespace(data_dir=root, runtime_dir=root / 'temp'), gateway=gateway,
                                  llm=FakeLLM(), logger=logging.getLogger('test'))
        instance = plugin.create_plugin()
        instance._set_context(context)
        instance.set_plugin_config({'plugin': {'enabled': True, 'config_version': '1.0.0'},
            'dm': {'allowed_users': [USER], 'reply_probability': 0, 'poll_seconds': 30},
            'browse': {'enabled': False, 'interests': ['猫']},
            'publish': {'enabled': False, 'image_files': ['cover.png'], 'private': True}})
        with patch.object(plugin, 'ReadOnlyClient', FakeClient), patch.object(plugin, 'CreatorClient', FakeCreator):
            await instance.on_load()
            await asyncio.wait_for(gateway.event.wait(), 5)
            assert len(gateway.messages) == 1
            outgoing = {'platform': 'xiaohongshu', 'account_id': ME,
                'message_info': {'additional_config': {'platform_io_target_user_id': USER}},
                'raw_message': [{'type': 'text', 'data': 'reply'}]}
            assert not (await instance.send_to_platform(outgoing))['success']
            await instance._browse_once()
            assert instance._memory.contains(ME, NOTE)
            assert '一只猫' in (await instance.search_memory('猫'))['content']
            usage = await instance.usage_status()
            assert usage['browse']['calls'] == 2 and usage['browse']['total_tokens'] == 40
            instance.config.browse.daily_token_limit = 40
            assert instance._browse_budget_reached()
            instance.config.browse.daily_token_limit = 0
            search_note_id = 'd' * 24
            instance._client.search_public_notes = lambda *args, **kwargs: [{
                'encrypted_id': 'A' * 44 + '==', 'note_card': {'display_title': '猫的新事',
                'title': '猫的新事', 'desc': '一只猫'}}]
            instance._client.resolve_search_id = lambda value: search_note_id
            await instance._browse_once()
            assert instance._memory.contains(ME, search_note_id)
            with patch.object(plugin, 'download_image', return_value=(b'image-bytes', 'image/jpeg')):
                msg = {'raw_message': [{'type': 'text', 'data': ''}]}
                await instance._enrich_note(msg, NOTE, 'example')
                assert msg['raw_message'][1]['binary_data_base64'] == 'aW1hZ2UtYnl0ZXM='
            await instance._plan_publish()
            assert FakeCreator.calls == [('标题', '正文', True, 1)]
            assert instance._publication.status(ME)['state'] == 'published'
            assert (await instance.usage_status())['publish']['total_tokens'] == 20
            await instance._plan_publish()
            assert len(FakeCreator.calls) == 1
            with instance._publication.db:
                instance._publication.db.execute('DELETE FROM attempts')
            instance.set_plugin_config({'plugin': {'enabled': True, 'config_version': '1.0.0'},
                'dm': {'allowed_users': [USER], 'reply_probability': 0, 'poll_seconds': 30},
                'browse': {'enabled': False, 'interests': ['猫']},
                'publish': {'enabled': False, 'image_mode': 'text_card', 'private': True}})
            await instance._plan_publish()
            assert len(FakeCreator.calls) == 2
            assert not list((root / 'temp').glob('*.jpg'))
            await instance.on_unload()
    print('SDK_FEATURES_FAKE_HOST_TEST: PASS')


if __name__ == '__main__': asyncio.run(main())
