import asyncio
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from identity import IdentityLinks
import plugin
from xhs_policy import Policy

ACCOUNT, OTHER, USER, UNKNOWN = 'a' * 24, 'b' * 24, 'c' * 24, 'd' * 24
QQ, OTHER_QQ = '123456789', '123456780'


class IdentityStoreTests(unittest.TestCase):
    def test_links_are_account_scoped_and_reversible(self):
        with tempfile.TemporaryDirectory() as d:
            store = IdentityLinks(Path(d) / 'identity.sqlite3')
            store.set(ACCOUNT, USER, QQ)
            self.assertEqual(store.get(ACCOUNT, USER), QQ)
            self.assertIsNone(store.get(OTHER, USER))
            store.set(ACCOUNT, USER, OTHER_QQ)
            self.assertEqual(store.get(ACCOUNT, USER), OTHER_QQ)
            store.delete(ACCOUNT, USER)
            self.assertIsNone(store.get(ACCOUNT, USER))
            for bad in ('', '123', '123456;rm', '../123456'):
                with self.assertRaises(ValueError): store.set(ACCOUNT, USER, bad)
            store.close()


class IdentityFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.links = IdentityLinks(Path(self.temp.name) / 'identity.sqlite3')
        self.instance = plugin.create_plugin()
        self.instance._account = ACCOUNT
        self.instance._policy = Policy(frozenset({USER}), 1)
        self.instance._identity_links = self.links
        self.append = AsyncMock(return_value={'success': True})
        self.chat = SimpleNamespace(
            get_private_streams=AsyncMock(side_effect=lambda platform: (
                [{'user_id': QQ, 'user_nickname': 'QQ 好友'}] if platform == 'qq' else
                [{'user_id': USER, 'account_id': ACCOUNT}, {'user_id': UNKNOWN, 'account_id': ACCOUNT}])),
            open_session=AsyncMock(return_value={'success': True, 'stream_id': 'stream'}))
        async def get_value(pid, field):
            return {'is_known': pid != 'unknown', 'person_name': '阿明', 'memory_points': ['喜欢赛车']}[field]
        self.person = SimpleNamespace(get_id=AsyncMock(side_effect=lambda _platform, uid: 'unknown' if uid == OTHER_QQ else 'person-id'),
                                      get_value=AsyncMock(side_effect=get_value))
        self.instance._set_context(SimpleNamespace(chat=self.chat, person=self.person,
            maisaka=SimpleNamespace(context=SimpleNamespace(append=self.append)), logger=logging.getLogger('identity-test')))

    async def asyncTearDown(self):
        self.links.close()
        self.temp.cleanup()

    async def test_explicit_binding_and_bounded_internal_context(self):
        result = await self.instance.identity_list()
        self.assertEqual([item['id'] for item in result['xhs_users']], [USER])
        await self.instance.identity_bind(USER, QQ)
        await self.instance._add_identity_context(USER)
        call = self.append.await_args
        text = call.args[1][0]['data']
        self.assertIn('小红书', text)
        self.assertIn('阿明', text)
        self.assertIn('喜欢赛车', text)
        self.assertFalse(call.kwargs['replyable'])
        await self.instance._add_identity_context(USER)
        self.assertEqual(self.append.await_count, 1)
        await self.instance.identity_unbind(USER)
        await self.instance._add_identity_context(USER)
        self.assertEqual(self.append.await_count, 2)
        self.assertIn('"qq_binding":null', self.append.await_args.args[1][0]['data'])
        self.assertNotIn('阿明', self.append.await_args.args[1][0]['data'])

    async def test_only_listed_and_allowed_users_can_be_bound(self):
        with self.assertRaises(ValueError): await self.instance.identity_bind(UNKNOWN, QQ)
        with self.assertRaises(ValueError): await self.instance.identity_bind(USER, OTHER_QQ)
        self.assertEqual(self.links.list(ACCOUNT), [])

    async def test_manual_qq_user_must_be_known(self):
        await self.instance.identity_bind(USER, '987654321')
        self.assertEqual(self.links.get(ACCOUNT, USER), '987654321')

    async def test_context_failure_does_not_raise(self):
        self.chat.open_session.side_effect = RuntimeError('offline')
        await self.instance._add_identity_context(USER)
        self.assertNotIn(USER, self.instance._identity_context)

    async def test_context_for_another_sender_does_not_contain_bound_data(self):
        self.links.set(ACCOUNT, USER, QQ)
        await self.instance._add_identity_context(UNKNOWN)
        text = self.append.await_args.args[1][0]['data']
        self.assertIn('"qq_binding":null', text)
        self.assertNotIn(QQ, text)
        self.person.get_id.assert_not_awaited()

    async def test_unbind_waits_for_inflight_context_then_invalidates_it(self):
        self.links.set(ACCOUNT, USER, QQ)
        started, finish = asyncio.Event(), asyncio.Event()
        async def delayed_append(*_args, **_kwargs):
            started.set()
            await finish.wait()
            return {'success': True}
        self.append.side_effect = delayed_append
        context = asyncio.create_task(self.instance._add_identity_context(USER))
        await started.wait()
        unbind = asyncio.create_task(self.instance.identity_unbind(USER))
        await asyncio.sleep(0)
        self.assertFalse(unbind.done())
        finish.set()
        await asyncio.gather(context, unbind)
        self.assertIsNone(self.links.get(ACCOUNT, USER))
        self.assertNotIn(USER, self.instance._identity_context)


if __name__ == '__main__':
    unittest.main()
