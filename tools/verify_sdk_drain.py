"""Explicit Windows SDK loopback diagnostic; never connects to a GOTV source."""
import argparse,json,os,shutil,subprocess
from pathlib import Path
from verify_all import native_environment
root=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sdk',type=Path,required=True);ap.add_argument('--steam-api',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if os.name!='nt':ap.error('Windows SDK diagnostic')
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);env=native_environment()
    api=a.steam_api.resolve(strict=True);sdk=a.sdk.resolve(strict=True)
    env['PATH']=str(api.parent)+os.pathsep+env.get('PATH','');env['SteamAppId']='730'
    def build(tool,args):
        p=subprocess.run([shutil.which(tool,path=env['PATH']),*map(str,args)],cwd=out,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (out/(tool+'.log')).write_bytes(p.stdout);p.check_returncode()
    build('lib',['/nologo','/machine:x64','/def:'+str(root/'native/steam_api64.def'),'/out:'+str(out/'steam_api64.lib')])
    build('cl',['/nologo','/std:c++20','/EHsc','/O2','/MT','/I'+str(sdk),'/I'+str(sdk/'steam'),root/'tests/native/sdk_drain.cpp','/Fo'+str(out/'sdk_drain.obj'),'/Fe'+str(out/'sdk_drain.exe'),'/link',out/'steam_api64.lib'])
    p=subprocess.run([str(out/'sdk_drain.exe')],cwd=out,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
    # Native SDK diagnostics are deliberately not forwarded or persisted.
    report=json.loads(p.stdout.decode('utf-8'));report['exitCode']=p.returncode
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));return p.returncode
if __name__=='__main__':raise SystemExit(main())
