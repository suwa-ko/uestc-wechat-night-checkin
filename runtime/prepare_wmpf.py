"""Fetch pinned debugger sources and verified, local-only Node/Yarn runtimes."""
import base64
import hashlib
import json
import os
import re
import shutil
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path('/opt/uestc-wechat/runtime')
WORK = ROOT / 'wmpf-debugger'
COMMIT = '9be0b2d0bd9875bd21a104a2279ad4304b46388b'
assert (ROOT / 'PROBE_OWNER').is_file()
assert shutil.disk_usage(ROOT).free > 2 * 1024**3
WORK.mkdir(mode=0o700, exist_ok=True)


def fetch(url, target):
    if target.exists():
        return
    temp = target.with_suffix(target.suffix + '.partial')
    with urllib.request.urlopen(url, timeout=45) as response, temp.open('wb') as f:
        shutil.copyfileobj(response, f)
    temp.replace(target)


def unpack(archive, expected_name):
    dest = WORK / expected_name
    if not dest.exists():
        with tarfile.open(archive) as tar:
            roots = {Path(m.name).parts[0] for m in tar.getmembers() if Path(m.name).parts}
            if roots != {expected_name}:
                raise RuntimeError('Unexpected archive root: ' + repr(roots))
            tar.extractall(WORK, filter='data')
    return dest


with urllib.request.urlopen('https://nodejs.org/dist/v22.23.4/SHASUMS256.txt', timeout=30) as r:
    sums = r.read().decode()
match = re.search(r'^([0-9a-f]{64})\s+(node-v22\.[0-9.]+-linux-x64\.tar\.xz)$', sums, re.M)
assert match
node_sha, node_name = match.groups()
node_tar = WORK / node_name
fetch('https://nodejs.org/dist/v22.23.4/' + node_name, node_tar)
assert hashlib.sha256(node_tar.read_bytes()).hexdigest() == node_sha
node_dir = unpack(node_tar, node_name.removesuffix('.tar.xz'))
with urllib.request.urlopen('https://registry.npmjs.org/yarn/1.22.22', timeout=30) as r:
    yarn_meta = json.load(r)
yarn_tar = WORK / 'yarn-1.22.22.tgz'
fetch(yarn_meta['dist']['tarball'], yarn_tar)
expected_integrity = yarn_meta['dist']['integrity'].removeprefix('sha512-')
assert base64.b64encode(hashlib.sha512(yarn_tar.read_bytes()).digest()).decode() == expected_integrity
yarn_dir = unpack(yarn_tar, 'package')
source_dir = WORK / f'WMPFDebugger-{COMMIT}'
source_dir.mkdir(exist_ok=True)
manifest = json.loads((ROOT / 'wmpf-source-manifest.json').read_text())
opener = urllib.request.build_opener()


def source_file(item):
    target = source_dir / item['path']
    assert target.resolve().is_relative_to(source_dir.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    def git_hash(data):
        return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if target.exists() and git_hash(target.read_bytes()) == item['sha']:
        return
    url = f'https://raw.githubusercontent.com/evi0s/WMPFDebugger/{COMMIT}/' + item['path']
    with opener.open(url, timeout=30) as response:
        data = response.read()
    assert git_hash(data) == item['sha'], item['path']
    target.write_bytes(data)


with ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(source_file, manifest))
entry = source_dir / 'src/index.ts'
code = entry.read_text()
if 'new WebSocketServer({ port: options.debugPort });' in code:
    assert code.count('new WebSocketServer({ port:') == 2
    code = code.replace('new WebSocketServer({ port: options.debugPort });',
                        'new WebSocketServer({ host: "127.0.0.1", port: options.debugPort });')
    code = code.replace('new WebSocketServer({ port: options.cdpPort });',
                        'new WebSocketServer({ host: "127.0.0.1", port: options.cdpPort });')
    entry.write_text(code)
assert code.count('host: "127.0.0.1", port:') == 2
metadata = {'commit': COMMIT, 'source_dir': str(source_dir),
            'source_file_count': len(manifest), 'source_verification': 'Git blob hashes at pinned commit',
            'node_dir': str(node_dir), 'node_archive_sha256': node_sha,
            'yarn_dir': str(yarn_dir), 'patch': 'Bind both debugger WebSockets to loopback only'}
(WORK / 'prepared.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata, indent=2), flush=True)
