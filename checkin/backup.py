"""Encrypted, bounded project backup with a brief frozen profile snapshot."""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import tarfile
import time
from urllib.parse import urlparse

import checkin

BACKUPS = Path('/var/backups/wechat-checkin')
PASSPHRASE = Path('/etc/wechat-checkin/backup-passphrase')
PAUSED = checkin.STATE / 'backup-pause.json'
MAX_BYTES = 1024**3


def command(*args):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=20, check=True)


def recover():
    marker = checkin.read(PAUSED)
    if not marker:
        return
    data = json.loads(command('docker', 'inspect', 'wechat-web').stdout)[0]
    if data['Id'] != marker.get('container_id'):
        raise RuntimeError('RECOVERY_CONTAINER_CHANGED')
    if data['State']['Paused']:
        command('docker', 'unpause', 'wechat-web')
    PAUSED.unlink(missing_ok=True)


def excluded(info):
    # The decryption key is deliberately stored separately from the archive.
    if info.name.endswith('/backup-passphrase') or '/gnupg/' in info.name:
        return None
    if info.name.endswith(('/db_storage/message', '/db_storage/session', '/msg')) or '/db_storage/message/' in info.name or '/db_storage/session/' in info.name:
        return None
    if (info.name.endswith('.png') and not info.name.endswith('/school-logo.png') and '/ui-templates/' not in info.name) or info.name.endswith(('.log', '.log.1')) or '/probe-artifacts/' in info.name or '/.git/' in info.name:
        return None
    return info


def bounds():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))


def interrupted(*_):
    raise RuntimeError('BACKUP_INTERRUPTED')


def perform():
    stamp = checkin.now().strftime('%Y%m%dT%H%M%S%z')
    output = BACKUPS / ('wechat-checkin-' + stamp + '.tar.gz.gpg')
    partial = output.with_suffix('.partial')
    if shutil.disk_usage('/').free < 2 * 1024**3:
        raise RuntimeError('BACKUP_DISK_LOW')
    client = checkin.container()
    assert not client['State']['Paused'], 'CONTAINER_ALREADY_PAUSED'
    volume = json.loads(command('docker', 'volume', 'inspect', 'wechat-profile').stdout)[0]
    docker_root = Path(json.loads(command('docker', 'info', '--format', '{{json .DockerRootDir}}').stdout)).resolve()
    profile = Path(volume['Mountpoint']).resolve()
    assert profile.is_relative_to(docker_root / 'volumes') and profile.name == '_data'
    assert any(m.get('Name') == volume['Name'] and m['Destination'] == '/home/wechat' for m in client['Mounts'])
    assert (Path('/usr/local/lib/wechat-checkin/DEPLOY_OWNER')).read_text() == 'wechat-checkin:v1\n'
    host = urlparse(checkin.read(checkin.CONFIG)['manage_url']).hostname
    assert host and '/' not in host
    paths = [
        '/etc/wechat-checkin', '/etc/wechat-web', '/usr/local/lib/wechat-checkin', '/var/lib/wechat-checkin',
        '/opt/uestc-wechat/desktop', '/opt/uestc-wechat/runtime',
        '/etc/nginx/sites-available/checkin', '/etc/nginx/snippets/wechat-ssl.conf', '/etc/nginx/snippets/wechat-proxy.conf',
        f'/etc/letsencrypt/live/{host}', f'/etc/letsencrypt/archive/{host}',
        f'/etc/letsencrypt/renewal/{host}.conf', '/etc/logrotate.d/wechat-web',
        '/root/astrbot/data/wechat-checkin', '/root/astrbot/data/render_theme',
    ]
    paths.extend(str(p) for p in Path('/etc/systemd/system').glob('wechat-checkin-*') if p.is_file())
    pause_seconds = 0
    process = None
    try:
        with partial.open('wb') as encrypted:
            process = subprocess.Popen(['gpg', '--homedir', '/etc/wechat-checkin/gnupg', '--batch', '--yes',
                '--pinentry-mode', 'loopback', '--passphrase-file', str(PASSPHRASE), '--no-symkey-cache',
                '--symmetric', '--cipher-algo', 'AES256', '--compress-algo', 'none', '--output', '-'],
                stdin=subprocess.PIPE, stdout=encrypted, stderr=subprocess.DEVNULL, preexec_fn=bounds)
            with tarfile.open(fileobj=process.stdin, mode='w|gz', compresslevel=1) as archive:
                checkin.save(PAUSED, {'container_id': client['Id'], 'started_at': checkin.now().isoformat()})
                start = time.monotonic()
                try:
                    command('docker', 'pause', 'wechat-web')
                    archive.add(profile, arcname='wechat-profile', filter=excluded)
                finally:
                    recover()
                    pause_seconds = round(time.monotonic() - start, 2)
                checkin.event('backup_profile_snapshotted', paused_seconds=pause_seconds)
                for item in sorted(set(paths)):
                    path = Path(item)
                    if path.exists():
                        archive.add(path, arcname='host' + str(path), filter=excluded)
            process.stdin.close()
            if process.wait(timeout=45) != 0:
                raise RuntimeError('ENCRYPTION_FAILED')
            encrypted.flush()
            os.fsync(encrypted.fileno())
        partial.rename(output)
        output.chmod(0o600)
        # Only this tool's named encrypted archives are pruned; no Docker cleanup is performed.
        retained = sorted(BACKUPS.glob('wechat-checkin-*.tar.gz.gpg'), reverse=True)
        for old in retained[2:]:
            assert old.parent.resolve() == BACKUPS.resolve() and not old.is_symlink()
            old.unlink()
        return {'status': 'success', 'timestamp': time.time(), 'time': checkin.now().isoformat(),
                'archive': str(output), 'bytes': output.stat().st_size, 'profile_pause_seconds': pause_seconds,
                'retained_archives': min(len(retained), 2), 'decryption_key_stored_separately': True}
    except BaseException:
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        partial.unlink(missing_ok=True)
        raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['run', 'recover'], default='run', nargs='?')
    args = parser.parse_args()
    if args.action == 'recover':
        recover()
        return
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with (checkin.STATE / 'run.lock').open('a') as lock:
        checkin.maintenance_attempt('backup', 'waiting')
        if not checkin.acquire_lock(lock, wait_seconds=30):
            checkin.defer_maintenance('backup', 'busy')
        try:
            recover()
            current = checkin.now().strftime('%H:%M')
            if '20:50' <= current < '23:00':
                today = checkin.read(checkin.STATE / (checkin.now().date().isoformat() + '.json'))
                if today.get('outcome') not in {'success', 'already_done', 'exempt'}:
                    checkin.defer_maintenance('backup', 'checkin_window')
            result = perform()
            checkin.save(checkin.STATE / 'last-backup.json', result)
            checkin.maintenance_attempt('backup', 'success')
            checkin.event('backup_complete', **result)
        except Exception as error:
            code = str(error) if isinstance(error, RuntimeError) else 'BACKUP_FAILED'
            checkin.save(checkin.STATE / 'last-backup.json', {'status': 'failed', 'timestamp': time.time(), 'error': code})
            checkin.maintenance_attempt('backup', 'failed', error=code)
            checkin.event('backup_failed', code=code)
            raise SystemExit(1) from None
        finally:
            recover()


if __name__ == '__main__':
    main()
