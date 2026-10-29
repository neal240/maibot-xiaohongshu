import json
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


if __name__ == '__main__': unittest.main()
