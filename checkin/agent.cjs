'use strict';
const fs=require('node:fs');
const {CDP,walkSource}=require('./cdp.cjs');
const {decide}=require('./policy.cjs');
const APP='wxaa78bf2905f01cee';
const ORIGIN='https://jzsz.uestc.edu.cn';
const client=new CDP();
const config=JSON.parse(fs.readFileSync('/etc/wechat-checkin/config.json'));
const pause=ms=>new Promise(r=>setTimeout(r,ms));
function beijing(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date());}
const pageSnapshot=`(async()=>{${walkSource}
 if(location.origin!==${JSON.stringify(ORIGIN)}||!location.pathname.startsWith('/daily-checkin-h5/'))throw new Error('Wrong page');
 if(!window.__codexCheckinResponses){
  window.__codexCheckinResponses=[];
  const original=XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send=function(...args){this.addEventListener('load',()=>{try{
   const u=new URL(this.responseURL);if(u.origin!==location.origin)return;
   const data=this.responseType==='json'?this.response:['','text'].includes(this.responseType)?JSON.parse(this.responseText):null;
   if(data&&/^[-0-9]+$/.test(String(data.code))){const list=window.__codexCheckinResponses;list.push({httpStatus:this.status,code:String(data.code)});if(list.length>20)list.shift();}
  }catch{}},{once:true});return original.apply(this,args)};
 }
 const nodes=allNodes();const components=new Set();
 for(const e of nodes){let c=e.__vueParentComponent;for(let i=0;c&&i<15;i++,c=c.parent)components.add(c);}
 const records=[];let map;
 for(const c of components){const p=c.props||{};if(typeof p.recordStatusCode==='string'&&p.businessDate)records.push({recordStatus:p.recordStatusCode,businessDate:String(p.businessDate).slice(0,10)});
  if(p.checkInInfo&&typeof p.checkInInfo.recordStatusCode==='string'&&p.businessDate)records.push({recordStatus:p.checkInInfo.recordStatusCode,businessDate:String(p.businessDate).slice(0,10)});
  if(typeof p.latitude==='number'&&typeof p.longitude==='number'&&c.vnode?.props?.id==='map')map={latitude:p.latitude,longitude:p.longitude};
 }
 const unique=[...new Map(records.map(r=>[r.recordStatus+'|'+r.businessDate,r])).values()];
 if(unique.length>1)throw new Error('Ambiguous status');
 if(!map){let c=document.querySelector('#map')?.__vueParentComponent;for(let i=0;c&&i<12;i++,c=c.parent){if(typeof c.props?.latitude==='number'&&typeof c.props?.longitude==='number'){map={latitude:c.props.latitude,longitude:c.props.longitude};break;}}}
 const circles=nodes.filter(e=>e.classList?.contains('check-in-circle')&&!e.classList.contains('disabled')&&e.textContent.trim()==='请打卡'&&visible(e));
 const text=(document.body.innerText||'');
 const notices=nodes.filter(e=>visible(e)&&e.classList&&[...e.classList].some(c=>/^uni-toast|wd-toast__content|wd-message-box__content$/.test(c))).map(e=>e.textContent.trim().slice(0,300)).filter(Boolean).slice(-3);
 // The school's own read-only GET. Personal fields are never returned through CDP.
 const statusModule=await import('/daily-checkin-h5/assets/student.g_CYnQCg.js');
 if(typeof statusModule.j!=='function')throw new Error('Status export changed');
 const response=await statusModule.j();
 const authoritative=String(response.code)==='0'&&response.data?{businessDate:String(response.data.businessDate||'').slice(0,10),recordStatus:response.data.recordStatusCode,abnormalFlag:!!response.data.abnormalFlag}:{};
 return {...(unique[0]||{}),...authoritative,statusReadCode:String(response.code),map,mapMatches:!!map&&Math.abs(map.latitude-${config.location.gcj02[1]})<1e-7&&Math.abs(map.longitude-${config.location.gcj02[0]})<1e-7,locationActive:!!window.__codexCheckinLocation,hasTicket:!!sessionStorage.getItem('daily-checkin-operation-ticket'),hasSubmit:circles.length===1,authRequired:['401','403'].includes(String(response.code))||/验证码|二次验证|登录已失效|请重新登录|身份认证失败/.test(text),notices,schoolResponse:window.__codexCheckinResponses.filter(x=>x.code!=='0').slice(-3)};
})()`;
async function withSchool(fn){const t=(await client.targets()).filter(t=>t.type==='webview'&&t.url.startsWith(ORIGIN+'/daily-checkin-h5/'));if(t.length!==1)throw new Error('CHECKIN_PAGE_NOT_UNIQUE');const sid=await client.attach(t[0]);try{return await fn(sid)}finally{await client.detach(sid)}}
async function snapshot(sid){return client.evaluate(sid,pageSnapshot);}
async function open(){const t=(await client.targets()).filter(t=>t.type==='page'&&t.url.startsWith('https://servicewechat.com/'+APP+'/'));if(t.length!==1)throw new Error('MINIAPP_NOT_OPEN');const sid=await client.attach(t[0]);try{
 await client.evaluate(sid,`(()=>{${walkSource}const a=allNodes().filter(e=>e.tagName==='WX-VIEW'&&e.classList.contains('app-item')&&e.textContent.trim()==='晚安成电');if(a.length!==1)throw new Error('Named app entry not unique');a[0].scrollIntoView({block:'center'});return true})()`);
 await pause(400);
 const point=await client.evaluate(sid,`(()=>{${walkSource}const a=allNodes().filter(e=>e.tagName==='WX-VIEW'&&e.classList.contains('app-item')&&e.textContent.trim()==='晚安成电');if(a.length!==1)throw new Error('Named app entry not unique');const e=a[0],r=e.getBoundingClientRect();let x=r.x+r.width/2,y=r.y+r.height/2,w=e.ownerDocument.defaultView;for(let i=0;i<8&&w.frameElement;i++){const f=w.frameElement.getBoundingClientRect();x+=f.x;y+=f.y;w=w.parent;}if(x<0||y<0||x>=innerWidth||y>=innerHeight)throw new Error('Entry outside viewport');return {x,y};})()`);
 await client.request('Input.dispatchMouseEvent',{type:'mouseMoved',...point},sid);
 await client.request('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point},sid);
 await client.request('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point},sid);
 const result={opened:true};
 await pause(1000);
 for(let i=0;i<40;i++){await pause(500);if((await client.targets()).some(t=>t.type==='webview'&&t.url.startsWith(ORIGIN+'/daily-checkin-h5/')))return result;}
 throw new Error('OPEN_CHECKIN_TIMEOUT');
 }finally{await client.detach(sid)}}
function atomic(p,value){const t=p+'.tmp';const fd=fs.openSync(t,'w',0o600);try{fs.writeFileSync(fd,JSON.stringify(value,null,2)+'\n');fs.fsyncSync(fd)}finally{fs.closeSync(fd)}fs.renameSync(t,p);const dir=fs.openSync(require('node:path').dirname(p),'r');try{fs.fsyncSync(dir)}finally{fs.closeSync(dir)}}
async function submit(){return withSchool(async sid=>{
 const now=beijing(),day=now.slice(0,10);const initial=await snapshot(sid);const verdict=decide(initial,day,now);
 if(verdict!=='READY')return {verdict,snapshot:initial,submitted:false};
 const ledger='/var/lib/wechat-checkin/'+day+'.json';const old=fs.existsSync(ledger)?JSON.parse(fs.readFileSync(ledger)):{};
 if(old.confirmIntent||['success','already_done','exempt'].includes(old.outcome))return {verdict:'DUPLICATE_GUARD',submitted:false};
 await client.evaluate(sid,`(()=>{${walkSource}const a=allNodes().filter(e=>e.classList?.contains('check-in-circle')&&!e.classList.contains('disabled')&&e.textContent.trim()==='请打卡'&&visible(e));if(a.length!==1)throw new Error('Unique check-in button missing');a[0].click();return true})()`);
 let confirmation=false;
 for(let i=0;i<20;i++){await pause(200);confirmation=await client.evaluate(sid,`(()=>{${walkSource}const a=allNodes().filter(e=>visible(e)&&e.textContent?.includes('确认打卡')&&e.textContent?.includes('是否确认打卡？'));return a.length>0})()`);if(confirmation)break;}
 if(!confirmation)throw new Error('CONFIRMATION_DIALOG_MISSING');
 const checked=await snapshot(sid);const decision=decide({...checked,hasSubmit:true},day,beijing());
 // Opening the confirmation dialog can cover the submit button. Recheck every other guard.
 if(decision!=='READY')throw new Error(decision);
 const picked=await client.evaluate(sid,`(()=>{${walkSource}const all=allNodes();const containers=all.filter(e=>visible(e)&&e.textContent?.includes('确认打卡')&&e.textContent?.includes('是否确认打卡？')).sort((a,b)=>a.textContent.length-b.textContent.length);
  for(const root of containers){const candidates=[...root.querySelectorAll('button,uni-button,.wd-button')].filter(e=>visible(e)&&['确定','确认'].includes(e.textContent.trim()));const unique=[...new Set(candidates.map(e=>e.closest('button,uni-button')||e))];if(unique.length===1){window.__codexCheckinConfirmButton=unique[0];return true;}}return false;})()`);
 if(!picked)throw new Error('CONFIRM_BUTTON_NOT_UNIQUE');
 // Durable intent precedes the only action that can send the school submission.
 atomic(ledger,{...old,day,phase:'confirming',confirmIntent:true,confirmedAt:beijing(),outcome:'unknown'});
 await client.evaluate(sid,`(()=>{const e=window.__codexCheckinConfirmButton;if(!e||!e.isConnected)throw new Error('Confirm disappeared');e.click();delete window.__codexCheckinConfirmButton;return true})()`);
 let last;
 for(let i=0;i<15;i++){await pause(1500);last=await snapshot(sid);if(last.businessDate===day&&last.recordStatus==='CHECKED_IN')return {verdict:'SUCCESS',submitted:true,snapshot:last};if(last.authRequired)break;}
 return {verdict:'RESULT_UNCONFIRMED',submitted:true,snapshot:last};
})}
async function main(){const action=process.argv[2];if(action==='logic-selftest')return;await client.connect();if(action==='open')return open();if(action==='inspect')return withSchool(snapshot);if(action==='submit')return submit();throw new Error('UNKNOWN_ACTION');}
if(require.main===module){main().then(r=>console.log(JSON.stringify({ok:true,result:r}))).catch(e=>{console.log(JSON.stringify({ok:false,error:/^[A-Z0-9_.]+$/.test(e.message)?e.message:'AUTOMATION_ERROR'}));process.exitCode=1}).finally(()=>client.close());}
