"""Install the authorized scheduler; enable timers only after validation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

source = Path(__file__).parent
root = Path('/usr/local/lib/wechat-checkin')
marker = 'wechat-checkin:v1\n'
if root.exists():
    assert (root / 'DEPLOY_OWNER').read_text() == marker
else:
    root.mkdir(mode=0o755, parents=True)
    (root / 'DEPLOY_OWNER').write_text(marker)
files = ['checkin.py', 'ui.py', 'agent.cjs', 'cdp.cjs', 'policy.cjs', 'render_notice.py', 'health.py', 'backup.py', 'cleanup.py', 'clear_chat_records.py']
for name in files:
    shutil.copyfile(source / name, root / name)
    (root / name).chmod(0o644)
state = Path('/var/lib/wechat-checkin')
state.mkdir(mode=0o700, exist_ok=True)
state.chmod(0o700)
templates = source / 'ui-templates'
if templates.is_dir():
    target = root / 'ui-templates'
    target.mkdir(mode=0o755, exist_ok=True)
    for name in ['main-menu.png', 'storage-settings.png', 'clear-button.png', 'clear-confirm.png']:
        shutil.copyfile(templates / name, target / name)
        (target / name).chmod(0o644)
renderer = Path('/root/astrbot/data/wechat-checkin')
renderer.mkdir(mode=0o755, exist_ok=True)
shutil.copyfile(root / 'render_notice.py', renderer / 'render_notice.py')
(renderer / 'render_notice.py').chmod(0o644)
shutil.copyfile(source / 'school-logo.png', root / 'school-logo.png')
for mode, calendar in [('prepare', '*-*-* 20:58:00 Asia/Shanghai'), ('submit', '*-*-* 21:01:00 Asia/Shanghai'), ('watchdog', '*-*-* *:00/5:00 Asia/Shanghai')]:
    unit = 'wechat-checkin-' + mode
    service = f'''[Unit]
Description=WeChat check-in {mode}
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={root}
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=TZ=Asia/Shanghai
ExecStart=/usr/bin/python3 {root}/checkin.py {mode}
TimeoutStartSec=240
MemoryMax=320M
CPUQuota=70%
Nice=10
UMask=0077
NoNewPrivileges=true
'''
    timer = f'''[Unit]
Description=Schedule WeChat check-in {mode}

[Timer]
OnCalendar={calendar}
AccuracySec=1s
RandomizedDelaySec=0
Persistent=false
Unit={unit}.service

[Install]
WantedBy=timers.target
'''
    for suffix, content in [('service', service), ('timer', timer)]:
        path = Path('/etc/systemd/system') / (unit + '.' + suffix)
        if path.exists():
            assert 'WeChat check-in' in path.read_text(), 'Unowned unit name'
        path.write_text(content)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
manifest = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
previous = json.loads((state / 'deployment.json').read_text()) if (state / 'deployment.json').exists() else {}
enabled = all(subprocess.run(['systemctl', 'is-enabled', 'wechat-checkin-' + name + '.timer'], capture_output=True).returncode == 0 for name in ['prepare', 'submit', 'watchdog'])
previous.update(files=manifest, timers_enabled=enabled)
(state / 'deployment.json').write_text(json.dumps(previous, indent=2) + '\n')
print(json.dumps({'installed': True, 'timers_enabled': enabled, 'email_enabled': False}))
