"""Check deployment inputs without logging private values or submitting anything."""
import json
import math
import platform
from pathlib import Path

assert platform.machine() == 'x86_64', 'Only Linux x86_64 has been validated'
config = json.loads(Path('/etc/wechat-checkin/config.json').read_text())
assert config['timezone'] == 'Asia/Shanghai'
point = config['location']
assert point['coordinate_system'] == 'WGS84'
lat, lon = point['latitude'], point['longitude']
gcj = point['gcj02']
assert all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in [lat, lon, *gcj]), 'Fill all coordinates yourself'
assert len(gcj) == 2 and abs(lat) <= 90 and abs(lon) <= 180 and abs(gcj[0]) <= 180 and abs(gcj[1]) <= 90
assert (lat, lon) != (0, 0), 'Example coordinates cannot be used'
assert config['astrbot']['umo'] and 'YOUR_' not in config['astrbot']['umo'], 'Configure your own private QQ target'
assert Path(config['astrbot']['key_file']).is_file(), 'Create a dedicated AstrBot IM key file'
assert Path('/opt/uestc-wechat/runtime/wmpf-debugger/prepared.json').is_file(), 'Prepare the pinned WMPF runtime first'
print('Static preflight passed. Next run a non-submitting dry-run before enabling timers.')
