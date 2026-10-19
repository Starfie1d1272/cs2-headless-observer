import process from 'node:process';
import { createRequire } from 'node:module';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import {
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';

const upstream = 'deced963b86d3ec26b28a225824130fdf9fe3167';
const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '..');
const [sourceArg, outputArg] = process.argv.slice(2);
if (!sourceArg || !outputArg)
  throw new Error('Expected pinned parser source directory and output file');
const source = resolve(sourceArg);
if (
  execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== upstream
) {
  throw new Error('Unexpected parser source commit');
}
const patch = resolve(here, 'cs2parser-online.patch');
execFileSync('git', ['-C', source, 'apply', '--check', '--unidiff-zero', patch]);
execFileSync('git', ['-C', source, 'apply', '--unidiff-zero', patch]);
if (!readFileSync(resolve(source, 'src/index.ts'), 'utf8').includes('ordinaryViewerProtocol = 2')) {
  throw new Error('Online parser capability is missing');
}
const telemetry = createRequire(resolve(repo, 'package.json'));
const esbuild = telemetry('esbuild');
const parser = createRequire(telemetry.resolve('cs2parser/package.json'));
let protobufModules = dirname(parser.resolve('@bufbuild/protobuf'));
while (basename(protobufModules) !== 'node_modules') {
  const parent = dirname(protobufModules);
  if (parent === protobufModules) throw new Error('Cannot locate the locked protobuf dependency');
  protobufModules = parent;
}
// Verification imports the patched source through tsx; reuse the locked dependency.
const protobufLink = resolve(source, 'node_modules/@bufbuild/protobuf');
const protobufTarget = resolve(protobufModules, '@bufbuild/protobuf');
mkdirSync(dirname(protobufLink), { recursive: true });
if (!existsSync(protobufLink)) symlinkSync(protobufTarget, protobufLink, 'junction');
if (realpathSync(protobufLink) !== realpathSync(protobufTarget))
  throw new Error('Unexpected parser dependency link');
const sourceConfig = resolve(source, 'tsconfig.mizar.json');
writeFileSync(
  sourceConfig,
  JSON.stringify({
    extends: './tsconfig.json',
    include: ['src/**/*'],
    compilerOptions: {
      types: ['node'],
      typeRoots: [resolve(repo, 'node_modules/@types')],
      noEmit: true,
    },
  }),
);
const compilerPackage = createRequire(resolve(repo, 'package.json')).resolve(
  'typescript/package.json',
);
const compilerBins = JSON.parse(readFileSync(compilerPackage, 'utf8')).bin;
const compilerEntry = compilerBins.tsc ?? compilerBins.tsc6;
if (typeof compilerEntry !== 'string')
  throw new Error('Locked TypeScript compiler entry is missing');
const compiler = resolve(dirname(compilerPackage), compilerEntry);
execFileSync(process.execPath, [compiler, '-p', sourceConfig], { stdio: 'inherit' });
await esbuild.build({
  entryPoints: [resolve(here, 'parser_worker.mjs')],
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node24',
  outfile: resolve(outputArg),
  alias: {
    cs2parser: resolve(source, 'src/index.ts'),
  },
  nodePaths: [protobufModules],
});

