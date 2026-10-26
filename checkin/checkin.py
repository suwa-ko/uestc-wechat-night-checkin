"""Scheduled UI check-in with durable duplicate protection and QQ-only failures."""
import argparse
from datetime import datetime, time as daytime
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path('/usr/local/lib/wechat-checkin')
STATE = Path('/var/lib/wechat-checkin')
CONFIG = Path('/etc/wechat-checkin/config.json')
PROBE = Path('/opt/uestc-wechat/runtime')
TZ = ZoneInfo('Asia/Shanghai')
AUTH_ERRORS = {'AUTH_REQUIRED', 'TICKET_MISSING'}
ERRORS = {
    'NOTIFICATION_TEST': '测试 QQ 错误报告通道；本次没有向学校提交签到。',
    'AUTH_REQUIRED': '微信需要本人确认登录、解锁或处理验证码；已暂停自动操作。',
    'TICKET_MISSING': '没有取得本次操作凭证；已暂停，需本人打开小程序检查登录。',
    'BUSINESS_DATE_MISMATCH': '学校页面的业务日期不是今天，未提交，避免签到日期错误。',
    'LOCATION_NOT_READY': '配置的位置定位或地图坐标核验未通过，未提交。',
    'SUBMIT_BUTTON_UNAVAILABLE': '未找到可用的“请打卡”按钮，可能尚未进入时段或页面异常。',
    'EXISTING_CASE_RECORD': '页面已有情况填报记录，停止自动签到，请本人核对。',
    'UNKNOWN_RECORD_STATUS': '学校返回了未识别的签到状态，停止点击，请本人核对。',
    'ADVISER_REQUIRED': '学校将账号标记为异常，请联系辅导员处理。',
    'STATUS_READ_FAILED': '学校的今日记录查询失败，未提交，避免把未知状态当成未签到。',
    'RESULT_UNCONFIRMED': '已点击确认，但未核验到今天“已打卡”。不再重复提交，请本人核对学校记录。',
    'DUPLICATE_GUARD': '已有提交意图或完成记录，为避免重复签到未再次提交。',
    'SCHEDULE_MISSING': '21:01 后未发现完成记录，定时任务可能未运行或意外退出。',
    'WECHAT_UNAVAILABLE': '云端微信容器未正常运行，请打开网页检查。',
    'DEBUGGER_VERSION_CHANGED': '微信版本或进程校验不符，停止使用调试定位。',
}


class Failure(Exception):
    pass


def now():
    return datetime.now(TZ)


def allowed(value):
    return daytime(21, 1) <= value.time().replace(tzinfo=None) < daytime(23)


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)


def save(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    temp.chmod(0o600)
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def event(name, **fields):
    print(json.dumps({'time': now().isoformat(), 'event': name, **fields}, ensure_ascii=False), flush=True)


def run(args, timeout=30, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)


def acquire_lock(handle, wait_seconds=0):
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(.1, remaining))


def maintenance_attempt(job, status, **fields):
    save(STATE / (job + '-attempt.json'), {'status': status, 'time': now().isoformat(), **fields})


def defer_maintenance(job, reason):
    maintenance_attempt(job, 'deferred', reason=reason)
    event(job + '_deferred_' + reason)
    # EX_TEMPFAIL: systemd retries this outcome, with a bounded start limit.
    raise SystemExit(75)


def container():
    r = run(['docker', 'inspect', 'wechat-web'])
    if r.returncode:
        raise Failure('WECHAT_UNAVAILABLE')
    d = json.loads(r.stdout)[0]
    if d['Config'].get('Labels', {}).get('io.github.uestc-wechat.desktop') != 'v1' or not d['State']['Running']:
        raise Failure('WECHAT_UNAVAILABLE')
    return d


def debugger():
    d = container()
    record = read(PROBE / 'wmpf-debugger/debugger-start.json')
    active = run(['systemctl', 'is-active', 'wechat-wmpf-debug']).stdout.strip() == 'active'
    if active and record.get('container_host_pid') != d['State']['Pid']:
        run(['systemctl', 'stop', 'wechat-wmpf-debug'])
        active = False
    if not active:
        env = dict(os.environ, WECHAT_DEBUG_RUNTIME_SECONDS='900', WECHAT_DEBUG_VERBOSE='0')
        r = run(['python3', str(PROBE / 'start_wmpf.py')], timeout=90, env=env)
        if r.returncode:
            raise Failure('DEBUGGER_VERSION_CHANGED')
        time.sleep(2)


def node(action, timeout=75):
    d = container()
    p = read(PROBE / 'wmpf-debugger/prepared.json')
    r = run(['nsenter', '--target', str(d['State']['Pid']), '--net',
             p['node_dir'] + '/bin/node', str(ROOT / 'agent.cjs'), action], timeout=timeout)
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise Failure('AUTOMATION_PROCESS_FAILED') from None
    if not data.get('ok'):
        code = str(data.get('error', 'AUTOMATION_ERROR'))
        raise Failure(code if re.fullmatch(r'[A-Z0-9_.]{1,100}', code) else 'AUTOMATION_ERROR')
    return data.get('result')


def location(config):
    for action in [('location-sync-map',),
                   ('location-enable', str(config['location']['latitude']), str(config['location']['longitude']))]:
        for attempt in range(8):
            r = run(['python3', str(PROBE / 'exec_cdp.py'), *action], timeout=30)
            if r.returncode == 0:
                break
            time.sleep(.75)
        else:
            raise Failure('LOCATION_NOT_READY')
        time.sleep(1)


def prepare(config):
    debugger()
    try:
        node('open')
    except Failure as e:
        if str(e) not in {'MINIAPP_NOT_OPEN', 'CDP_TIMEOUT_TARGET.GETTARGETS', 'DEBUGGER_CONNECTION_FAILED', 'DEBUGGER_CONNECTION_TIMEOUT'}:
            raise
        from ui import bootstrap
        try:
            bootstrap()
        except RuntimeError as error:
            raise Failure(str(error)) from None
        for attempt in range(4):
            try:
                node('open')
                break
            except Failure:
                if attempt == 3:
                    raise
                time.sleep(1)
    location(config)
    for _ in range(20):
        snapshot = node('inspect', timeout=25)
        if snapshot.get('authRequired'):
            raise Failure('AUTH_REQUIRED')
        if snapshot.get('hasTicket') and snapshot.get('businessDate'):
            if not snapshot.get('locationActive') or not snapshot.get('mapMatches'):
                raise Failure('LOCATION_NOT_READY')
            return snapshot
        time.sleep(1)
    raise Failure('PAGE_STATUS_NOT_READY')


def sanitize(text):
    text = re.sub(r'https?://\S+', '[链接已隐藏]', str(text))
    text = re.sub(r'(?i)(ticket|token|cookie|session|authorization)\s*[:=]\s*\S+', r'\1=[隐藏]', text)
    text = re.sub(r'\b[A-Za-z0-9_-]{32,}\b', '[隐藏]', text)
    return text[:1200]


def send_notice(config, payload):
    channel = config['astrbot']
    message = payload['message']
    try:
        r = run(['docker', 'exec', '-i', 'astrbot', 'python', '-B', '/AstrBot/data/wechat-checkin/render_notice.py'],
                input=json.dumps(payload, ensure_ascii=False), timeout=35)
        if r.returncode:
            raise ValueError('render')
        attachment = json.loads(r.stdout.strip().splitlines()[-1])['attachment_id']
        if not re.fullmatch(r'[0-9a-f-]{36}', attachment):
            raise ValueError('attachment')
        message = [{'type': 'image', 'attachment_id': attachment}]
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        event('notice_render_fallback')
    key = Path(channel['key_file']).read_text().strip()
    request = urllib.request.Request(channel['url'], data=json.dumps({'umo': channel['umo'], 'message': message}).encode(),
                                     headers={'Content-Type': 'application/json', 'X-API-Key': key})
    try:
        # No proxy environment may redirect local API credentials.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=20) as response:
            result = json.loads(response.read(65536))
        return 'accepted' if result.get('status') == 'ok' else 'unknown'
    except urllib.error.HTTPError as e:
        return 'pending' if e.code in {401, 403, 404, 429} else 'unknown'
    except urllib.error.URLError as e:
        return 'pending' if isinstance(e.reason, ConnectionRefusedError) else 'unknown'
    except (TimeoutError, socket.timeout, ValueError):
        return 'unknown'


def deliver(config, day):
    path = STATE / (day + '-notice.json')
    data = read(path)
    if data.get('status') != 'pending' or time.time() < data.get('next_attempt', 0):
        return
    data['status'] = 'inflight'
    save(path, data)
    try:
        status = send_notice(config, data['payload'])
    except Exception:
        status = 'pending'
    data.update(status=status, next_attempt=time.time() + 300)
    save(path, data)
    event('notice_delivery', status=status)


def queue(config, day, code, snapshot=None, test=False):
    path = STATE / (day + '-notice.json')
    if path.exists() and not test:
        deliver(config, day)
        return
    detail = ERRORS.get(code, '自动操作未能完成，请打开网页核对微信和学校页面。')
    extra = ''
    if snapshot:
        extra = '\n页面状态：' + sanitize(json.dumps({k: snapshot.get(k) for k in ['businessDate', 'recordStatus', 'notices', 'schoolResponse']}, ensure_ascii=False))
    message = ('【通知通道测试】这是一张测试卡片，不代表签到失败。' if test else '【晚安成电自动签到未确认成功】')
    manage_url = config.get('manage_url', 'https://checkin.example.com/')
    message += f'\n时间：{now():%Y-%m-%d %H:%M:%S}（北京时间）\n位置：配置的位置\n阶段/代码：{code}\n{detail}{extra}\n处理入口：{manage_url}'
    payload = {'kind': 'test' if test else 'auth_pause' if code in AUTH_ERRORS else 'failure',
               'day': day, 'label': '21:01 自动签到' if not test else 'QQ 通知链路测试', 'detail': message, 'message': message}
    save(path, {'status': 'pending', 'payload': payload, 'next_attempt': 0})
    deliver(config, day)


def fail(config, day, code, snapshot=None):
    path = STATE / (day + '.json')
    record = read(path)
    record.update(day=day, outcome='unknown' if record.get('confirmIntent') else 'failed', error=code, finishedAt=now().isoformat())
    save(path, record)
    control_path = STATE / 'control.json'
    control = read(control_path)
    if code in AUTH_ERRORS:
        if control.get('auth_paused'):
            return
        save(control_path, {'auth_paused': True, 'paused_at': now().isoformat(), 'reason': code})
    queue(config, day, code, snapshot)
    event('checkin_failed', code=code, submitted=bool(record.get('confirmIntent')))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'submit', 'dry-run', 'watchdog', 'test-notice', 'resume'])
    args = parser.parse_args()
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            event('already_running')
            return
        config = read(CONFIG)
        day = now().date().isoformat()
        if args.action == 'resume':
            save(STATE / 'control.json', {'auth_paused': False, 'resumed_at': now().isoformat()})
            event('auth_resumed')
            return
        if args.action == 'test-notice':
            key = day + '-test'
            if (STATE / (key + '-notice.json')).exists():
                event('test_already_sent')
                return
            queue(config, key, 'NOTIFICATION_TEST', test=True)
            return
        if args.action == 'watchdog':
            try:
                import health
                health.run(config)
            except Exception:
                event('healthcheck_failed')
            # Keep queued QQ failures deliverable after a bot outage, including across midnight.
            for notice in sorted(STATE.glob('*-notice.json')):
                if read(notice).get('status') == 'pending':
                    deliver(config, notice.name.removesuffix('-notice.json'))
            if not allowed(now()) or now().time().replace(tzinfo=None) < daytime(21, 5):
                return
            record = read(STATE / (day + '.json'))
            if read(STATE / 'control.json').get('auth_paused'):
                deliver(config, day)
            elif record.get('outcome') in {'failed', 'unknown'} and not (STATE / (day + '-notice.json')).exists():
                fail(config, day, record.get('error', 'RESULT_UNCONFIRMED'))
            elif record.get('outcome') not in {'success', 'already_done', 'exempt', 'failed', 'unknown'}:
                fail(config, day, 'SCHEDULE_MISSING')
            else:
                deliver(config, day)
            return
        if read(STATE / 'control.json').get('auth_paused'):
            event('auth_paused_no_login_attempt')
            return
        if args.action == 'submit' and not allowed(now()):
            event('outside_checkin_window')
            return
        record_path = STATE / (day + '.json')
        record = read(record_path)
        if args.action == 'submit' and (record.get('confirmIntent') or record.get('outcome') in {'success', 'already_done', 'exempt'}):
            event('daily_duplicate_guard')
            return
        try:
            snapshot = prepare(config)
            if args.action in {'prepare', 'dry-run'}:
                save(STATE / 'last-prepare.json', {'time': now().isoformat(), 'dry_run': args.action == 'dry-run', 'snapshot': snapshot})
                event('prepared', dry_run=args.action == 'dry-run', snapshot=snapshot)
                return
            save(record_path, {'day': day, 'phase': 'ready', 'startedAt': now().isoformat(), 'outcome': 'running'})
            result = node('submit', timeout=75)
            verdict = result['verdict']
            if verdict in {'SUCCESS', 'ALREADY_DONE', 'EXEMPT'}:
                record = read(record_path)
                outcome = {'SUCCESS': 'success', 'ALREADY_DONE': 'already_done', 'EXEMPT': 'exempt'}[verdict]
                record.update(day=day, outcome=outcome, finishedAt=now().isoformat(), verified_business_date=day,
                              verified_record_status=result.get('snapshot', {}).get('recordStatus'))
                save(record_path, record)
                event('checkin_verified', outcome=outcome)
            else:
                fail(config, day, verdict, result.get('snapshot'))
        except Exception as e:
            code = str(e) if isinstance(e, Failure) and re.fullmatch(r'[A-Z0-9_.]{1,100}', str(e)) else 'AUTOMATION_PROCESS_FAILED'
            if args.action == 'dry-run':
                event('dry_run_failed', code=code)
                raise SystemExit(1) from None
            if args.action == 'prepare' and code not in AUTH_ERRORS:
                save(STATE / 'last-prepare.json', {'time': now().isoformat(), 'error': code})
                event('prepare_failed_will_retry_at_2101', code=code)
                return
            fail(config, day, code)


if __name__ == '__main__':
    main()
