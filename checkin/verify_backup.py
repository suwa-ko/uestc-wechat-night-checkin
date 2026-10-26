"""Check decryption integrity and restore a script in memory, never over live data."""
import argparse
import hashlib
from pathlib import Path
import json
import subprocess
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('archive')
parser.add_argument('--profile', action='store_true')
args = parser.parse_args()
path = Path(args.archive).resolve()
assert path.parent == Path('/var/backups/wechat-checkin') and path.name.endswith('.tar.gz.gpg')
process = subprocess.Popen(['gpg', '--homedir', '/etc/wechat-checkin/gnupg', '--batch', '--yes', '--pinentry-mode', 'loopback',
    '--passphrase-file', '/etc/wechat-checkin/backup-passphrase', '--no-symkey-cache', '--decrypt', str(path)],
    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
count = 0
profile = config = logo = False
script_hash = None
try:
    with tarfile.open(fileobj=process.stdout, mode='r|gz') as archive:
        for item in archive:
            count += 1
            assert not item.name.endswith('/backup-passphrase'), 'Decryption key leaked into archive'
            profile |= item.name.startswith('wechat-profile/')
            config |= item.name == 'host/etc/wechat-checkin/config.json'
            logo |= item.name == 'host/usr/local/lib/wechat-checkin/school-logo.png'
            if item.name == 'host/usr/local/lib/wechat-checkin/checkin.py':
                script_hash = hashlib.sha256(archive.extractfile(item).read()).hexdigest()
    while process.stdout.read(1024 * 1024):
        pass
    assert process.wait(timeout=30) == 0, 'GPG integrity check failed'
    expected = hashlib.sha256(Path('/usr/local/lib/wechat-checkin/checkin.py').read_bytes()).hexdigest()
    assert config and logo and script_hash == expected
    assert not args.profile or profile
    print(json.dumps({'decryption_integrity_verified': True, 'member_count': count, 'profile_included': profile,
                      'configuration_present': config, 'automation_template_present': logo, 'script_restore_hash_matches': True,
                      'live_data_overwritten': False}))
finally:
    if process.poll() is None:
        process.kill(); process.wait(timeout=10)
