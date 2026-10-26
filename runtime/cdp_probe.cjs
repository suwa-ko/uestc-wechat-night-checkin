const fs = require('node:fs');
const path = require('node:path');
const root = '/opt/uestc-wechat/runtime/wmpf-debugger';
const prepared = JSON.parse(fs.readFileSync(path.join(root, 'prepared.json'), 'utf8'));
const WebSocket = require(path.join(prepared.source_dir, 'node_modules/ws'));
const ws = new WebSocket('ws://127.0.0.1:62000');
let nextId = Math.floor(Date.now() % 100000000);
const pending = new Map();
ws.on('message', data => {
  let message;
  try { message = JSON.parse(data.toString()); } catch { return; }
  if (message.id && pending.has(message.id)) {
    const waiter = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(waiter.timer);
    if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
    else waiter.resolve(message.result || {});
  }
});
function request(method, params = {}, sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(method + ' timed out')); }, 12000);
    pending.set(id, {resolve, reject, timer});
    ws.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
  });
}
function safeUrl(raw) {
  try { const u = new URL(raw); return u.origin + u.pathname + u.hash.split('?')[0]; }
  catch { return String(raw || '').split('?')[0]; }
}
async function main() {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('CDP WebSocket open timed out')), 8000);
    ws.once('open', () => { clearTimeout(timer); resolve(); });
    ws.once('error', error => { clearTimeout(timer); reject(error); });
  });
  const action = process.argv[2] || 'targets';
  if (action === 'targets') {
    const result = await request('Target.getTargets');
    return {action, targets: (result.targetInfos || []).map(t => ({
      targetId: t.targetId, type: t.type, title: /:\/\//.test(t.title || '') ? safeUrl(t.title) : t.title,
      url: safeUrl(t.url), attached: t.attached
    }))};
  }
  if (action === 'webview-info') {
    const result = await request('Target.getTargets');
    const target = (result.targetInfos || []).find(t => t.type === 'webview' &&
      t.url.startsWith('https://jzsz.uestc.edu.cn/daily-checkin-h5/'));
    if (!target) throw new Error('School WebView target not found');
    const attached = await request('Target.attachToTarget', {targetId: target.targetId, flatten: true});
    try {
      const result = await request('Runtime.evaluate', {
        expression: '({secure:isSecureContext,hasGeolocation:!!navigator.geolocation,hasOperationTicket:!!sessionStorage.getItem("daily-checkin-operation-ticket"),title:document.title,origin:location.origin,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone})',
        returnByValue: true
      }, attached.sessionId);
      return {action, targetId: target.targetId, sessionId: attached.sessionId,
        facts: result.result?.value, error: result.exceptionDetails?.text};
    } finally {
      await request('Target.detachFromTarget', {sessionId: attached.sessionId}).catch(() => {});
    }
  }
  if (action === 'location-sync-map') {
    const config = JSON.parse(fs.readFileSync('/etc/wechat-checkin/config.json')).location;
    const gcj = config.gcj02;
    if (!Array.isArray(gcj) || gcj.length!==2 || !gcj.every(Number.isFinite)) throw new Error('Verified map coordinates required');
    const targets = await request('Target.getTargets');
    const matches = (targets.targetInfos || []).filter(t => t.type==='webview' && t.url.startsWith('https://jzsz.uestc.edu.cn/daily-checkin-h5/'));
    if (matches.length!==1) throw new Error('Expected one check-in WebView');
    const attached = await request('Target.attachToTarget',{targetId:matches[0].targetId,flatten:true});
    try {
      const expression=`(()=>{
        if(location.origin!=='https://jzsz.uestc.edu.cn'||!location.pathname.startsWith('/daily-checkin-h5/'))throw new Error('Unexpected page');
        const u=new URL(location.href);
        const raw=u.hash.slice(1);const split=raw.indexOf('?');
        const route=split<0?raw:raw.slice(0,split);
        if(!route.includes('/pages/student/report-today/home/'))throw new Error('Unexpected route');
        const params=new URLSearchParams(split<0?'':raw.slice(split+1));
        params.set('latitude',${JSON.stringify(String(gcj[1]))});params.set('longitude',${JSON.stringify(String(gcj[0]))});
        u.hash=route+'?'+params.toString();
        setTimeout(()=>location.replace(u.href),100);
        return {navigationScheduled:true,latitude:${gcj[1]},longitude:${gcj[0]},coordinateSystem:'GCJ02',checkinSubmitted:false};
      })()`;
      const result=await request('Runtime.evaluate',{expression,returnByValue:true},attached.sessionId);
      if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);
      return {action,...result.result?.value};
    } finally {await request('Target.detachFromTarget',{sessionId:attached.sessionId}).catch(()=>{});}
  }
  if (action === 'location-enable' || action === 'location-disable' || action === 'location-status') {
    const enabled = action === 'location-enable';
    const latitude = Number(process.argv[3]);
    const longitude = Number(process.argv[4]);
    if (enabled && (!Number.isFinite(latitude) || !Number.isFinite(longitude) ||
        process.argv.length < 5 || Math.abs(latitude) > 90 || Math.abs(longitude) > 180)) {
      throw new Error('Provide explicit WGS84 latitude and longitude');
    }
    const targets = await request('Target.getTargets');
    const matches = (targets.targetInfos || []).filter(t => t.type === 'webview' &&
      t.url.startsWith('https://jzsz.uestc.edu.cn/daily-checkin-h5/'));
    if (matches.length !== 1) throw new Error('Expected exactly one school check-in WebView; found ' + matches.length);
    const attached = await request('Target.attachToTarget', {targetId: matches[0].targetId, flatten: true});
    try {
      // This override lives only in the current document. No check-in API is called.
      const expression = `(()=>{
        if(location.origin!=='https://jzsz.uestc.edu.cn'||!location.pathname.startsWith('/daily-checkin-h5/'))return {enabled:false,skipped:true};
        const key='__codexCheckinLocation';
        const action=${JSON.stringify(action)};
        const g=navigator.geolocation;
        let state=window[key];
        if(action==='location-disable'){
          if(state){
            for(const id of state.timers.values())clearInterval(id);
            for(const [name,descriptor] of Object.entries(state.original)){
              if(descriptor)Object.defineProperty(g,name,descriptor);else delete g[name];
            }
            state.badge?.remove();delete window[key];
          }
          return {enabled:false,checkinSubmitted:false};
        }
        if(action==='location-status'){
          const map=[];let c=document.querySelector('#map')?.__vueParentComponent;
          for(let i=0;c&&i<12;i++,c=c.parent){const p=c.props;if(p&&typeof p.latitude==='number'&&typeof p.longitude==='number')map.push({latitude:p.latitude,longitude:p.longitude});}
          const h=location.hash;const q=new URLSearchParams(h.includes('?')?h.slice(h.indexOf('?')+1):'');
          return {enabled:!!state,point:state?.point,mapCoordinates:map,routeCoordinates:{latitude:q.get('latitude'),longitude:q.get('longitude')},badgeVisible:!!state?.badge?.isConnected,scope:'current check-in document',checkinSubmitted:false};
        }
        if(!state){
          state={original:{},timers:new Map(),nextId:1000000,nativeClear:g.clearWatch.bind(g)};
          for(const name of ['getCurrentPosition','watchPosition','clearWatch'])state.original[name]=Object.getOwnPropertyDescriptor(g,name);
          window[key]=state;
        }
        state.point={latitude:${JSON.stringify(latitude)},longitude:${JSON.stringify(longitude)},accuracy:10};
        const makePosition=()=>({coords:{...state.point,altitude:null,altitudeAccuracy:null,heading:null,speed:null},timestamp:Date.now()});
        Object.defineProperty(g,'getCurrentPosition',{configurable:true,writable:true,value:function(success){
          if(typeof success!=='function')throw new TypeError('Success callback is required');
          setTimeout(()=>success(makePosition()),0);
        }});
        Object.defineProperty(g,'watchPosition',{configurable:true,writable:true,value:function(success){
          if(typeof success!=='function')throw new TypeError('Success callback is required');
          const id=++state.nextId;
          state.timers.set(id,setInterval(()=>success(makePosition()),1000));
          setTimeout(()=>{if(state.timers.has(id))success(makePosition())},0);
          return id;
        }});
        Object.defineProperty(g,'clearWatch',{configurable:true,writable:true,value:function(id){
          if(state.timers.has(id)){clearInterval(state.timers.get(id));state.timers.delete(id)}else state.nativeClear(id);
        }});
        const renderBadge=()=>{if(!document.documentElement)return;
        if(!state.badge){
          const badge=document.createElement('div');
          badge.id='codex-location-test-status';
          badge.style.cssText='position:fixed;left:8px;bottom:8px;z-index:2147483647;background:#714300;color:white;padding:8px;border-radius:6px;font:12px sans-serif;pointer-events:none';
          document.documentElement.appendChild(badge);state.badge=badge;
        }
        state.badge.textContent='定位测试已启用 · GPS '+state.point.latitude+', '+state.point.longitude+' · 仅当前网页';
        };
        renderBadge();
        if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',renderBadge,{once:true});
        return {enabled:true,point:state.point,scope:'current check-in document',checkinSubmitted:false};
      })()`;
      const result = await request('Runtime.evaluate', {expression, returnByValue:true}, attached.sessionId);
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
      const report = {action, ...result.result?.value};
      if (enabled) {
        const verified = await request('Runtime.evaluate', {
          expression: 'new Promise(resolve=>navigator.geolocation.getCurrentPosition(p=>resolve({latitude:p.coords.latitude,longitude:p.coords.longitude,accuracy:p.coords.accuracy})))',
          returnByValue:true, awaitPromise:true
        }, attached.sessionId);
        report.returned = verified.result?.value;
        if (!report.returned || report.returned.latitude !== latitude || report.returned.longitude !== longitude) throw new Error('Override read-back failed');
        report.readBackMatches = true;
      }
      return report;
    } finally {
      await request('Target.detachFromTarget', {sessionId:attached.sessionId}).catch(()=>{});
    }
  }
  throw new Error('Unsupported diagnostic action');
}
main().then(result => console.log(JSON.stringify(result, null, 2)))
  .catch(error => { console.error(JSON.stringify({error: error.message})); process.exitCode = 1; })
  .finally(() => ws.close());
