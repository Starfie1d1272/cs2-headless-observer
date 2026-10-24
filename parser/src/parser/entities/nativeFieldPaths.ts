import type {BitBuffer} from '../ubitreader.js';
import {doOp, popSpecial, type FieldPath} from './fieldPathOps.js';
import {fillHuffmanTables} from './fieldPaths.js';

const primary=new Uint16Array(256);
const long=new Uint16Array(1<<17);
fillHuffmanTables(primary,long);
const maxDepth=10;
const fixedPush=new Map<number,number>([
  ...Array.from({length:8},(_,i)=>[i+5,1] as const),
  [13,2],[14,2],[15,3],[16,3],[17,2],[18,2],[19,3],[20,3],
  [21,2],[22,2],[23,3],[24,3],
]);

export function createNativePathState():FieldPath {
  // The legacy public type is a seven-element tuple; its proven opcode
  // functions work on an array. This ordinary-viewer state has native depth10.
  const path=new Array<number>(maxDepth).fill(0) as unknown as FieldPath['path'];
  path[0]=-1;
  return {path,last:0};
}
function requirePush(state:FieldPath,count:number) {
  if(!Number.isInteger(count)||count<0||state.last+1+count>maxDepth)
    throw new Error('Field path depth overflow');
}
function requirePop(state:FieldPath,count:number) {
  if(!Number.isInteger(count)||count<0||count>state.last)
    throw new Error('Field path depth underflow');
}

/** Reuse verified opcode arithmetic, adding bounded variable-depth handling. */
export function applyNativePathOperation(op:number,reader:BitBuffer,state:FieldPath):void {
  if(!Number.isInteger(state.last)||state.last<0||state.last>=maxDepth||state.path.length<maxDepth)
    throw new Error('Invalid field path state');
  if(!Number.isInteger(op)||op<0||op>39)throw new Error('Invalid field path opcode');
  if(op===39) {
    state.path.fill(0);state.path[0]=32767;state.last=0;return;
  }
  const push=fixedPush.get(op);
  if(push!==undefined)requirePush(state,push);
  if(op===27||op===28||op===37)requirePop(state,1);
  if(op===25) {
    const count=reader.readUbitVar();
    requirePush(state,count);
    state.path[state.last]!+=reader.readUbitVar();
    for(let i=0;i<count;i++)state.path[++state.last]!+=reader.readUbitVarFp();
  } else if(op===26) {
    for(let i=0;i<=state.last;i++)
      if(reader.readBoolean())state.path[i]!+=reader.readVarInt32()+1;
    const count=reader.readUbitVar();
    requirePush(state,count);
    for(let i=0;i<count;i++)state.path[++state.last]=reader.readUbitVarFp();
  } else if(op>=33&&op<=35) {
    const count=reader.readUbitVarFp();
    requirePop(state,count);popSpecial(state,count);
    if(op===33)state.path[state.last]!+=1;
    else if(op===34)state.path[state.last]!+=reader.readVarInt32();
    else for(let i=0;i<=state.last;i++)
      if(reader.readBoolean())state.path[i]!+=reader.readVarInt32();
  } else {
    doOp(op,reader,state);
  }
  if(state.last<0||state.last>=maxDepth)throw new Error('Invalid field path depth');
  for(let i=0;i<=state.last;i++) {
    const value=state.path[i]!;
    if(!Number.isSafeInteger(value))throw new Error('Invalid field path component');
    // Native CFieldPath stores signed16 components. Final schema resolution,
    // not arithmetic success alone, decides whether the wrapped path is valid.
    state.path[i]=(value<<16)>>16;
  }
}

/**
 * Decode a complete field list before exposing it. Budgets are observer policy;
 * failure discards the list and its owning entity/snapshot transaction.
 */
export function readNativeFieldPaths(reader:BitBuffer,maxPaths=65536,bitBudget=reader.RemainingBits):readonly (readonly number[])[] {
  if(!Number.isSafeInteger(maxPaths)||maxPaths<0||maxPaths>1_000_000)
    throw new Error('Invalid field-list budget');
  const initialBits=reader.RemainingBits;
  if(!Number.isSafeInteger(bitBudget)||bitBudget<0||bitBudget>initialBits)
    throw new Error('Invalid field-list bit boundary');
  const state=createNativePathState();
  const result:(readonly number[])[]=[];
  while(true) {
    const prefix=reader.peekHuffmanPrefix();
    const code=primary[prefix]||long[reader.peekHuffmanCode()]!;
    const width=code>>>6,op=code&63;
    if(width<1||width>17||op>39)throw new Error('Invalid Huffman field path');
    if(initialBits-reader.RemainingBits+width>bitBudget)throw new Error('Truncated field-list code');
    reader.consumePeeked(width);
    applyNativePathOperation(op,reader,state);
    if(initialBits-reader.RemainingBits>bitBudget)throw new Error('Truncated field-list payload');
    // PlusN can reach the same root sentinel as explicit opcode39.
    if(state.path[0]===32767)return Object.freeze(result);
    const path=state.path.slice(0,state.last+1);
    if(path.some(value=>value<0||value>32767))throw new Error('Invalid resolved field path');
    if(result.length>=maxPaths)throw new Error('Field-list budget exceeded');
    result.push(Object.freeze(path));
  }
}
