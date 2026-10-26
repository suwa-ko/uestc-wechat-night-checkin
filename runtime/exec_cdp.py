import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path('/opt/uestc-wechat/runtime')
WORK = ROOT / 'wmpf-debugger'
prepared = json.loads((WORK / 'prepared.json').read_text())
info = json.loads(subprocess.run(['sudo', '-n', 'docker', 'inspect', os.environ.get('WECHAT_CONTAINER', 'wechat-web')],
                                capture_output=True, text=True, check=True).stdout)[0]
assert info['Config']['Labels']['io.github.uestc-wechat.runtime'] == 'v1'
assert info['State']['Running']
cmd = ['sudo', '-n', 'nsenter', '--target', str(info['State']['Pid']), '--net',
       prepared['node_dir'] + '/bin/node', str(WORK / 'cdp_probe.cjs'), *sys.argv[1:]]
result = subprocess.run(cmd, timeout=80)
raise SystemExit(result.returncode)
