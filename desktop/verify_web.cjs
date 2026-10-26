'use strict';
// Verify the HTTPS/WebSocket boundary without logging authentication material.
const fs = require('node:fs');
const https = require('node:https');
const path = require('node:path');
const root = '/opt/uestc-wechat/runtime/wmpf-debugger';
const prepared = JSON.parse(fs.readFileSync(path.join(root, 'prepared.json')));
const WebSocket = require(path.join(prepared.source_dir, 'node_modules/ws'));
const access = JSON.parse(fs.readFileSync('/etc/wechat-web/access.json'));
const authorization = 'Basic ' + Buffer.from(access.username + ':' + access.password).toString('base64');

function getPage(auth) {
  return new Promise((resolve, reject) => {
    const req = https.get(access.url + 'vnc.html', {headers: auth ? {Authorization: authorization} : {}}, res => {
      let html = '';
      res.on('data', d => { html += d; });
      res.on('end', () => resolve({status: res.statusCode, novnc: html.includes('noVNC')}));
    });
    req.setTimeout(10000, () => req.destroy(new Error('HTTP timeout')));
    req.on('error', reject);
  });
}

function connect(auth, origin) {
  return new Promise((resolve, reject) => {
    const headers = {Origin: origin};
    if (auth) headers.Authorization = authorization;
    const ws = new WebSocket(access.url.replace('https:', 'wss:') + 'websockify', ['binary'], {headers});
    const timer = setTimeout(() => { ws.terminate(); reject(new Error('WebSocket timeout')); }, 12000);
    const finish = result => { clearTimeout(timer); resolve(result); };
    ws.once('message', data => {
      const rfb = data.toString('ascii');
      ws.terminate();
      finish({status: 101, rfb: /^RFB \d{3}\.\d{3}\n$/.test(rfb)});
    });
    ws.once('unexpected-response', (req, res) => {
      res.resume();
      finish({status: res.statusCode});
      req.destroy();
    });
    ws.on('error', err => { clearTimeout(timer); reject(err); });
  });
}

(async () => {
  const results = {
    anonymous_page: await getPage(false),
    authenticated_page: await getPage(true),
    anonymous_websocket: await connect(false, new URL(access.url).origin),
    wrong_origin: await connect(true, 'https://example.invalid'),
    authenticated_websocket: await connect(true, new URL(access.url).origin),
  };
  console.log(JSON.stringify(results, null, 2));
  if (results.anonymous_page.status !== 401 || results.authenticated_page.status !== 200 ||
      !results.authenticated_page.novnc || results.anonymous_websocket.status !== 401 ||
      results.wrong_origin.status !== 403 || !results.authenticated_websocket.rfb) process.exitCode = 1;
})().catch(() => { console.error('Web validation failed; no credentials logged.'); process.exitCode = 1; });
