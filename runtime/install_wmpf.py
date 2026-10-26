import json
import subprocess
from pathlib import Path

ROOT = Path('/opt/uestc-wechat/runtime')
WORK = ROOT / 'wmpf-debugger'
assert (ROOT / 'PROBE_OWNER').is_file()
prepared = json.loads((WORK / 'prepared.json').read_text())
node = str(Path(prepared['node_dir']) / 'bin/node')
yarn = str(Path(prepared['yarn_dir']) / 'bin/yarn.js')
log = WORK / 'install.log'
log.touch(mode=0o600, exist_ok=True)
command = ['sudo', '-n', 'systemd-run', '--wait', '--collect',
           '--unit=wechat-wmpf-deps',
           '--property=MemoryMax=768M', '--property=CPUQuota=75%',
           '--property=RuntimeMaxSec=900',
           f'--property=StandardOutput=append:{log}',
           f'--property=StandardError=append:{log}',
           '--working-directory=' + prepared['source_dir'],
           '--setenv=PATH=' + str(Path(prepared['node_dir']) / 'bin') + ':/usr/local/bin:/usr/bin:/bin',
           node, yarn, 'install', '--frozen-lockfile', '--non-interactive',
           '--network-timeout', '30000', '--registry', 'https://registry.npmjs.org',
           '--cache-folder', str(WORK / 'yarn-cache')]
result = subprocess.run(command, timeout=930)
print('install_exit', result.returncode)
raise SystemExit(result.returncode)
