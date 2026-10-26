"""Set Nginx Basic authentication using private interactive input."""
import getpass
import grp
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

assert os.geteuid() == 0, 'Run with sudo'
url = input('HTTPS desktop URL: ').strip().rstrip('/') + '/'
parsed = urlparse(url)
assert parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
username = input('Web username: ').strip()
assert username and not any(c in username for c in ':\r\n')
password = getpass.getpass('New web password: ')
assert password and not any(c in password for c in '\r\n')
assert password == getpass.getpass('Repeat web password: '), 'Passwords do not match'
root = Path('/etc/wechat-web')
root.mkdir(mode=0o750, exist_ok=True)
gid = grp.getgrnam('www-data').gr_gid
os.chown(root, 0, gid)
root.chmod(0o750)
hashed = subprocess.check_output(['openssl', 'passwd', '-6', '-stdin'], input=password + '\n', text=True).strip()
access = root / 'access.json'
access.write_text(json.dumps({'url': url, 'username': username, 'password': password}) + '\n')
access.chmod(0o600)
target = root / 'htpasswd'
target.write_text(username + ':' + hashed + '\n')
os.chown(target, 0, gid)
target.chmod(0o640)
print('Credentials saved. Validate and reload your Nginx configuration.')
