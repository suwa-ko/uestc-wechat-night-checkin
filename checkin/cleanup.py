"""Prune only old disposable cache files inside the verified WeChat volume."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import time

import checkin

DAY = 86400


def roots(profile):
    profile = profile.resolve()
    items = []
    users = profile / 'xwechat_files'
    if users.is_dir() and not users.is_symlink():
        for account in users.iterdir():
            if account.name == 'all_users' or not account.is_dir() or account.is_symlink():
                continue
            items.extend([(account / 'cache', 'chat_cache', 7 * DAY), (account / 'temp', 'temporary_files', 2 * DAY)])
    for name in ['completed', 'pending', 'attachments', 'new', 'records']:
        items.append((profile / '.xwechat/crashinfo' / name, 'crash_reports', 7 * DAY))
    items.append((profile / '.cache/mesa_shader_cache', 'shader_cache', 30 * DAY))
    return [(p, label, age) for p, label, age in items if p.is_dir() and not p.is_symlink() and p.resolve().is_relative_to(profile)]


def protected(path):
    name = path.name.lower()
    return (name.endswith(('.db', '.sqlite', '.sqlite3', '.mdb', '-wal', '-shm', '.wxapkg', '.so', '.node', '.pak'))
            or any(word in name for word in ['cookie', 'login', 'token', 'session', 'preferences', 'local state']))


def candidates(profile, moment):
    result = []
    for base, label, age in roots(profile):
        for current, directories, files in os.walk(base, followlinks=False):
            directory = Path(current)
            directories[:] = [name for name in directories if not (directory / name).is_symlink()]
            for name in files:
                path = directory / name
                if protected(path) or path.is_symlink():
                    continue
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(info.st_mode) and moment - info.st_mtime >= age:
                    result.append((path, base, label, age, info.st_size, info.st_dev, info.st_ino))
    return result


def clean(profile, moment, dry):
    profile = profile.resolve()
    removed = removed_bytes = 0
    eligible = candidates(profile, moment)
    totals = {}
    for path, base, label, age, size, device, inode in eligible:
        totals[label] = totals.get(label, 0) + size
        if dry:
            continue
        # Revalidate immediately before each unlink; never recursively delete directories.
        if not path.resolve().is_relative_to(base.resolve()) or not base.resolve().is_relative_to(profile) or path.is_symlink() or protected(path):
            continue
        try:
            current = path.lstat()
            if (current.st_dev, current.st_ino) != (device, inode) or moment - current.st_mtime < age:
                continue
            path.unlink()
            removed += 1
            removed_bytes += size
        except FileNotFoundError:
            pass
    return {'status': 'success', 'dry_run': dry, 'candidate_files': len(eligible), 'candidate_bytes': sum(x[4] for x in eligible),
            'categories_bytes': totals, 'removed_files': removed, 'removed_bytes': removed_bytes,
            'login_data_preserved': True, 'chat_databases_preserved': True, 'miniapp_runtime_preserved': True}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['preview', 'run'])
    args = parser.parse_args()
    dry = args.action == 'preview'
    with (checkin.STATE / 'run.lock').open('a') as lock:
        if not dry:
            checkin.maintenance_attempt('cleanup', 'waiting')
        if not checkin.acquire_lock(lock, wait_seconds=0 if dry else 30):
            if dry:
                checkin.event('cleanup_preview_busy')
                return
            checkin.defer_maintenance('cleanup', 'busy')
        try:
            data = checkin.container()
            if data['State']['Paused']:
                if dry:
                    checkin.event('cleanup_preview_paused')
                    return
                checkin.defer_maintenance('cleanup', 'paused')
            if not dry:
                backup = checkin.read(checkin.STATE / 'last-backup.json')
                if backup.get('status') != 'success' or time.time() - backup.get('timestamp', 0) > 36 * 3600:
                    checkin.defer_maintenance('cleanup', 'backup_required')
                if '20:50' <= checkin.now().strftime('%H:%M') < '23:05':
                    today = checkin.read(checkin.STATE / (checkin.now().date().isoformat() + '.json'))
                    if today.get('outcome') not in {'success', 'already_done', 'exempt'}:
                        checkin.defer_maintenance('cleanup', 'checkin_window')
            volume = json.loads(subprocess.check_output(['docker', 'volume', 'inspect', 'wechat-profile']))[0]
            root = Path(volume['Mountpoint']).resolve()
            docker_root = Path(json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .DockerRootDir}}']))).resolve()
            assert root.is_relative_to(docker_root / 'volumes') and root.name == '_data'
            assert any(m.get('Name') == volume['Name'] and m['Destination'] == '/home/wechat' for m in data['Mounts'])
            native = {}
            if not dry:
                import clear_chat_records
                native = clear_chat_records.perform()
            result = clean(root, time.time(), dry)
            result.update(native)
            result['time'] = checkin.now().isoformat()
            if not dry:
                checkin.save(checkin.STATE / 'last-cleanup.json', result)
                checkin.maintenance_attempt('cleanup', 'success')
            checkin.event('cache_cleanup', **result)
        except Exception as error:
            code = str(error) if isinstance(error, RuntimeError) else type(error).__name__
            if not code.replace('_', '').isalnum() or len(code) > 100:
                code = 'CACHE_CLEANUP_FAILED'
            if not dry:
                checkin.save(checkin.STATE / 'last-cleanup.json', {'status': 'failed', 'time': checkin.now().isoformat(), 'error': code})
                checkin.maintenance_attempt('cleanup', 'failed', error=code)
            checkin.event('cache_cleanup_failed', code=code)
            raise SystemExit(1) from None


if __name__ == '__main__':
    main()
