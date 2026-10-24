import fs from 'node:fs';
import {doOp} from '../../gotv-parser-audit/src/parser/entities/fieldPathOps.ts';
import {BitBuffer} from '../../gotv-parser-audit/src/parser/ubitreader.ts';
const rows=[];
for(let op=0;op<40;op++)for(let depth=1;depth<=10;depth++)for(let first=0;first<16;first++){
 const bytes=new Uint8Array(64);bytes[0]=first;
 const initial=Array.from({length:depth},(_,i)=>10+i*10);
 const field={path:[...initial,...Array(12-depth).fill(0)],last:depth-1};
 const reader=new BitBuffer(bytes);
 try{doOp(op,reader,field);}catch{continue;}
 const out=field.path.slice(0,field.last+1);
 if((op===37 && depth<2) || (op!==39 && (field.last<0 || out.length<1||out.length>10||out.some(x=>!Number.isInteger(x)||x<0||x>=32767))))continue;
 rows.push({op,initial,first,expected:out,bits:reader._byteOffset*8-reader._bitsAvail});
}
fs.writeFileSync('.agent-tmp/gotv-research-plan/field-path-depth-model-cases.json',JSON.stringify(rows));console.log(rows.length);
