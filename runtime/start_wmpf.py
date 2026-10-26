"""Attach the pinned debugger only to the verified, owned WeChat renderer."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path('/opt/uestc-wechat/runtime')
WORK = ROOT / 'wmpf-debugger'
NAME = os.environ.get('WECHAT_CONTAINER', 'wechat-web')
UNIT = 'wechat-wmpf-debug'
RUNTIME_SECONDS = int(os.environ.get('WECHAT_DEBUG_RUNTIME_SECONDS', '7200'))
assert 60 <= RUNTIME_SECONDS <= 7200
EXPECTED_RENDERER = '75549c42a6f155c752ca7a413942f544d15aff9f44b2ece327cd047b5de71b81'
assert (ROOT / 'PROBE_OWNER').is_file()


def run(*args, **kwargs):
    return subprocess.run(list(args), capture_output=True, text=True,
                          check=True, timeout=45, **kwargs)


prepared = json.loads((WORK / 'prepared.json').read_text())
source = Path(prepared['source_dir'])
info = json.loads(run('sudo', '-n', 'docker', 'inspect', NAME).stdout)[0]
assert info['Config']['Labels']['io.github.uestc-wechat.runtime'] == 'v1'
assert info['State']['Running']
rows = run('sudo', '-n', 'docker', 'top', NAME, '-eo', 'pid,ppid,comm').stdout.splitlines()[1:]
processes = {}
for row in rows:
    parts = row.split()
    if len(parts) == 3:
        processes[int(parts[0])] = (int(parts[1]), parts[2])
roots = [pid for pid, (parent, name) in processes.items()
         if name == 'WeChatAppEx' and processes.get(parent, (0, ''))[1] != 'WeChatAppEx']
if len(roots) != 1:
    raise SystemExit('Expected one owned browser root, got ' + repr(roots))
target = roots[0]
actual = run('sudo', '-n', 'sha256sum', f'/proc/{target}/exe').stdout.split()[0]
assert actual == EXPECTED_RENDERER, 'Renderer changed; do not inject known offsets.'
platform_file = source / 'src/platform/linux.ts'
code = platform_file.read_text()
if 'WMPF_TARGET_PID' not in code:
    needle = 'if (p.name !== "WeChatAppEx") return false;'
    assert needle in code
    code = code.replace(needle, needle + '\n            if (process.env.WMPF_TARGET_PID && p.pid !== Number(process.env.WMPF_TARGET_PID)) return false;')
    needle = 'const wmpfVersion = readableProcessPath\n            ? searchWmpfVersionInFile(readableProcessPath)\n            : 0;'
    assert needle in code
    code = code.replace(needle, 'const wmpfVersion = process.env.WMPF_TARGET_VERSION\n            ? Number(process.env.WMPF_TARGET_VERSION)\n            : (readableProcessPath ? searchWmpfVersionInFile(readableProcessPath) : 0);')
    platform_file.write_text(code)
log = WORK / 'debugger.log'
assert not log.is_symlink()
if log.exists() and log.stat().st_size > 8 * 1024 * 1024:
    log.replace(WORK / 'debugger.previous.log')
log.touch(mode=0o600, exist_ok=True)
log.chmod(0o600)
unit_state = subprocess.run(['sudo', '-n', 'systemctl', 'is-active', UNIT], capture_output=True, text=True)
if unit_state.stdout.strip() == 'active':
    raise SystemExit('Debugger unit already active; inspect instead of duplicating.')
node = str(Path(prepared['node_dir']) / 'bin/node')
command = ['sudo', '-n', 'systemd-run', '--collect', '--service-type=exec',
           '--unit=' + UNIT, '--property=MemoryMax=512M', '--property=CPUQuota=50%',
           '--property=RuntimeMaxSec=' + str(RUNTIME_SECONDS), '--working-directory=' + str(source),
           '--property=StandardOutput=append:' + str(log),
           '--property=StandardError=append:' + str(log),
           '--setenv=WMPF_TARGET_PID=' + str(target), '--setenv=WMPF_TARGET_VERSION=25806',
           '--setenv=PATH=' + str(Path(prepared['node_dir']) / 'bin') + ':/usr/local/bin:/usr/bin:/bin',
           '/usr/bin/nsenter', '--target', str(info['State']['Pid']), '--net',
           node, '--import', 'tsx', 'src/index.ts']
if os.environ.get('WECHAT_DEBUG_VERBOSE', '1') == '1':
    command.append('--debug-frida')
result = run(*command)
record = {'unit': UNIT, 'container': NAME, 'target_host_pid': target,
          'container_host_pid': info['State']['Pid'], 'renderer_sha256': actual,
          'wmpf_version': 25806, 'network': 'container loopback; no published ports',
          'profile_preserved': True}
(WORK / 'debugger-start.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
print(result.stderr.strip())
