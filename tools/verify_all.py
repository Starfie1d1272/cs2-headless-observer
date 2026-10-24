"""Offline validation of a built worker and its patched source. No Steam or network."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def native_environment():
    env = {key.upper():value for key,value in os.environ.items()} if os.name == 'nt' else dict(os.environ)
    if os.name == 'nt' and not shutil.which('cl'):
        vswhere = Path(env.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        if vswhere.is_file():
            location = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
                'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
            script = Path(location) / 'VC/Auxiliary/Build/vcvars64.bat'
            if location and script.is_file():
                output = subprocess.check_output(f'cmd.exe /d /s /c ""{script}" >nul && set"', text=True)
                for line in output.splitlines():
                    key, sep, value = line.partition('=')
                    if sep and key: env[key.upper()] = value
    return env

def evidence_hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('research/data', 'research/evidence', 'docs/protocol')
            for p in (ROOT / folder).rglob('*') if p.is_file()}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parser-source', type=Path, required=True)
    ap.add_argument('--worker', type=Path, required=True)
    ap.add_argument('--node', type=Path, default=Path(shutil.which('node') or 'node'), help='Exact Node executable used by all parser checks and child processes')
    ap.add_argument('--output', type=Path, default=ROOT / 'work/verification' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    args = ap.parse_args()
    source, worker, out = args.parser_source.resolve(strict=True), args.worker.resolve(strict=True), args.output.resolve()
    for folder in ('research','docs','archive','tests','client','native','patches','tools'):
        protected = ROOT / folder
        if out == protected or protected in out.parents:
            ap.error('Output must be outside source and evidence directories')
    out.mkdir(parents=True, exist_ok=False)
    env = native_environment()
    node = args.node.resolve(strict=True)
    env['PATH'] = str(node.parent) + os.pathsep + env.get('PATH', '')
    node_version = subprocess.check_output([str(node), '--version'], text=True).strip()
    env['GOTV_ORDERED_WORKER'] = str(worker)
    results = []
    before = evidence_hashes()
    def run(name, command):
        start = time.monotonic()
        result = subprocess.run([str(v) for v in command], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / (name + '.log')).write_bytes(result.stdout)
        print(f'{name}: {"pass" if result.returncode == 0 else "FAIL"}', flush=True)
        results.append({'check': name, 'exitCode': result.returncode, 'seconds': round(time.monotonic()-start,3)})
        if result.returncode:
            sys.stdout.buffer.write(result.stdout[-12000:]); sys.stdout.flush()
            raise RuntimeError(name)
    failure = None
    try:
        if os.name == 'nt':
            compiler = shutil.which('cl', path=env.get('PATH'))
            if not compiler: raise RuntimeError('MSVC x64 toolchain is required')
            fixture = out / 'abi_fixture.dll'
            run('native-abi-build', [compiler, '/nologo', '/std:c++20', '/EHsc', '/W4', '/LD',
                ROOT/'tests/native/abi_fixture.cpp', '/Fo'+str(out/'abi_fixture.obj'), '/link', '/OUT:'+str(fixture), '/IMPLIB:'+str(out/'abi_fixture.lib')])
            env['GOTV_ABI_FIXTURE'] = str(fixture)
            executable = out / 'session_test.exe'
            run('native-session-build', [compiler, '/nologo', '/std:c++20', '/EHsc', '/W4', '/I'+str(ROOT/'native'),
                ROOT/'tests/native/session_test.cpp', '/Fo'+str(out/'session_test.obj'), '/Fe'+str(executable)])
        else:
            compiler = shutil.which('g++')
            if not compiler: raise RuntimeError('g++ is required')
            executable = out / 'session_test'
            run('native-session-build', [compiler, '-std=c++20', '-Wall', '-Wextra', '-I', ROOT/'native', ROOT/'tests/native/session_test.cpp', '-o', executable])
        run('native-session', [executable])
        run('parser-components', [node, ROOT/'tools/verification/verify_cohesive_parser.mjs', source, out/'components'])
        run('python', [sys.executable, ROOT/'tools/run_python_tests.py'])
        # Windows runners may provide pnpm.exe instead of a .cmd shim.
        pnpm = shutil.which('pnpm')
        if not pnpm: raise RuntimeError('pnpm is required')
        run('events', [pnpm, 'test:events'])
        run('typecheck', [pnpm, 'typecheck'])
        for name in ('verify_online_entities.mjs','verify_coordinate_profile.mjs','verify_angle_codecs.mjs','verify_integral_coordinates.mjs'):
            run(name[:-4], [node, '--import', 'tsx', ROOT/'tools/verification'/name, source])
        run('knowledge', [sys.executable, ROOT/'research/knowledge/validate.py', ROOT])
        run('repository-layout', [sys.executable, ROOT/'tools/check_layout.py'])
        run('managed-contract', [node, ROOT/'tools/verify_contract.mjs'])
        run('consumer-example', [sys.executable, ROOT/'examples/managed_consumer.py', '--help'])
        run('synthetic-replay', [sys.executable, ROOT/'tools/replay_example.py', '--worker', worker, '--node', node, '--output', out/'replay'])
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        failure = str(error)
    finally:
        unchanged = before == evidence_hashes()
        report = {'scope':'OFFLINE_NO_STEAM_NO_NETWORK', 'nodeVersion':node_version, 'nodeSha256':hashlib.sha256(node.read_bytes()).hexdigest(), 'workerSha256':hashlib.sha256(worker.read_bytes()).hexdigest(),
                  'checks':results, 'evidenceUnchanged':unchanged, 'failure':failure, 'passed':failure is None and unchanged}
        (out/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(report), flush=True)
    return 0 if report['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
