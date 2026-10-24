// Minimal private owner. Feed one JSON configuration line to stdin and keep it open.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';

export class Consumer {
 constructor(source){this.source=source;this.sequence=0;this.world=1;this.ready=false;}
 accept(row){
  if(row.source!==this.source||row.channel!==1)throw new Error('source-owner-mismatch');
  if(!Number.isSafeInteger(row.sequence)||row.sequence<=this.sequence)throw new Error('record-order');
  this.sequence=row.sequence;
  if(!Number.isSafeInteger(row.world)||row.world<this.world)return;
  if(row.kind==='discontinuity'){this.world=row.world;this.ready=false;}
  else if(row.kind==='cursor'&&row.world===this.world)this.ready=Number.isSafeInteger(row.tick)&&row.tick>0&&typeof row.map==='string'&&row.map.length>0&&Number.isFinite(row.tickInterval)&&row.tickInterval>0&&row.tickInterval<=1;
  else if(row.type==='raw-event'&&this.ready&&row.world===this.world)return row;
 }
}

async function main(){
 const args=process.argv.slice(2);
 const get=name=>{const i=args.indexOf(name);if(i<0)throw new Error('Required '+name);return args[i+1];};
 if(args.includes('--help')){console.log('node managed_consumer.mjs --package DIR --steam-api FILE --host-version NUMBER [--node FILE]');return;}
 const root=path.resolve(get('--package')),manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
 const entry=name=>{const p=path.resolve(root,manifest.entrypoints[name]);if(path.relative(root,p).startsWith('..'))throw new Error('artifact-entrypoint');return p;};
 if(process.env.SteamAppId&&process.env.SteamAppId!=='730')throw new Error('Steam-context');
 const id=randomUUID().replaceAll('-',''),state=new Consumer('ahead:'+id);
 const output=path.join(fs.mkdtempSync(path.join(os.tmpdir(),'observer-consumer-')),id);
 const supplied=args.indexOf('--node'),node=supplied>=0?args[supplied+1]:(fs.existsSync(path.join(root,'runtime/node.exe'))?path.join(root,'runtime/node.exe'):'node');
 const child=spawn(entry('python'),['-B',entry('driver'),'--managed','--native',entry('native'),'--steam-api',path.resolve(get('--steam-api')),
  '--node',node,'--parser-worker',entry('worker'),'--host-version',get('--host-version'),'--source-role','ahead','--source-id',id,'--output',output],
  {env:{...process.env,SteamAppId:'730'},windowsHide:true,stdio:['pipe','pipe','ignore']});
 const closed=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',resolve);});
 let configured=false,configuration=Buffer.alloc(0);
 const stop=()=>{state.ready=false;child.stdin.end();};
 child.stdin.on('error',()=>{state.ready=false;});
 process.on('SIGINT',stop);
 process.stdin.on('data',chunk=>{
  if(configured){stop();return;}
  configuration=Buffer.concat([configuration,chunk]);
  if(configuration.length>4096){stop();return;}
  const end=configuration.indexOf(10);if(end<0)return;
  try{
   const row=JSON.parse(configuration.subarray(0,end).toString('utf8'));
   child.stdin.write(JSON.stringify({endpoint:row.endpoint,password:row.password})+'\n');configured=true;
   if(end+1<configuration.length)stop();configuration.fill(0);configuration=Buffer.alloc(0);
  }catch{stop();}
 });
 process.stdin.on('end',stop);
 let pending=Buffer.alloc(0);const decoder=new TextDecoder('utf-8',{fatal:true});
 const consume=(line)=>{if(line.length+1>65536)throw new Error('record-budget');const event=state.accept(JSON.parse(decoder.decode(line)));
  if(event)console.log(JSON.stringify({kind:event.kind,eventServerTick:event.eventServerTick}));};
 try{
  for await(const chunk of child.stdout){
   let start=0,end;
   while((end=chunk.indexOf(10,start))>=0){const part=chunk.subarray(start,end);consume(pending.length?Buffer.concat([pending,part]):part);pending=Buffer.alloc(0);start=end+1;}
   const tail=chunk.subarray(start);if(pending.length+tail.length>=65536)throw new Error('record-budget');pending=Buffer.concat([pending,tail]);
  }
  if(pending.length)throw new Error('truncated-record');
 }finally{
  stop();const timer=setTimeout(()=>child.kill('SIGKILL'),15000);
  try{await closed;}finally{clearTimeout(timer);process.stdin.destroy();process.removeListener('SIGINT',stop);}
  console.error('Private report: '+path.join(output,'report.json'));
 }
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)await main();
