"""Clear server-only chat history using WeChat's own settings and checked UI."""
from pathlib import Path
import time

from PIL import Image, ImageChops, ImageStat

import checkin
import ui

TEMPLATES = Path(__file__).with_name('ui-templates')
RECTS = {
    'main-menu': (232, 567, 364, 764),
    'storage-settings': (508, 391, 931, 588),
    'clear-button': (803, 603, 929, 631),
    'clear-confirm': (489, 336, 783, 562),
}


def matches(frame, name):
    expected = Image.open(TEMPLATES / (name + '.png')).convert('RGB')
    actual = frame.crop(RECTS[name]).convert('RGB')
    if actual.size != expected.size:
        return False
    difference = ImageChops.difference(actual, expected)
    text_mask = expected.convert('L').point(lambda value: 255 if value < 180 else 0)
    if sum(text_mask.histogram()[1:]) < 50:
        return False
    # Blank or unrelated dialogs must not pass merely because most of the background is white.
    return (sum(ImageStat.Stat(difference).mean) / 3 < 8
            and sum(ImageStat.Stat(difference, text_mask).mean) / 3 < 40)


def wait_for(*names):
    for _ in range(18):
        frame = ui.screenshot()
        if all(matches(frame, name) for name in names):
            return
        time.sleep(.3)
    raise RuntimeError('CHAT_CLEAR_UI_NOT_RECOGNIZED_' + '_'.join(names).upper().replace('-', '_'))


def perform(preview=False):
    info = checkin.container()
    if info['Config']['Image'] != 'wechat-web:4.1.13.26':
        raise RuntimeError('CHAT_CLEAR_CLIENT_VERSION_CHANGED')
    main = [w for w in ui.windows() if w['class'] == 'wechat' and w['instance'] == 'wechat' and w['width'] >= 800 and w['height'] >= 600]
    if len(main) != 1:
        raise RuntimeError('CHAT_CLEAR_REQUIRES_LOGIN')
    window = main[0]
    ui.x_events(f"x.XMapRaised(d,{window['id']});x.XMoveResizeWindow(d,{window['id']},180,116,913,667)")
    time.sleep(.4)
    # Only dismiss recognized settings/confirmation panels; never click an unknown dialog.
    frame = ui.screenshot()
    if matches(frame, 'clear-confirm'):
        ui.click(697, 510); time.sleep(.3)
        frame = ui.screenshot()
    if matches(frame, 'storage-settings'):
        ui.click(944, 173); time.sleep(.3)
    # Do not send Escape: the client can interpret it as an exit request.
    # A click on the empty title bar dismisses an ordinary popup without invoking an action.
    ui.click(600, 133); time.sleep(.2)
    ui.click(213, 747)
    wait_for('main-menu')
    ui.click(263, 742)
    wait_for('storage-settings', 'clear-button')
    if preview:
        ui.click(944, 173)
        return {'chat_clear_ui_verified': True, 'chat_records_cleared': False, 'preview': True}
    ui.click(864, 616)
    wait_for('clear-confirm')
    # This is the client-native "clear all" button; no database files are unlinked.
    ui.click(572, 510)
    for _ in range(30):
        time.sleep(.3)
        frame = ui.screenshot()
        if not matches(frame, 'clear-confirm') and matches(frame, 'storage-settings'):
            ui.click(944, 173)
            return {'chat_clear_ui_verified': True, 'chat_records_cleared': True, 'client_restarted': False,
                    'scope': 'server Linux WeChat local history', 'database_files_removed_manually': False}
    raise RuntimeError('CHAT_CLEAR_RESULT_UNCONFIRMED')
