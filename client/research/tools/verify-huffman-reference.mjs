import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
if(!process.argv[2])throw new Error('Supply bundled pinned fieldPaths module');
const {fillHuffmanTables}=await import(pathToFileURL(resolve(process.argv[2])).href);
const root='.agent-tmp/gotv-research-plan/';
const native=JSON.parse(fs.readFileSync(root+'huffman-codebook-authority.json','utf8'));
assert.equal(native.matched_codewords,40);
const primary=new Uint16Array(256),long=new Uint16Array(1<<17);
fillHuffmanTables(primary,long);
let tested=0;
for(let bits=0;bits<(1<<17);bits++){
  let node=0,depth=0;
  while(node>=0){assert.ok(depth<17);node=native.decoder_table[node][(bits>>>depth++)&1];}
  const symbol=~node,expected=(depth<<6)|symbol;
  assert.equal(primary[bits&255]||long[bits],expected,`prefix ${bits}`);
  tested++;
}
const result={prefixes:tested,matched:tested,codewords:40,maximumBits:17,
  scope:'Actual pinned TypeScript Huffman LUT versus fixed-native-derived decoder table; no source opcode, runtime integration or live acceptance implied.'};
fs.writeFileSync(root+'huffman-reference-comparison.json',JSON.stringify(result,null,2)+'\n');
console.log(result);
