"""Pull encrypted project backups to the user's Windows backup directory."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

OWNER = 'wechat-checkin-backups:v1'
FULL = re.compile(r'wechat-checkin-\d{8}T\d{6}\+0800\.tar\.gz\.gpg')
CONFIG = re.compile(r'config-snapshot-\d{8}T\d{6}\+0800\.tar\.gz\.gpg')
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', 'wechat-host']


def save(root, data):
    temp = root / 'sync-status.tmp'
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, root / 'sync-status.json')


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def manifest():
    code = '''import pathlib,re,json,hashlib
root=pathlib.Path('/var/backups/wechat-checkin')
full=sorted([p for p in root.iterdir() if re.fullmatch(r'wechat-checkin-\\d{8}T\\d{6}\\+0800\\.tar\\.gz\\.gpg',p.name)])[-2:]
config=sorted([p for p in root.iterdir() if re.fullmatch(r'config-snapshot-\\d{8}T\\d{6}\\+0800\\.tar\\.gz\\.gpg',p.name)])[-1:]
out=[]
for p in full+config:
 assert p.parent.resolve()==root and not p.is_symlink()
 with p.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
 out.append({'name':p.name,'bytes':p.stat().st_size,'sha256':sha})
print(json.dumps(out))
'''
    r = subprocess.run(SSH + ['sudo -n python3 -'], input=code.encode(), capture_output=True, timeout=120)
    if r.returncode:
        raise RuntimeError('REMOTE_MANIFEST_FAILED')
    items = json.loads(r.stdout)
    for item in items:
        if not (FULL.fullmatch(item['name']) or CONFIG.fullmatch(item['name'])) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise RuntimeError('INVALID_MANIFEST')
    return items


def pull(root, item):
    target = root / item['name']
    partial = root / (item['name'] + '.partial')
    if target.is_symlink() or partial.is_symlink() or target.resolve().parent != root or partial.resolve().parent != root:
        raise RuntimeError('UNSAFE_LOCAL_BACKUP_PATH')
    if target.exists() and target.stat().st_size == item['bytes'] and digest(target) == item['sha256']:
        return False
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > item['bytes']:
        raise RuntimeError('INVALID_PARTIAL_SIZE')
    if shutil.disk_usage(root).free < item['bytes'] - offset + 256 * 1024**2:
        raise RuntimeError('LOCAL_DISK_LOW')
    remote = '/var/backups/wechat-checkin/' + item['name']
    command = 'sudo -n tail -c +' + str(offset + 1) + ' -- ' + shlex.quote(remote)
    process = subprocess.Popen(SSH + [command], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    transferred = offset
    last_update = 0
    try:
        with partial.open('ab') as output:
            while data := process.stdout.read(1024 * 1024):
                output.write(data)
                transferred += len(data)
                if time.monotonic() - last_update >= 5:
                    save(root, {'status': 'downloading', 'file': item['name'], 'bytes': transferred,
                                'total': item['bytes'], 'updated_at': datetime.now().isoformat()})
                    last_update = time.monotonic()
            output.flush(); os.fsync(output.fileno())
        if process.wait(timeout=20) != 0 or transferred != item['bytes']:
            raise RuntimeError('DOWNLOAD_INTERRUPTED_RESUME_AVAILABLE')
        if digest(partial) != item['sha256']:
            assert partial.resolve().is_relative_to(root)
            partial.unlink()
            raise RuntimeError('BACKUP_HASH_MISMATCH')
        os.replace(partial, target)
        return True
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)


def acknowledge(root, item):
    payload = {'archive': item['name'], 'bytes': item['bytes'], 'sha256': item['sha256'],
               'local_path': str(root / item['name'])}
    code = '''import json,re,sys
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/wechat-checkin')
import checkin
assert (checkin.ROOT/'DEPLOY_OWNER').read_text()=='wechat-checkin:v1\\n'
payload = json.loads(PAYLOAD)
assert re.fullmatch(r'wechat-checkin-\\d{8}T\\d{6}\\+0800\\.tar\\.gz\\.gpg', payload['archive'])
assert re.fullmatch(r'[0-9a-f]{64}',payload['sha256'])
path=Path('/var/backups/wechat-checkin')/payload['archive']
assert not path.is_symlink() and path.is_file() and path.stat().st_size==payload['bytes']
payload.update(status='success',time=checkin.now().isoformat())
checkin.save(checkin.STATE/'local-sync.json',payload)
'''.replace('PAYLOAD', repr(json.dumps(payload)))
    result = subprocess.run(SSH + ['sudo -n python3 -'], input=code.encode(), capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('REMOTE_SYNC_ACK_FAILED')


def run(root, quiet):
    root = root.resolve()
    if json.loads((root / 'backup-target.json').read_text(encoding='utf-8-sig'))['owner'] != OWNER:
        raise RuntimeError('UNOWNED_BACKUP_DIRECTORY')
    # Task Scheduler also uses IgnoreNew; this lock covers manual concurrent launches.
    import msvcrt
    with (root / 'sync.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        try:
            save(root, {'status': 'checking', 'updated_at': datetime.now().isoformat()})
            items = manifest()
            if not any(FULL.fullmatch(i['name']) for i in items):
                catalog = json.loads((root / 'archive-catalog.json').read_text()) if (root / 'archive-catalog.json').exists() else {}
                local_valid = any(FULL.fullmatch(name) and (root / name).is_file() and digest(root / name) == info.get('sha256') for name, info in catalog.items())
                if not local_valid:
                    raise RuntimeError('NO_FULL_BACKUP_ON_SERVER')
            secret = subprocess.run(SSH + ['sudo -n cat /etc/wechat-checkin/backup-passphrase'], capture_output=True, timeout=30)
            if secret.returncode or not 32 <= len(secret.stdout.strip()) <= 128:
                raise RuntimeError('BACKUP_KEY_FETCH_FAILED')
            key = root / 'backup-passphrase.txt'
            if key.exists() and key.read_bytes().strip() != secret.stdout.strip():
                previous = root / ('backup-passphrase-previous-' + datetime.now().strftime('%Y%m%dT%H%M%S') + '.txt')
                shutil.copyfile(key, previous)
            key.write_bytes(secret.stdout)
            downloaded = []
            for item in items:
                if pull(root, item):
                    downloaded.append(item['name'])
            catalog_file = root / 'archive-catalog.json'
            catalog = json.loads(catalog_file.read_text()) if catalog_file.exists() else {}
            for item in items:
                catalog[item['name']] = {'bytes': item['bytes'], 'sha256': item['sha256'], 'verified_at': datetime.now().isoformat()}
            catalog_file.write_text(json.dumps(catalog, indent=2), encoding='utf-8')
            # Retain seven full backups on the PC. Only owned, validated archive names are eligible.
            for old in sorted((p for p in root.iterdir() if FULL.fullmatch(p.name)), reverse=True)[7:]:
                assert old.resolve().parent == root and not old.is_symlink()
                old.unlink()
            latest_config = {i['name'] for i in items if CONFIG.fullmatch(i['name'])}
            for old in root.iterdir():
                if latest_config and CONFIG.fullmatch(old.name) and old.name not in latest_config:
                    assert old.resolve().parent == root and not old.is_symlink()
                    old.unlink()
            full = [item for item in items if FULL.fullmatch(item['name'])]
            if full:
                acknowledge(root, max(full, key=lambda item: item['name']))
            result = {'status': 'success', 'completed_at': datetime.now().isoformat(), 'downloaded': downloaded,
                      'verified_archives': [i['name'] for i in items], 'sha256_verified': True,
                      'server_acknowledged': bool(full), 'local_retention': 7}
            save(root, result)
            if not quiet:
                print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(r'D:\backups\wechat-checkin'))
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    try:
        run(args.root, args.quiet)
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        if args.root.is_dir():
            save(args.root, {'status': 'failed', 'error': code, 'updated_at': datetime.now().isoformat()})
        if not args.quiet:
            print(json.dumps({'status': 'failed', 'error': code}), flush=True)
        sys.exit(1)
