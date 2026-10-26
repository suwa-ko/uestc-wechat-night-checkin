"""Initialize a new reference deployment without copying anybody's account data."""
import json
import os
from pathlib import Path
import shutil
import subprocess

base = Path('/opt/uestc-wechat')
assert os.geteuid() == 0, 'Run with sudo'
assert Path(__file__).resolve().parents[1] == base, 'Clone this repository into /opt/uestc-wechat first'
for directory, name, value in [
    ('desktop', 'DEPLOY_OWNER', 'wechat-web:v1\n'),
    ('runtime', 'PROBE_OWNER', 'uestc-wechat-runtime:v1\n'),
]:
    target = base / directory / name
    if target.exists():
        assert target.read_text() == value, 'Existing deployment has a different owner'
    else:
        target.write_text(value)
for directory in ['/etc/wechat-checkin', '/etc/wechat-web', '/var/lib/wechat-checkin']:
    Path(directory).mkdir(mode=0o700, exist_ok=True)
config = Path('/etc/wechat-checkin/config.json')
if not config.exists():
    shutil.copyfile(base / 'examples/config.example.json', config)
    config.chmod(0o600)
volume = subprocess.run(['docker', 'volume', 'inspect', 'wechat-profile'], capture_output=True, text=True)
if volume.returncode == 0:
    assert json.loads(volume.stdout)[0].get('Labels', {}).get('io.github.uestc-wechat.owner') == 'v1', 'Refusing an unowned existing profile volume'
else:
    subprocess.run(['docker', 'volume', 'create', '--label', 'io.github.uestc-wechat.owner=v1', 'wechat-profile'], check=True)
print('Layout ready. Fill in /etc/wechat-checkin/config.json before installing timers.')
