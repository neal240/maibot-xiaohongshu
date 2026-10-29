import tempfile
import unittest
from pathlib import Path
from publishing import PublishState, image_paths


class PublishingTests(unittest.TestCase):
    def test_uncertain_publish_is_never_retried_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.sqlite'
            state = PublishState(path)
            self.assertTrue(state.begin('a', 100, now=1000))
            state.close()
            state = PublishState(path)
            self.assertFalse(state.begin('a', 100, now=9999))
            self.assertTrue(state.clear_uncertain('a'))
            self.assertTrue(state.begin('a', 100, now=9999))
            state.finish('a', success=True)
            self.assertFalse(state.begin('a', 100, now=10000))
            self.assertTrue(state.begin('a', 100, now=10100))
            state.finish('a', success=False)
            self.assertFalse(state.begin('a', 100, now=30000))
            state.close()

    def test_images_must_be_existing_files_inside_material_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            images = root / 'images'
            images.mkdir()
            (images / 'cover.png').write_bytes(b'example')
            (root / 'outside.png').write_bytes(b'example')
            self.assertEqual(image_paths(images, ['cover.png']), [(images / 'cover.png').resolve()])
            with self.assertRaises(ValueError): image_paths(images, ['../outside.png'])
            with self.assertRaises(ValueError): image_paths(images, ['missing.png'])
            with self.assertRaises(ValueError): image_paths(images, [])


if __name__ == '__main__': unittest.main()
