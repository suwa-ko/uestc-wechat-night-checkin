"""Start the owned miniapp using a verified window class and school logo."""
import io
import json
from pathlib import Path
import re
import subprocess
import time

from PIL import Image, ImageChops, ImageStat

CONTAINER = 'wechat-web'
UI_BUILD = '2026.10.27.1'


def docker(*args, **kwargs):
    return subprocess.run(['docker', 'exec', *args], capture_output=True, check=True, timeout=20, **kwargs)


def windows():
    text = docker(CONTAINER, 'xwininfo', '-root', '-tree', text=True).stdout
    rows = []
    pattern = r'(0x[0-9a-f]+).*?\("([^"]*)" "([^"]*)"\).*?(\d+)x(\d+)([+-]\d+)([+-]\d+)'
    for line in text.splitlines():
        m = re.search(pattern, line)
        if m:
            rows.append({'id': int(m[1], 16), 'instance': m[2], 'class': m[3],
                         'width': int(m[4]), 'height': int(m[5]), 'x': int(m[6]), 'y': int(m[7])})
    return rows


def x_events(events):
    code = '''import ctypes,os
x=ctypes.CDLL('libX11.so.6');t=ctypes.CDLL('libXtst.so.6')
x.XOpenDisplay.argtypes=[ctypes.c_char_p];x.XOpenDisplay.restype=ctypes.c_void_p
x.XFlush.argtypes=[ctypes.c_void_p];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
x.XMapRaised.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
x.XMoveResizeWindow.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_uint]
t.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
t.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
d=x.XOpenDisplay(os.environ['DISPLAY'].encode())
if not d:raise SystemExit('DISPLAY_UNAVAILABLE')
EVENTS
x.XFlush(d);x.XCloseDisplay(d)
'''.replace('EVENTS', events)
    docker('-i', CONTAINER, 'python3', '-', input=code, text=True)


def click(x, y):
    assert 0 <= x < 1280 and 0 <= y < 900
    x_events(f't.XTestFakeMotionEvent(d,-1,{int(x)},{int(y)},0)\nt.XTestFakeButtonEvent(d,1,1,0);t.XTestFakeButtonEvent(d,1,0,0)')


def screenshot():
    name = '/tmp/checkin-' + str(time.time_ns()) + '.png'
    docker(CONTAINER, 'scrot', name)
    try:
        for _ in range(20):
            r = subprocess.run(['docker', 'exec', CONTAINER, 'cat', name], capture_output=True, timeout=10)
            if r.returncode == 0 and r.stdout.startswith(b'\x89PNG'):
                return Image.open(io.BytesIO(r.stdout)).convert('RGB')
            time.sleep(.15)
        raise RuntimeError('SCREENSHOT_UNAVAILABLE')
    finally:
        subprocess.run(['docker', 'exec', CONTAINER, 'rm', '-f', '--', name], capture_output=True, timeout=10)


def find_school_logo(frame, template, left=179, top=49):
    # Recent and saved miniapps can legitimately contain the same school icon.
    # Prefer the recent row, requiring uniqueness within that row only.
    for cy in [190, 363]:
        candidates = []
        for n in range(9):
            cx = 104 + 86 * n
            crop = frame.crop((left + cx - 24, top + cy - 24, left + cx + 24, top + cy + 24))
            score = sum(ImageStat.Stat(ImageChops.difference(crop, template)).mean) / 3
            candidates.append((score, left + cx, top + cy))
        candidates.sort()
        score, x, y = candidates[0]
        if score < 15:
            return (score, x, y) if candidates[1][0] - score >= 5 else None
    return None


def wait_for_school_logo(template, timeout=30):
    deadline = time.monotonic() + timeout
    previous = None
    while True:
        match = find_school_logo(screenshot(), template)
        if match and previous and match[1:] == previous[1:]:
            return match
        previous = match
        if time.monotonic() >= deadline:
            raise RuntimeError('SCHOOL_LOGO_NOT_MATCHED')
        time.sleep(.4)


def main_windows(rows):
    return [w for w in rows if w['class'] == 'wechat' and w['instance'] == 'wechat'
            and w['width'] >= 800 and w['height'] >= 600]


def find_passwordless_entry(frame, rows, template):
    """Match only the observed native remembered-account entry button, including its text."""
    owned = [w for w in rows if w['class'] == 'wechat' and w['instance'] == 'wechat']
    if len(owned) != 1 or frame.size != (1280, 900) or template.size != (174, 36):
        return None
    w = owned[0]
    if (w['width'], w['height']) != (292, 396):
        return None
    if w['x'] < 0 or w['y'] < 0 or w['x'] + 292 > 1280 or w['y'] + 396 > 900:
        return None
    crop = frame.crop((w['x'] + 59, w['y'] + 289, w['x'] + 233, w['y'] + 325)).convert('RGB')
    template = template.convert('RGB')
    difference = ImageChops.difference(crop, template)
    score = sum(ImageStat.Stat(difference).mean) / 3
    # Check the text separately: matching a generic green login button is not enough.
    text_score = sum(ImageStat.Stat(difference.crop((44, 5, 130, 31))).mean) / 3
    if score > 2 or text_score > 2:
        return None
    return (w['id'], w['x'] + 146, w['y'] + 307)


def ensure_wechat_ready(timeout=30):
    """Click a verified remembered-account entry once; never click an authentication prompt."""
    rows = windows()
    main = main_windows(rows)
    if len(main) == 1:
        return {'passwordless_entry_clicked': False}
    template_path = Path(__file__).with_name('ui-templates') / 'enter-wechat.png'
    if not template_path.is_file():
        raise RuntimeError('AUTH_REQUIRED')
    with Image.open(template_path) as image:
        template = image.convert('RGB')
    match = find_passwordless_entry(screenshot(), rows, template)
    if match is None:
        raise RuntimeError('AUTH_REQUIRED')
    x_events(f'x.XMapRaised(d,{match[0]})')
    time.sleep(.4)
    stable = find_passwordless_entry(screenshot(), windows(), template)
    if stable != match:
        raise RuntimeError('AUTH_REQUIRED')
    time.sleep(.4)
    if find_passwordless_entry(screenshot(), windows(), template) != stable:
        raise RuntimeError('AUTH_REQUIRED')
    click(stable[1], stable[2])
    deadline = time.monotonic() + max(0, timeout)
    while True:
        main = main_windows(windows())
        if len(main) == 1:
            return {'passwordless_entry_clicked': True}
        if len(main) > 1 or time.monotonic() >= deadline:
            raise RuntimeError('AUTH_REQUIRED')
        time.sleep(.5)


def bootstrap():
    entry = ensure_wechat_ready()
    main = main_windows(windows())
    if len(main) != 1:
        raise RuntimeError('AUTH_REQUIRED')
    w = main[0]
    x_events(f"x.XMapRaised(d,{w['id']});x.XMoveResizeWindow(d,{w['id']},180,116,913,667)")
    time.sleep(.5)
    # Only the miniapp toolbar entry is clicked; no chat entry or send control is used.
    click(212, 535)
    time.sleep(1)
    choices = [w for w in windows() if w['class'] == 'WeChatAppEx' and w['width'] >= 850 and w['height'] >= 700]
    if len(choices) != 1:
        raise RuntimeError('MINIAPP_WINDOW_NOT_UNIQUE')
    w = choices[0]
    x_events(f"x.XMapRaised(d,{w['id']});x.XMoveResizeWindow(d,{w['id']},179,49,922,802)")
    time.sleep(.5)
    template = Image.open(Path(__file__).with_name('school-logo.png')).convert('RGB')
    started = time.monotonic()
    score, x, y = wait_for_school_logo(template)
    click(x, y)
    return {'bootstrap': True, 'ui_build': UI_BUILD, **entry, 'logo_match_error': round(score, 2),
            'logo_wait_seconds': round(time.monotonic() - started, 2)}
