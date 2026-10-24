// Ordered fixed-profile data-plane worker. No sockets, credentials or commands.
// Bundled explicitly by the cohesive build; the legacy worker is not selected here.
import process from 'node:process';
import {NativeObserverCore} from 'cs2parser/observer-core';
const MAX_LINE=8*1024**2,MAX_BODY=4*1024**2;
let core;
const send=record=>{
 const line=JSON.stringify(record)+'\n';
 if(Buffer.byteLength(line)>65536||process.stdout.writableLength+Buffer.byteLength(line)>8*1024**2)
  throw new Error('ordered-parser-output-budget');
 process.stdout.write(line);
};
const identity=row=>({source:row.source,channel:row.channel,world:row.world});
const verifyIdentity=row=>{
 const current=core.currentIdentity;
 if(row.source!==current.source||row.channel!==current.channel||row.world!==current.world)
  throw new Error('ordered-parser-control-generation');
};
const consume=row=>{
 if(!row||typeof row!=='object'||Array.isArray(row))throw new Error('ordered-parser-record-shape');
 if(row.type==='init'){
  if(core)throw new Error('ordered-parser-already-initialized');
  core=new NativeObserverCore(identity(row));send({type:'initialized',protocol:3,...core.currentIdentity});return;
 }
 if(!core)throw new Error('ordered-parser-not-initialized');
 if(row.type==='reset-world'){
  core.resetWorld(identity(row));send({type:'world-reset',...core.currentIdentity,reason:'parent-world-boundary'});return;
 }
 verifyIdentity(row);
 if(row.type==='admit-creation-sequence'){
  core.admitCreationSequence(row.creationSequence);
  send({type:'creation-sequence-admitted',...core.currentIdentity,creationSequence:row.creationSequence});return;
 }
 if(row.type!=='message'||typeof row.bodyBase64!=='string'||row.bodyBase64.length>Math.ceil(MAX_BODY/3)*4||
  row.bodyBase64.length%4!==0)
  throw new Error('ordered-parser-message-shape');
 const body=Buffer.from(row.bodyBase64,'base64');
 if(body.length>MAX_BODY||body.toString('base64')!==row.bodyBase64)throw new Error('ordered-parser-body-budget-or-encoding');
 for(const record of core.consume({...identity(row),sequence:row.sequence,messageId:row.messageId,body,contextTick:row.contextTick}))send(record);
};
process.stdout.on('error',()=>{process.exitCode=1;process.stdin.destroy();});
process.once('SIGTERM',()=>{process.stdin.destroy();});
let pending=Buffer.alloc(0);
try{
 for await(const chunk of process.stdin){
  pending=Buffer.concat([pending,chunk]);
  let start=0,end;
  while((end=pending.indexOf(10,start))!==-1){
   const line=pending.subarray(start,end);if(line.length>MAX_LINE)throw new Error('ordered-parser-input-budget');if(!line.length)throw new Error('ordered-parser-empty-record');
   consume(JSON.parse(line.toString('utf8')));start=end+1;
  }
  pending=pending.subarray(start);
  if(pending.length>MAX_LINE)throw new Error('ordered-parser-input-budget');
 }
 if(pending.length)throw new Error('ordered-parser-truncated-record');
 send({type:'end',status:'complete',...(core?.currentIdentity??{})});
}catch(error){
 process.exitCode=1;
 try{send({type:'error',code:'ordered-parser-failed',message:String(error?.message??error).slice(0,1024),...(core?.currentIdentity??{})});}catch{}
}
