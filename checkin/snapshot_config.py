"""Small encrypted source/configuration snapshot for an off-server copy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from urllib.parse import urlparse

sys.path.insert(0, '/usr/local/lib/wechat-checkin')
import backup
import checkin

os.umask(0o077)
stamp = checkin.now().strftime('%Y%m%dT%H%M%S%z')
output = backup.BACKUPS / ('config-snapshot-' + stamp + '.tar.gz.gpg')
partial = output.with_suffix('.partial')
host = urlparse(checkin.read(checkin.CONFIG)['manage_url']).hostname
assert host and '/' not in host
paths = ['/etc/wechat-checkin', '/etc/wechat-web', '/usr/local/lib/wechat-checkin', '/var/lib/wechat-checkin',
         '/opt/uestc-wechat/desktop', '/opt/uestc-wechat/checkin',
         '/etc/nginx/sites-available/checkin', '/etc/nginx/snippets/wechat-ssl.conf', '/etc/nginx/snippets/wechat-proxy.conf',
         f'/etc/letsencrypt/live/{host}', f'/etc/letsencrypt/archive/{host}',
         f'/etc/letsencrypt/renewal/{host}.conf', '/etc/logrotate.d/wechat-web']
probe = Path('/opt/uestc-wechat/runtime')
paths.extend(str(p) for p in probe.iterdir() if p.is_file() and p.suffix in {'.py', '.sh', '.md', '.json'})
paths.append(str(probe / 'Dockerfile'))
prepared = checkin.read(probe / 'wmpf-debugger/prepared.json')
paths.append(str(probe / 'wmpf-debugger/prepared.json'))
paths.extend(str(p) for p in Path(prepared['source_dir']).iterdir() if p.name not in {'node_modules', '.git', '.yarn'})
paths.extend(str(p) for p in Path('/etc/systemd/system').glob('wechat-checkin-*') if p.is_file())
process = None
try:
    with partial.open('wb') as encrypted:
        process = subprocess.Popen(['gpg', '--homedir', '/etc/wechat-checkin/gnupg', '--batch', '--yes',
            '--pinentry-mode', 'loopback', '--passphrase-file', str(backup.PASSPHRASE), '--no-symkey-cache',
            '--symmetric', '--cipher-algo', 'AES256', '--compress-algo', 'none', '--output', '-'],
            stdin=subprocess.PIPE, stdout=encrypted, stderr=subprocess.DEVNULL)
        with tarfile.open(fileobj=process.stdin, mode='w|gz', compresslevel=1) as archive:
            for name in sorted(set(paths)):
                path = Path(name)
                if path.exists():
                    archive.add(path, arcname='host' + str(path), filter=backup.excluded)
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise RuntimeError('CONFIG_ENCRYPTION_FAILED')
        encrypted.flush(); os.fsync(encrypted.fileno())
    partial.rename(output)
    output.chmod(0o600)
    print(json.dumps({'archive': str(output), 'bytes': output.stat().st_size, 'scope': 'configuration_and_source_only', 'profile_included': False}))
except BaseException:
    if process and process.poll() is None:
        process.kill(); process.wait(timeout=10)
    partial.unlink(missing_ok=True)
    raise
