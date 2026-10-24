"""Compile the Windows x64 SDK bridge; never loads Steam or connects a source."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from verify_all import native_environment

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sdk',type=Path,required=True,help='Pinned SDK root containing steam/steam_api.h')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    sdk=args.sdk.resolve(strict=True);out=args.output.resolve()
    if not (sdk/'steam/steam_api.h').is_file(): ap.error('Expected pinned SDK root with steam/steam_api.h')
    if out==ROOT or ROOT/'native'==out or ROOT/'native' in out.parents: ap.error('Use a build output directory')
    out.mkdir(parents=True,exist_ok=False)
    env=native_environment()
    def run(tool,*arguments):
        executable=shutil.which(tool,path=env.get('PATH'))
        if not executable: raise RuntimeError('MSVC x64 toolchain is required')
        return subprocess.check_output([executable,*map(str,arguments)],cwd=out,env=env,stderr=subprocess.STDOUT)
    (out/'import-library.log').write_bytes(run('lib','/nologo','/machine:x64','/def:'+str(ROOT/'native/steam_api64.def'),'/out:'+str(out/'steam_api64.lib')))
    common=['/nologo','/std:c++20','/EHsc','/O2','/MT','/I'+str(sdk),'/I'+str(sdk/'steam')]
    (out/'sdk-compile.log').write_bytes(run('cl',*common,'/c',ROOT/'tests/native/compile_sdk.cpp','/I'+str(ROOT/'native'),'/Fo'+str(out/'compile_sdk.obj')))
    dll=out/'cs2_observer.dll'
    (out/'bridge-build.log').write_bytes(run('cl',*common,'/LD',ROOT/'native/sdk_host.cpp','/Fo'+str(out/'sdk_host.obj'),'/link',out/'steam_api64.lib','/OUT:'+str(dll)))
    exports=run('dumpbin','/exports',dll)
    (out/'exports.txt').write_bytes(exports)
    required=['observer_create','observer_send','observer_receive','observer_auth','observer_close','observer_abi_version','observer_local_id','observer_accept_server_auth2','observer_remote_end_reason']
    assert all(name.encode() in exports for name in required),'Missing ABI export'
    print(json.dumps({'compiled':True,'sdkLoaded':False,'sha256':hashlib.sha256(dll.read_bytes()).hexdigest()}))

if __name__=='__main__': main()
