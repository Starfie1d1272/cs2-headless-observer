import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const root='.agent-tmp/gotv-research-plan/';
const readerPath='.agent-tmp/gotv-parser-audit/src/parser/ubitreader.ts';
if(createHash('sha256').update(readFileSync(readerPath)).digest('hex')!=='bb314d2f45692f90cdc23c48a5a555d79c88497b0e201a30465b2ddace877bbb')throw new Error('pinned-reader-source-mismatch');
const {BitBuffer}=await import(pathToFileURL(process.cwd()+'/.agent-tmp/gotv-parser-audit/src/parser/ubitreader.ts'));
const {decodeNativeQuantized}=await import(new URL('./native-quantized-model.ts',import.meta.url));
const data=JSON.parse(readFileSync(root+'quantized-configured-read-vectors.json'));const failures=[];
for(const c of data.cases){
 const config=data.configs[c.config],b=Buffer.from(config.config_hex,'hex');
 const q={raw:config.raw,bits:config.effective_bits,low:config.configured_low,high:config.configured_high,flags:config.effective_flags,multiplier:b.readDoubleLE(8),decodeMultiplier:config.dec_mul,cellRangeBits:b[30]>>>2};
 const input=Buffer.from(c.input_hex,'hex'),reader=new BitBuffer(input),out=Buffer.alloc(c.dimension*4);
 for(let i=0;i<c.dimension;i++)out.writeFloatLE(decodeNativeQuantized(reader,q),i*4);
 const consumed=input.length*8-reader.RemainingBits;
 if(out.toString('hex')!==c.native_hex||consumed!==c.native_bits)failures.push({...c,actual_hex:out.toString('hex'),actual_bits:consumed});
}
const result={cases:data.cases.length,matched:data.cases.length-failures.length,failures:failures.slice(0,20),model_sha256:createHash('sha256').update(readFileSync(new URL('./native-quantized-model.ts',import.meta.url))).digest('hex'),scope:'isolated scalar decode model against saved fixed-binary output; not runtime integration'};
writeFileSync(root+'quantized-configured-read-comparison.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));if(failures.length)process.exitCode=1;
