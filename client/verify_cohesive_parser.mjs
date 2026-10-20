// Reproducible component checks against the SAME patched source used by the worker.
import process from 'node:process';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdtempSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {execFileSync} from 'node:child_process';
const here=dirname(fileURLToPath(import.meta.url));
if(!process.argv[2])throw new Error('Expected patched parser source');
const source=resolve(process.argv[2]);
const esbuild=createRequire(resolve(here,'../package.json'))('esbuild');
const directory=mkdtempSync(resolve(tmpdir(),'gotv-cohesive-verification-'));
const entry=resolve(directory,'entry.ts'),bundle=resolve(directory,'checks.mjs');
const modules=['src/parser/ubitreader.ts','src/parser/entities/nativeFieldPaths.ts',
 'src/parser/entities/nativeSchema.ts','src/parser/entities/nativeEntityFields.ts',
 'src/parser/entities/nativeSnapshotState.ts','src/parser/entities/nativePacketEntities.ts',
 'src/parser/entities/nativeStringTables.ts','src/parser/entities/nativeObserverCore.ts',
 'src/parser/entities/nativeEventProjection.ts','src/compression/wasm.ts',
 'src/ts-proto/netmessages.ts','src/ts-proto/networkbasetypes.ts','src/ts-proto/gameevents.ts'];
writeFileSync(entry,modules.map(path=>'export * from '+JSON.stringify(resolve(source,path))+';').join('\n'));
await esbuild.build({entryPoints:[entry],bundle:true,platform:'node',format:'esm',target:'node24',outfile:bundle});
const evidence=process.env.GOTV_RESEARCH_ROOT??resolve(here,'research')+'/';
for(const name of ['path-reader','entity-fields','snapshots','packets','tables','projection','core']){
 execFileSync(process.execPath,[resolve(evidence,'tools','verify-native-'+name+'.mjs'),bundle],
  {stdio:'inherit',env:{...process.env,GOTV_RESEARCH_ROOT:evidence}});
}
