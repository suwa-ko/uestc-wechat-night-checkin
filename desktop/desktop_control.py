"""Operate the owned X11 desktop and fetch a newly generated screenshot."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('--click', nargs=2, type=int)
parser.add_argument('--scroll', type=int)
args = parser.parse_args()
container = 'wechat-web'
info = json.loads(subprocess.check_output(['docker', 'inspect', container]))[0]
assert info['Config']['Labels']['io.github.uestc-wechat.desktop'] == 'v1'
if args.click or args.scroll:
    x, y = args.click or (640, 650)
    assert 0 <= x < 1280 and 0 <= y < 900
    code = '''import ctypes,os
x=ctypes.CDLL('libX11.so.6');t=ctypes.CDLL('libXtst.so.6')
x.XOpenDisplay.argtypes=[ctypes.c_char_p];x.XOpenDisplay.restype=ctypes.c_void_p
x.XFlush.argtypes=[ctypes.c_void_p];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
t.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
t.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
d=x.XOpenDisplay(os.environ['DISPLAY'].encode())
if not d:raise SystemExit('Display unavailable')
POINT
x.XFlush(d);x.XCloseDisplay(d)
'''
    events = f't.XTestFakeMotionEvent(d,-1,{x},{y},0)\n'
    if args.click:
        events += 't.XTestFakeButtonEvent(d,1,1,0);t.XTestFakeButtonEvent(d,1,0,0)'
    else:
        assert abs(args.scroll) <= 10
        button = 5 if args.scroll > 0 else 4
        events += '\n'.join(f't.XTestFakeButtonEvent(d,{button},1,0);t.XTestFakeButtonEvent(d,{button},0,0)' for _ in range(abs(args.scroll)))
    code = code.replace('POINT', events)
    subprocess.run(['docker', 'exec', '-i', container, 'python3', '-'],
                   input=code, text=True, check=True, capture_output=True)
    time.sleep(1)
filename = '/tmp/desktop-' + str(time.time_ns()) + '.png'
subprocess.run(['docker', 'exec', container, 'scrot', filename], check=True, capture_output=True)
for attempt in range(20):
    result = subprocess.run(['docker', 'exec', container, 'cat', filename], capture_output=True)
    if result.returncode == 0 and result.stdout.startswith(b'\x89PNG'):
        target = Path('/opt/uestc-wechat/desktop/desktop-fresh.png')
        target.write_bytes(result.stdout)
        os.chown(target, 1000, 1000)
        target.chmod(0o600)
        print(json.dumps({'screenshot': str(target), 'bytes': len(result.stdout), 'clicked': args.click}))
        break
    time.sleep(.25)
else:
    raise SystemExit('Screenshot not readable')
