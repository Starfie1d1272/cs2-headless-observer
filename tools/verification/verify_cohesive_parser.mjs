// Reproducible component checks against the SAME patched source used by the worker.
import process from 'node:process';
import {createRequire} from 'node:module';
import {dirname,resolve,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdirSync,writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
const here=dirname(fileURLToPath(import.meta.url));
const repo=resolve(here,'../..');
if(!process.argv[2]||!process.argv[3])throw new Error('Expected patched parser source and NEW output directory');
const source=resolve(process.argv[2]);
const esbuild=createRequire(resolve(repo,'package.json'))('esbuild');
const directory=resolve(process.argv[3]);
if(['research','docs','archive','tests','client','native','patches','tools'].some(name=>{
 const path=resolve(repo,name);return directory===path||directory.startsWith(path+sep);
}))throw new Error('Output must be outside source and evidence directories');
mkdirSync(directory,{recursive:false});
const entry=resolve(directory,'entry.ts'),bundle=resolve(directory,'checks.mjs');
const modules=['src/parser/ubitreader.ts','src/parser/entities/nativeFieldPaths.ts',
 'src/parser/entities/nativeSchema.ts','src/parser/entities/nativeEntityFields.ts',
 'src/parser/entities/nativeSnapshotState.ts','src/parser/entities/nativePacketEntities.ts',
 'src/parser/entities/nativeStringTables.ts','src/parser/entities/nativeObserverCore.ts',
 'src/parser/entities/nativeEventProjection.ts','src/compression/wasm.ts',
 'src/ts-proto/netmessages.ts','src/ts-proto/networkbasetypes.ts','src/ts-proto/gameevents.ts'];
writeFileSync(entry,modules.map(path=>'export * from '+JSON.stringify(resolve(source,path))+';').join('\n'));
await esbuild.build({entryPoints:[entry],bundle:true,platform:'node',format:'esm',target:'node24',outfile:bundle});
for(const name of ['path-reader','entity-fields','snapshots','packets','tables','projection','core']){
 execFileSync(process.execPath,[resolve(repo,'tests/parser/verify-native-'+name+'.mjs'),bundle],
  {stdio:'inherit',env:{...process.env,GOTV_FIXTURE_ROOT:resolve(repo,'research/data')+'/',GOTV_RESULT_ROOT:directory+'/'}});
}
