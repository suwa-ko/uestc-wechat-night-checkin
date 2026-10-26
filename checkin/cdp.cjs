'use strict';
const fs=require('node:fs');
const path=require('node:path');
const prepared=JSON.parse(fs.readFileSync('/opt/uestc-wechat/runtime/wmpf-debugger/prepared.json'));
const WebSocket=require(path.join(prepared.source_dir,'node_modules/ws'));
class CDP {
 constructor(){this.ws=new WebSocket('ws://127.0.0.1:62000');this.id=Date.now()%100000000;this.pending=new Map();this.ws.on('message',b=>{let m;try{m=JSON.parse(b)}catch{return}const p=this.pending.get(m.id);if(p){clearTimeout(p.timer);this.pending.delete(m.id);m.error?p.reject(new Error('CDP_'+p.method)):p.resolve(m.result||{})}});}
 async connect(){await new Promise((r,j)=>{const t=setTimeout(()=>j(new Error('DEBUGGER_CONNECTION_TIMEOUT')),8000);this.ws.once('open',()=>{clearTimeout(t);r()});this.ws.once('error',()=>{clearTimeout(t);j(new Error('DEBUGGER_CONNECTION_FAILED'))})});}
 request(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++this.id;const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('CDP_TIMEOUT_'+method.toUpperCase()))},10000);this.pending.set(id,{resolve,reject,timer,method});this.ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}))})}
 async targets(){return (await this.request('Target.getTargets')).targetInfos||[];}
 async attach(target){return (await this.request('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;}
 async evaluate(sessionId,expression){const r=await this.request('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},sessionId);if(r.exceptionDetails)throw new Error('PAGE_EVALUATION_FAILED');return r.result?.value;}
 async detach(sessionId){await this.request('Target.detachFromTarget',{sessionId}).catch(()=>{});}
 close(){for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error('CDP_CLOSED'))}this.pending.clear();this.ws.terminate();}
}
const walkSource=`function allNodes(root=document){const out=[];for(const e of root.querySelectorAll('*')){out.push(e);if(e.shadowRoot)out.push(...allNodes(e.shadowRoot));if(e.tagName==='IFRAME'){try{if(e.contentDocument)out.push(...allNodes(e.contentDocument))}catch{}}}return out;}
function visible(e){const r=e.getBoundingClientRect();const s=e.ownerDocument.defaultView.getComputedStyle(e);if(r.width<=0||r.height<=0||s.visibility==='hidden'||s.display==='none')return false;let p=e;while(p&&p.nodeType===1){const t=p.ownerDocument.defaultView.getComputedStyle(p);if(t.display==='none'||t.visibility==='hidden'||t.opacity==='0')return false;p=p.parentElement;}return true;}`;
module.exports={CDP,walkSource};
