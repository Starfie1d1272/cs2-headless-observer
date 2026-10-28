import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {projectNativeEvent,projectRoundClock}=await import(pathToFileURL(resolve(process.argv[2])).href);
const steam='76561198000000123',serial=100000,pawn=3000;
const values=object=>({*entries(){for(const [name,value] of Object.entries(object))yield {field:{name},operation:'value',value};}});
const entities=new Map([[1,{id:1,classId:0,serial:1,fields:values({m_steamID:BigInt(steam),m_hPlayerPawn:pawn|((serial&1023)<<14)})}],
 [pawn,{id:pawn,classId:1,serial,fields:values({})}],[10,{id:10,classId:2,serial:1,fields:values({m_bWarmupPeriod:true,m_totalRoundsPlayed:3})}]]);
const schema={getClass:id=>({name:['CCSPlayerController','CCSPlayerPawn','CCSGameRulesProxy'][id]})};
const snapshots={waitingFull:false,getEntity:id=>entities.get(id),*entries(){yield* entities.values();}};
const fixed64=n=>Array.from({length:8},(_,i)=>Number((BigInt(n)>>BigInt(i*8))&255n));
let info=Uint8Array.of(17,...fixed64(steam));
const tables={entryByName:(name,slot)=>slot===0?{value:info}:undefined};
const types=new Map([['userid',9],['userid_pawn',8]]),fields={userid:0,userid_pawn:(serial*32768+pawn)|0,weapon:'ak47'};
const project=()=>projectNativeEvent(schema,snapshots,tables,'weapon_fire',fields,types);
let checks=0;const check=f=>{f();checks++;};
check(()=>assert.equal(project().actor,steam));check(()=>assert.equal(project().warmup,true));check(()=>assert.equal(project().round,3));
check(()=>assert.equal(project().identityResolved,true));
entities.get(10).fields=values({m_totalRoundsPlayed:3,m_fRoundStartTime:12.5,m_iRoundTime:115,m_bFreezePeriod:false,m_bWarmupPeriod:false,m_bBombPlanted:false,m_bGamePaused:false,m_nTotalPausedTicks:0,m_nPauseStartTick:0,m_bTechnicalTimeOut:false,m_bRoundInProgress:true,m_iRoundWinStatus:2});
let clock=projectRoundClock(schema,snapshots,100);
check(()=>assert.deepEqual(clock,{totalRoundsPlayed:3,phase:'unknown',startTime:12.5,duration:115,committedTick:100,freezePeriod:false,warmupPeriod:false,bombPlanted:false,roundInProgress:true,roundWinStatus:2,pause:{active:false,totalPausedTicks:0,startTick:0,technical:false,semantics:'unknown'},status:'available'}));
entities.get(10).fields=values({m_bWarmupPeriod:false,m_bFreezePeriod:true});
check(()=>assert.equal(projectRoundClock(schema,snapshots,101).phase,'freezetime'));
check(()=>assert.equal(projectRoundClock(schema,snapshots,101).status,'partial'));
snapshots.waitingFull=true;clock=projectRoundClock(schema,snapshots,102);
check(()=>assert.equal(clock.status,'unavailable'));check(()=>assert.equal(clock.startTime,null));snapshots.waitingFull=false;
entities.get(10).fields=values({m_bWarmupPeriod:true,m_totalRoundsPlayed:3});
const originalControllerFields=entities.get(1).fields;
entities.get(1).fields={*entries(){yield* originalControllerFields.entries();yield {field:{name:'m_steamID'},operation:'value',value:BigInt(steam)};}};
check(()=>assert.equal(project().actor,null));
entities.get(1).fields=originalControllerFields;
check(()=>assert.deepEqual(project().pawns.userid,{index:pawn,serial}));
check(()=>assert.deepEqual(project().players.userid,{domain:'player-controller-slot',slot:0,steamId:steam,userId:null,controller:{index:1,serial:1}}));
info=Uint8Array.of(17,...fixed64(steam),24,42);
check(()=>assert.equal(project().players.userid.userId,42));
check(()=>assert.equal(project().players.userid.slot,0));
check(()=>assert.equal(projectNativeEvent(schema,snapshots,tables,'player_hurt',fields,types).players.userid.steamId,steam));
check(()=>assert.equal(Object.isFrozen(project().players.userid.controller),true));
entities.get(1).fields=values({m_steamID:BigInt(steam),m_hPlayerPawn:BigInt(pawn|((serial&1023)<<14))});
entities.get(10).fields=values({m_bWarmupPeriod:true,m_totalRoundsPlayed:3n});
check(()=>assert.equal(project().actor,steam));check(()=>assert.equal(project().round,3));
entities.get(1).fields=values({m_steamID:BigInt(steam),m_hPlayerPawn:0x100000000n});
check(()=>assert.equal(project().actor,steam));check(()=>assert.equal(project().pawns.userid,null));
entities.get(1).fields=values({m_steamID:BigInt(steam),m_hPlayerPawn:BigInt(pawn|((serial&1023)<<14))});
info=Uint8Array.of(17,...fixed64(steam));
const original=fields.userid_pawn;fields.userid_pawn=((serial-1024)*32768+pawn)|0;
check(()=>assert.equal(project().actor,steam));check(()=>assert.equal(project().pawns.userid,null)); // Same compressed10-bit serial, different native17-bit identity remains unresolved.
fields.userid_pawn=original;entities.get(pawn).serial++;
check(()=>assert.equal(project().actor,steam));check(()=>assert.equal(project().pawns.userid,null));entities.get(pawn).serial--;
fields.userid_pawn=-1;check(()=>assert.equal(project().actor,steam));check(()=>assert.equal(project().pawns.userid,null));fields.userid_pawn=original;
info=Uint8Array.of(17,...fixed64('76561198000000456'));check(()=>assert.equal(project().actor,null));info=Uint8Array.of(17,...fixed64(steam));
info=new Uint8Array();check(()=>assert.equal(project().actor,null));check(()=>assert.equal(project().pawns.userid,null));
info=Uint8Array.of(17,...fixed64(steam));
fields.userid=65535;check(()=>assert.equal(project().actor,null));fields.userid=0;
types.set('userid',4);check(()=>assert.equal(project().actor,null));types.set('userid',9);
snapshots.waitingFull=true;check(()=>assert.equal(project().actor,null));check(()=>assert.equal(project().round,null));check(()=>assert.equal(project().pawns.userid,null));snapshots.waitingFull=false;
const prior=project();entities.get(1).fields=values({m_steamID:123n});check(()=>assert.equal(project().actor,null));check(()=>assert.equal(prior.actor,steam));
for(const id of ['76561200000000000','76561202255233023']){
 entities.get(1).fields=values({m_steamID:BigInt(id)});info=Uint8Array.of(17,...fixed64(id));
 check(()=>assert.equal(project().actor,id));check(()=>assert.equal(project().identityResolved,true));
}
for(const id of ['76561197960265728','9007199254740991','18446744073709551616']){
 entities.get(1).fields=values({m_steamID:BigInt(id)});info=Uint8Array.of(17,...fixed64(id));
 check(()=>assert.equal(project().actor,null));
}
const output={checks,passed:true,scope:'Independent controller and strict full native pawn identity; distinct17/10-bit serial domains and unknown fallback; synthetic fixtures only'};
fs.writeFileSync(process.env.GOTV_RESULT_ROOT+'native-event-projection-comparison.json',JSON.stringify(output,null,2)+'\n');console.log(output);
