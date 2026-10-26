from PIL import Image
import unittest

import clear_chat_records as native


class ChatClearGuardTests(unittest.TestCase):
    def test_blank_background_is_not_a_confirmation_dialog(self):
        blank = Image.new('RGB', (1280, 900), (246, 246, 246))
        self.assertFalse(native.matches(blank, 'clear-confirm'))

    def test_only_matching_confirmation_labels_are_accepted(self):
        frame = Image.new('RGB', (1280, 900), 'white')
        template = Image.open(native.TEMPLATES / 'clear-confirm.png')
        frame.paste(template, native.RECTS['clear-confirm'][:2])
        self.assertTrue(native.matches(frame, 'clear-confirm'))
        frame.paste(Image.new('RGB', template.size, 'white'), native.RECTS['clear-confirm'][:2])
        self.assertFalse(native.matches(frame, 'clear-confirm'))


if __name__ == '__main__':
    unittest.main()
