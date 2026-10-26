"""Install the daily cache cleanup without restarting WeChat."""
from pathlib import Path
import subprocess

root = Path('/usr/local/lib/wechat-checkin')
assert (root / 'DEPLOY_OWNER').read_text() == 'wechat-checkin:v1\n'
service = f'''[Unit]
Description=WeChat check-in local chat history and aged cache cleanup
After=docker.service
StartLimitIntervalSec=30min
StartLimitBurst=4

[Service]
Type=oneshot
Restart=on-failure
RestartPreventExitStatus=1 2 SIGTERM SIGKILL SIGSEGV SIGABRT SIGBUS SIGILL SIGFPE
RestartSec=60s
WorkingDirectory={root}
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=TZ=Asia/Shanghai
ExecStart=/usr/bin/python3 {root}/cleanup.py run
TimeoutStartSec=180
MemoryMax=128M
CPUQuota=25%
Nice=15
IOWeight=20
UMask=0077
NoNewPrivileges=true
'''
timer = '''[Unit]
Description=Schedule WeChat check-in local chat history and aged cache cleanup

[Timer]
OnCalendar=*-*-* 04:50:00 Asia/Shanghai
AccuracySec=1m
Persistent=true
Unit=wechat-checkin-cleanup.service

[Install]
WantedBy=timers.target
'''
for suffix, text in [('service', service), ('timer', timer)]:
    p = Path('/etc/systemd/system/wechat-checkin-cleanup.' + suffix)
    if p.exists():
        assert 'WeChat check-in' in p.read_text()
    p.write_text(text)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'wechat-checkin-cleanup.timer'], check=True, capture_output=True)
print('Aged cache cleanup enabled daily at 04:50 Asia/Shanghai.')
