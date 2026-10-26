import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import ui


class SchoolLogoTests(unittest.TestCase):
    def setUp(self):
        self.logo = Image.new('RGB', (48, 48), '#174d9c')
        draw = ImageDraw.Draw(self.logo)
        draw.ellipse((7, 7, 40, 40), fill='white')
        draw.rectangle((20, 12, 27, 35), fill='#174d9c')
        self.blank = Image.new('RGB', (1280, 900), '#eeeeee')
        self.loaded = self.blank.copy()
        self.loaded.paste(self.logo, (369 - 24, 239 - 24))

    def test_loading_and_duplicate_icons_cannot_trigger_click(self):
        self.assertIsNone(ui.find_school_logo(self.blank, self.logo))
        duplicate = self.loaded.copy()
        duplicate.paste(self.logo, (455 - 24, 239 - 24))
        self.assertIsNone(ui.find_school_logo(duplicate, self.logo))

    def test_waits_for_loaded_stable_icon(self):
        with patch.object(ui, 'screenshot', side_effect=[self.blank, self.loaded, self.blank, self.loaded, self.loaded]) as capture, \
             patch.object(ui.time, 'sleep'), patch.object(ui, 'click') as click:
            score, x, y = ui.wait_for_school_logo(self.logo)
        self.assertEqual((x, y), (369, 239))
        self.assertEqual(capture.call_count, 5)
        click.assert_not_called()

    def test_same_app_in_recent_and_saved_rows_prefers_recent(self):
        frame = self.loaded.copy()
        frame.paste(self.logo, (283 - 24, 412 - 24))
        self.assertEqual(ui.find_school_logo(frame, self.logo)[1:], (369, 239))

    def test_missing_icon_times_out_without_click(self):
        with patch.object(ui, 'screenshot', return_value=self.blank), patch.object(ui, 'click') as click:
            with self.assertRaisesRegex(RuntimeError, 'SCHOOL_LOGO_NOT_MATCHED'):
                ui.wait_for_school_logo(self.logo, timeout=0)
        click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
