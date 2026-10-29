import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from memory import NoteMemory
from notes import shared_reference, image_url

NOTE = 'c' * 24


class NoteTests(unittest.TestCase):
    def test_only_supported_note_cards_are_parsed(self):
        card = lambda link: json.dumps({'content_type': 3, 'content': json.dumps({'link': link})})
        self.assertEqual(shared_reference(card('xhsdiscover://item/' + NOTE + '?xsec_token=t')), (NOTE, 't'))
        self.assertEqual(shared_reference(card('https://www.xiaohongshu.com/explore/' + NOTE)), (NOTE, ''))
        self.assertIsNone(shared_reference(card('https://evil.example/explore/' + NOTE)))
        self.assertIsNone(shared_reference(card('https://www.xiaohongshu.com.evil.example/explore/' + NOTE)))
        self.assertIsNone(shared_reference(card('xhsdiscover://item/not-an-id')))

    def test_image_urls_are_restricted_and_redirects_not_followed(self):
        self.assertEqual(image_url({'url_default': 'http://ci.xhscdn.com/a'}), 'https://ci.xhscdn.com/a')
        self.assertIsNone(image_url({'url_default': 'https://ci.xhscdn.com.evil.example/a'}))
        self.assertIsNone(image_url({'url_default': 'https://127.0.0.1/a'}))
        self.assertIsNone(image_url({'url_default': 'https://ci.xhscdn.com:99999/a'}))
        self.assertIsNone(image_url({'url_default': 'https://name:password@ci.xhscdn.com/a'}))

    def test_memory_is_account_scoped_and_wildcards_are_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = NoteMemory(Path(tmp) / 'memory.sqlite')
            memory.put('account1', NOTE, '猫', '一只白猫')
            self.assertTrue(memory.contains('account1', NOTE))
            self.assertEqual(len(memory.search('account1', '猫')), 1)
            self.assertEqual(memory.search('account2', '猫'), [])
            self.assertEqual(memory.search('account1', '%'), [])
            memory.close()

    def test_old_database_migrates_and_history_preserves_legacy_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'memory.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('''CREATE TABLE notes (account TEXT NOT NULL, note_id TEXT NOT NULL,
                    keyword TEXT NOT NULL, summary TEXT NOT NULL, saved_at INTEGER NOT NULL,
                    PRIMARY KEY(account,note_id))''')
                db.execute("INSERT INTO notes VALUES ('account1', ?, '猫', '旧摘要', strftime('%s','now'))", (NOTE,))
            memory = NoteMemory(path)
            item = memory.history('account1')['items'][0]
            self.assertEqual((item['summary'], item['title'], item['body'], item['status']), ('旧摘要', '', '', 'complete'))
            self.assertEqual(memory.history('account2')['total'], 0)
            memory.close()

    def test_view_history_tracks_failed_summary_without_using_it_as_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = NoteMemory(Path(tmp) / 'memory.sqlite')
            memory.record_view('account1', NOTE, 'F1', '比赛记录', '练习赛的内容')
            self.assertEqual(memory.history('account1')['items'][0]['status'], 'reading')
            self.assertFalse(memory.contains('account1', NOTE))
            memory.finish_view('account1', NOTE, None)
            item = memory.history('account1', query='练习赛')['items'][0]
            self.assertEqual((item['title'], item['body'], item['status']), ('比赛记录', '练习赛的内容', 'failed'))
            self.assertEqual(memory.search('account1', 'F1'), [])
            memory.finish_view('account1', NOTE, '比赛摘要')
            self.assertTrue(memory.contains('account1', NOTE))
            self.assertEqual(memory.search('account1', 'F1')[0][2], '比赛摘要')
            self.assertEqual(memory.history('account1', query='%')['total'], 0)
            self.assertEqual(memory.history('account2')['total'], 0)
            memory.close()

    def test_interrupted_read_is_marked_failed_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'memory.sqlite'
            memory = NoteMemory(path)
            memory.record_view('account1', NOTE, '猫', '标题', '正文')
            memory.close()
            memory = NoteMemory(path)
            self.assertEqual(memory.history('account1')['items'][0]['status'], 'failed')
            memory.close()


if __name__ == '__main__': unittest.main()
