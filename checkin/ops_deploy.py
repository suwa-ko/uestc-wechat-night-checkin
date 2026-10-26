"""Install persistence safeguards without restarting the live WeChat session."""
import json
import os
from pathlib import Path
import secrets
import subprocess

os.umask(0o077)
root = Path('/usr/local/lib/wechat-checkin')
assert (root / 'DEPLOY_OWNER').read_text() == 'wechat-checkin:v1\n'
private = Path('/etc/wechat-checkin')
key = private / 'backup-passphrase'
if not key.exists():
    key.write_text(secrets.token_urlsafe(48) + '\n')
key.chmod(0o600)
(private / 'gnupg').mkdir(mode=0o700, exist_ok=True)
backups = Path('/var/backups/wechat-checkin')
backups.mkdir(mode=0o700, exist_ok=True)
backups.chmod(0o700)
service = f'''[Unit]
Description=WeChat check-in encrypted project backup
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
ExecStart=/usr/bin/python3 {root}/backup.py run
ExecStopPost=/usr/bin/python3 {root}/backup.py recover
TimeoutStartSec=600
TimeoutStopSec=30
MemoryMax=320M
CPUQuota=70%
Nice=15
IOWeight=20
UMask=0077
NoNewPrivileges=true
'''
timer = '''[Unit]
Description=Schedule WeChat check-in encrypted backup

[Timer]
OnCalendar=*-*-* 04:20:00 Asia/Shanghai
AccuracySec=1m
Persistent=true
Unit=wechat-checkin-backup.service

[Install]
WantedBy=timers.target
'''
for suffix, text in [('service', service), ('timer', timer)]:
    p = Path('/etc/systemd/system/wechat-checkin-backup.' + suffix)
    if p.exists():
        assert 'WeChat check-in' in p.read_text()
    p.write_text(text)
volume = json.loads(subprocess.check_output(['docker', 'volume', 'inspect', 'wechat-profile']))[0]
logroot = Path(volume['Mountpoint']).resolve() / 'probe-artifacts'
assert logroot.is_dir() and logroot.is_relative_to('/var/lib/docker/volumes')
logfile = Path('/etc/logrotate.d/wechat-web')
if logfile.exists():
    assert '# wechat-web persistence' in logfile.read_text()
logfile.write_text(f'''# wechat-web persistence
{logroot}/*.log /opt/uestc-wechat/runtime/wmpf-debugger/debugger.log {{
    daily
    maxsize 5M
    rotate 3
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su root root
}}
''')
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'wechat-checkin-backup.timer'], check=True, capture_output=True)
print(json.dumps({'backup_timer_enabled': True, 'backup_time_beijing': '04:20', 'retention': 2,
                  'encrypted': True, 'archive_limit_bytes': 1024**3, 'login_session_restarted': False}))
