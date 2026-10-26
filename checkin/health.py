"""Quiet, deduplicated health alerts for the project's existing watchdog."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import checkin


def timestamp(record):
    try:
        if 'timestamp' in record:
            return float(record['timestamp'])
        value = datetime.fromisoformat(record['time'])
        return value.replace(tzinfo=checkin.TZ).timestamp() if value.tzinfo is None else value.timestamp()
    except (KeyError, TypeError, ValueError, OverflowError):
        return 0


def maintenance_issues(backup, cleanup, sync, attempts, moment):
    issues = []
    if cleanup.get('status') == 'failed':
        issues.append(('cache_cleanup_failed', '最近一次聊天记录/缓存清理失败，请检查服务器微信是否解锁'))
    elif cleanup.get('status') != 'success' or not cleanup.get('chat_records_cleared'):
        issues.append(('cache_cleanup_missing', '尚无已确认完成聊天清空的记录'))
    elif moment - timestamp(cleanup) > 36 * 3600:
        issues.append(('cache_cleanup_stale', '聊天记录清理已超过36小时未成功完成，可能因跳过或定时任务异常而漏跑'))
    if backup.get('status') == 'failed':
        issues.append(('backup_failed', '最近一次加密备份失败：' + checkin.sanitize(backup.get('error', 'BACKUP_FAILED'))))
    elif backup.get('status') != 'success':
        issues.append(('backup_missing', '尚无成功的加密备份记录'))
    elif moment - timestamp(backup) > 36 * 3600:
        issues.append(('backup_stale', '加密备份已超过36小时未成功更新'))
    if backup.get('status') == 'success':
        latest = Path(backup.get('archive', '')).name
        # Give the PC its morning schedule and a reasonable opportunity to log in.
        if latest and sync.get('archive') != latest and moment - timestamp(backup) > 12 * 3600:
            issues.append(('backup_sync_lag', '最新备份生成已超过12小时，尚未收到D盘校验成功回执；请检查电脑是否开机、登录及同步任务'))
        elif sync.get('archive') == latest and moment - timestamp(sync) > 36 * 3600:
            issues.append(('backup_sync_stale', 'D盘备份同步已超过36小时未确认成功，请检查本地同步任务'))
    for job, record in attempts.items():
        if record.get('status') in {'waiting', 'deferred'} and moment - timestamp(record) > 15 * 60:
            label = '备份' if job == 'backup' else '聊天清理'
            issues.append((job + '_retry_exhausted', label + '任务等待或补跑超过15分钟仍未完成，请检查锁和服务状态'))
    return issues


def collect():
    issues = []
    for name, label in [('wechat-web', '云端微信'), ('astrbot', 'AstrBot'), ('napcat', 'QQ 机器人')]:
        r = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True, timeout=12)
        try:
            data = json.loads(r.stdout)[0]
            if not data['State']['Running']:
                issues.append((name + '_stopped', label + '容器未运行'))
            elif data['State'].get('Health', {}).get('Status') == 'unhealthy':
                issues.append((name + '_unhealthy', label + '健康检查失败'))
            if name == 'wechat-web' and not any(m.get('Name') == 'wechat-profile' and m['Destination'] == '/home/wechat' for m in data['Mounts']):
                issues.append(('profile_mount', '微信登录资料卷挂载不符'))
        except (ValueError, IndexError, KeyError):
            issues.append((name + '_missing', label + '容器不可用'))
    units = ['nginx.service', 'wechat-checkin-prepare.timer', 'wechat-checkin-submit.timer', 'wechat-checkin-backup.timer']
    if Path('/etc/systemd/system/wechat-checkin-cleanup.timer').exists():
        units.append('wechat-checkin-cleanup.timer')
    for unit in units:
        r = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=10)
        if r.stdout.strip() != 'active':
            issues.append(('unit_' + unit, unit + '未运行'))
    free = shutil.disk_usage('/').free
    if free < 2 * 1024**3:
        issues.append(('disk_low', f'系统盘可用空间不足2GiB（约{free / 1024**3:.2f}GiB）'))
    issues.extend(maintenance_issues(
        checkin.read(checkin.STATE / 'last-backup.json'),
        checkin.read(checkin.STATE / 'last-cleanup.json'),
        checkin.read(checkin.STATE / 'local-sync.json'),
        {job: checkin.read(checkin.STATE / (job + '-attempt.json')) for job in ['backup', 'cleanup']},
        time.time()))
    return issues


def run(config):
    path = checkin.STATE / 'health.json'
    state = checkin.read(path)
    issues = collect()
    fingerprint = hashlib.sha256('|'.join(sorted(code for code, _ in issues)).encode()).hexdigest()[:16] if issues else ''
    consecutive = state.get('consecutive', 0) + 1 if fingerprint and fingerprint == state.get('fingerprint') else 1
    previous_notice = state.get('notified_fingerprint', '') if issues else ''
    state.update(checked_at=checkin.now().isoformat(), fingerprint=fingerprint, consecutive=consecutive,
                 notified_fingerprint=previous_notice, issues=[code for code, _ in issues])
    if issues and consecutive >= 2 and previous_notice != fingerprint:
        key = checkin.now().date().isoformat() + '-health-' + fingerprint
        message = '【云端微信运行异常】\n' + '\n'.join(text for _, text in issues) + '\n连续两次检查异常，请查看服务器。\n入口：' + config.get('manage_url', 'https://checkin.example.com/')
        payload = {'kind': 'failure', 'day': checkin.now().date().isoformat(), 'label': '长期运行健康检查', 'detail': message, 'message': message}
        notice = checkin.STATE / (key + '-notice.json')
        if not notice.exists():
            checkin.save(notice, {'status': 'pending', 'payload': payload, 'next_attempt': 0})
        state['notified_fingerprint'] = fingerprint
        checkin.event('health_alert_queued', issues=state['issues'])
    checkin.save(path, state)
