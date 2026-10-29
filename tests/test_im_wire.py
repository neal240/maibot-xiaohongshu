import hashlib
import unittest
from im_wire import encode_text


class WireTests(unittest.TestCase):
    def test_captured_protocol_fixture(self):
        encoded = encode_text('a' * 24, 'b' * 24, '测试文字',
                              message_id='00000000-0000-4000-8000-000000000000',
                              timestamp_ms=1234567890000)
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                         '45b10ede74960d3364d6021287e37a83b36c1a32e4164fabd19e3694000e6bf2')
