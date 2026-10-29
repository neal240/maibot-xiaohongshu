import asyncio
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import plugin
from memory import NoteMemory

ME, HOME_NOTE, SEARCH_NOTE = 'a' * 24, 'b' * 24, 'c' * 24


class Client:
    def __init__(self):
        self.calls = []
        self.feed = [{'id': HOME_NOTE, 'xsec_token': 'test',
                      'note_card': {'display_title': '日常中的小发现'}}]

    def home_feed(self, *, limit):
        self.calls.append(('home', limit))
        return self.feed

    def search_public_notes(self, keyword, *, limit):
        self.calls.append(('search', keyword))
        return [{'encrypted_id': 'A' * 44 + '==',
                 'note_card': {'display_title': '搜索笔记', 'desc': '搜索正文'}}]

    def resolve_search_id(self, opaque): return SEARCH_NOTE
    def note_detail(self, note_id, token, *, source):
        return {'title': '日常中的小发现', 'desc': '推荐正文'}


class BrowseFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = NoteMemory(Path(self.temp.name) / 'memory.sqlite3')
        self.instance = plugin.create_plugin()
        self.instance._set_context(SimpleNamespace(logger=logging.getLogger('browse-test')))
        self.instance.set_plugin_config({'plugin': {'config_version': '1.0.0'},
                                         'browse': {'enabled': True, 'interests': ['F1', '猫']}})
        self.instance._account = ME
        self.instance._memory = self.memory
        self.instance._client = Client()
        self.instance._browse_client = self.instance._client
        self.instance._browse_allowed = lambda: True
        self.answers = []
        self.prompts = []

        async def generate(_kind, prompt, **_kwargs):
            self.prompts.append(prompt)
            return {'success': True, 'response': self.answers.pop(0)}
        self.instance._generate = generate

    async def asyncTearDown(self):
        self.memory.close()
        self.temp.cleanup()

    async def test_home_choice_can_be_outside_interest_words(self):
        self.answers = ['[0]', '一条摘要']
        await self.instance._browse_once()
        self.assertEqual(self.instance._client.calls, [('home', 10)])
        row = self.memory.history(ME)['items'][0]
        self.assertEqual((row['keyword'], row['title']), ('首页推荐', '日常中的小发现'))
        self.assertIn('不必局限于这些词', self.prompts[0])

    async def test_no_home_choice_searches_random_word(self):
        self.answers = ['[]', '[0]', '搜索摘要']
        with patch.object(plugin.random, 'choice', return_value='猫') as choose:
            await self.instance._browse_once()
        choose.assert_called_once_with(['F1', '猫'])
        self.assertEqual(self.instance._client.calls, [('home', 10), ('search', '猫')])
        self.assertEqual(self.memory.history(ME)['items'][0]['keyword'], '猫')

    async def test_invalid_model_selection_does_not_trigger_search(self):
        self.answers = ['选择第一个']
        await self.instance._browse_once()
        self.assertEqual(self.instance._client.calls, [('home', 10)])
        self.assertEqual(self.memory.history(ME)['total'], 0)

    async def test_empty_interests_can_still_browse_home(self):
        self.instance.config.browse.interests = []
        self.answers = ['[0]', '一条摘要']
        await self.instance._browse_once()
        self.assertEqual(self.instance._client.calls, [('home', 10)])
        self.assertEqual(self.memory.history(ME)['total'], 1)

    async def test_empty_home_without_interests_skips_search(self):
        self.instance.config.browse.interests = []
        self.instance._client.feed = []
        await self.instance._browse_once()
        self.assertEqual(self.instance._client.calls, [('home', 10)])
        self.assertEqual(self.memory.history(ME)['total'], 0)

    async def test_browse_platform_error_pauses_browse_without_stopping_gateway(self):
        root = Path(self.temp.name)
        self.instance.ctx.paths = SimpleNamespace(data_dir=root)
        self.instance.ctx.gateway = SimpleNamespace(update_state=AsyncMock(return_value=True))
        self.instance._poll_dm = AsyncMock()
        self.instance._memory = None
        class FailingBrowseClient:
            def __init__(self, *_args): pass
            def identity(self): return ME
            def home_feed(self, *, limit): raise plugin.PlatformError('platform request unsuccessful')
        session = {'version': 1, 'shared_cookies': {}}
        with patch.object(plugin, 'ReadOnlyClient', FailingBrowseClient), \
             patch.object(plugin.SessionStore, 'load', return_value=session):
            self.instance._worker = asyncio.create_task(self.instance._run())
            for _ in range(100):
                if self.instance._browse_paused: break
                await asyncio.sleep(.01)
            self.assertTrue(self.instance._browse_paused)
            self.assertTrue((root / 'browse-platform-paused').exists())
            self.assertFalse(self.instance._worker.done())
            self.assertIsNotNone(self.instance._client)
            self.instance._poll_dm.assert_awaited()
            await self.instance._stop()


if __name__ == '__main__':
    unittest.main()
