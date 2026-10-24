"""Verify a Windows package's hashes and synthetic offline replay with its bundled runtimes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client'))
from node_runtime import inspect_node
import tempfile

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package',type=Path)
    ap.add_argument('--node',type=Path,help='Node executable; external-node may also use PATH')
    ap.add_argument('--report',type=Path,help='Write validation report outside the artifact')
    args=ap.parse_args()
    root=args.package.resolve(strict=True)
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['nativeAbi']==3 and manifest['parserIpc']==3
    expected=manifest['filesSha256']
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    assert actual==set(expected)|{'manifest.json'},'Package inventory mismatch'
    for name,digest in expected.items():
        path=(root/name).resolve();assert root in path.parents,name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
    assert not any(Path(name).name.lower()=='steam_api64.dll' for name in actual),'Steam API must come from local CS2'
    # The distributed grant and SDK terms must match the corresponding source snapshot.
    for name, source in [('LICENSE-STEAMWORKS-EXCEPTION.txt', 'LICENSE-STEAMWORKS-EXCEPTION.txt'),
                         ('Steamworks-SDK.txt', 'licenses/Steamworks-SDK.txt')]:
        assert (root/'licenses'/name).read_bytes() == (root/'source/project'/source).read_bytes(), name
    python=root/'runtime/python/python.exe'
    component=manifest.get('distribution')=='external-node'
    node=args.node.resolve(strict=True) if args.node else (Path(__import__('shutil').which('node') or 'node') if component else root/'runtime/node.exe')
    info=inspect_node(node)
    assert info['platform']=='win32' and info['arch']=='x64','Windows x64 Node required for this package'
    if component:
        assert not (root/'runtime/node.exe').exists(),'Component must not carry another Node'
    with tempfile.TemporaryDirectory(prefix='cs2-observer-package-check-') as temp:
        output=Path(temp)/'synthetic'
        checks=[('driver-help',[python,root/'client/driver.py','--help']),('node-version',[node,'--version']),
                ('synthetic-replay',[python,root/'tools/replay_example.py','--node',node,'--output',output])]
        for name,command in checks:
            subprocess.run(list(map(str,command)),cwd=root,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            print(name+': pass')
        managed=Path(temp)/'managed'
        connection={'endpoint':'127.0.0.1:27020','password':'synthetic-configuration'}
        with subprocess.Popen(list(map(str,[python,root/'client/driver.py','--managed','--native',Path(temp)/'absent.dll',
            '--node',node,'--parser-worker',root/'client/parser_worker.mjs','--host-version','14192','--output',managed])),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as child:
            child.stdin.write(json.dumps(connection)+'\n');child.stdin.flush()
            assert child.wait(timeout=15)==1,'Expected absent-library startup rejection'
            stdout,stderr=child.stdout.read(),child.stderr.read()
        terminal=json.loads((managed/'report.json').read_text())
        assert stdout=='' and terminal['finalization_failures']==[] and terminal['outcome']=='failed'
        assert sorted(p.name for p in managed.iterdir())==['report.json']
        assert connection['password'] not in stderr and connection['endpoint'] not in stderr
        print('managed-startup-rejection-and-cleanup: pass')
    after={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    assert after==actual,'Package changed while running; generated cache or capture files are forbidden'
    for name,digest in expected.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
    report={'passed':True,'files':len(expected),'distribution':manifest.get('distribution','standalone-research'),
            'nodeVersion':subprocess.check_output([str(node),'--version'],text=True).strip(),
            'artifactRuntime':'windows-offline-smoke-pass','managedStartupBoundary':'pass',
            'artifactUnchanged':True,'artifactOnline':'not-tested','workingTreeDirty':manifest['workingTreeDirty']}
    if args.report:
        destination=args.report.resolve()
        assert root not in destination.parents,'Report must be outside the immutable artifact'
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__': main()
