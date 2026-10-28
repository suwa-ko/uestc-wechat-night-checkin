import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image, ImageDraw

import ui


class PasswordlessEntryTests(unittest.TestCase):
    def setUp(self):
        self.template = Image.open(Path(ui.__file__).with_name('ui-templates') / 'enter-wechat.png').convert('RGB')
        self.login = {'id': 123, 'instance': 'wechat', 'class': 'wechat', 'width': 292,
                      'height': 396, 'x': 494, 'y': 252}
        self.main = dict(self.login, width=917, height=667, x=181, y=117)
        self.frame = Image.new('RGB', (1280, 900), '#eeeeee')
        self.frame.paste(self.template, (self.login['x'] + 59, self.login['y'] + 289))

    def test_verified_button_matches_only_owned_window(self):
        self.assertEqual(ui.find_passwordless_entry(self.frame, [self.login], self.template), (123, 640, 559))

    def test_wrong_native_class_rejected(self):
        row = dict(self.login, **{'class': 'browser'})
        self.assertIsNone(ui.find_passwordless_entry(self.frame, [row], self.template))

    def test_ambiguous_native_windows_rejected(self):
        self.assertIsNone(ui.find_passwordless_entry(self.frame, [self.login, dict(self.login, id=124)], self.template))

    def test_qr_login_layout_without_entry_button_rejected(self):
        blank = Image.new('RGB', (1280, 900), 'white')
        self.assertIsNone(ui.find_passwordless_entry(blank, [self.login], self.template))

    def test_different_button_text_rejected_even_if_green(self):
        frame = self.frame.copy()
        draw = ImageDraw.Draw(frame)
        x, y = self.login['x'] + 59, self.login['y'] + 289
        draw.rectangle((x + 44, y + 5, x + 130, y + 31), fill=self.template.getpixel((20, 15)))
        draw.text((x + 50, y + 12), 'CONFIRM', fill='white')
        self.assertIsNone(ui.find_passwordless_entry(frame, [self.login], self.template))

    def test_disabled_gray_button_rejected(self):
        frame = self.frame.copy()
        frame.paste(self.template.convert('L').convert('RGB'), (self.login['x'] + 59, self.login['y'] + 289))
        self.assertIsNone(ui.find_passwordless_entry(frame, [self.login], self.template))

    def test_changed_window_geometry_rejected(self):
        self.assertIsNone(ui.find_passwordless_entry(self.frame, [dict(self.login, width=300)], self.template))

    def test_offscreen_window_rejected(self):
        self.assertIsNone(ui.find_passwordless_entry(self.frame, [dict(self.login, x=1200)], self.template))

    def test_changed_display_resolution_rejected(self):
        self.assertIsNone(ui.find_passwordless_entry(self.frame.resize((1920, 1080)), [self.login], self.template))

    def test_already_logged_in_does_not_capture_or_click(self):
        with patch.object(ui, 'windows', return_value=[self.main]), patch.object(ui, 'screenshot') as capture, patch.object(ui, 'click') as click:
            self.assertEqual(ui.ensure_wechat_ready(), {'passwordless_entry_clicked': False})
        capture.assert_not_called()
        click.assert_not_called()

    def test_missing_template_stops_without_click(self):
        with patch.object(ui, 'windows', return_value=[self.login]), patch.object(Path, 'is_file', return_value=False), patch.object(ui, 'click') as click:
            with self.assertRaisesRegex(RuntimeError, 'AUTH_REQUIRED'):
                ui.ensure_wechat_ready()
        click.assert_not_called()

    def test_exact_entry_is_clicked_once_then_main_window_confirmed(self):
        with patch.object(ui, 'windows', side_effect=[[self.login], [self.login], [self.login], [self.main]]), \
             patch.object(ui, 'screenshot', return_value=self.frame), patch.object(ui, 'x_events'), \
             patch.object(ui.time, 'sleep'), patch.object(ui, 'click') as click:
            self.assertEqual(ui.ensure_wechat_ready(), {'passwordless_entry_clicked': True})
        click.assert_called_once_with(640, 559)

    def test_phone_confirmation_wait_stops_after_one_entry_click(self):
        with patch.object(ui, 'windows', return_value=[self.login]), \
             patch.object(ui, 'screenshot', return_value=self.frame), patch.object(ui, 'x_events'), \
             patch.object(ui.time, 'sleep'), patch.object(ui, 'click') as click:
            with self.assertRaisesRegex(RuntimeError, 'AUTH_REQUIRED'):
                ui.ensure_wechat_ready(timeout=0)
        click.assert_called_once_with(640, 559)

    def test_moving_window_cancels_click(self):
        with patch.object(ui, 'windows', side_effect=[[self.login], [dict(self.login, x=495)]]), \
             patch.object(ui, 'screenshot', return_value=self.frame), patch.object(ui, 'x_events'), \
             patch.object(ui.time, 'sleep'), patch.object(ui, 'click') as click:
            with self.assertRaisesRegex(RuntimeError, 'AUTH_REQUIRED'):
                ui.ensure_wechat_ready()
        click.assert_not_called()

    def test_changing_button_cancels_click(self):
        with patch.object(ui, 'windows', return_value=[self.login]), \
             patch.object(ui, 'screenshot', side_effect=[self.frame, self.frame, Image.new('RGB', (1280, 900), 'white')]), \
             patch.object(ui, 'x_events'), patch.object(ui.time, 'sleep'), patch.object(ui, 'click') as click:
            with self.assertRaisesRegex(RuntimeError, 'AUTH_REQUIRED'):
                ui.ensure_wechat_ready()
        click.assert_not_called()


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
