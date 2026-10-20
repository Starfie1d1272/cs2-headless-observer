"""Assemble a portable research artifact from pinned official runtimes and a CI-built bridge."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

RUNTIMES = {
    'python': ('python-3.14.8-embed-amd64.zip', 'a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310'),
    'node': ('node-v24.22.0-win-x64.zip', 'f9683a19877e12a9b167305c8db71040d812876359de21f0d2e97c3f321f80c3'),
}
MODULES = ['driver', 'launcher', 'ordered_parser_bridge', 'observer_settings', 'wire', 'live', 'channel',
           'handshake', 'password', 'resource_manifest', 'replay', 'sdk']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtimes', type=Path, required=True)
    ap.add_argument('--native', type=Path, required=True)
    ap.add_argument('--parser-bundle', type=Path, required=True)
    ap.add_argument('--parser-source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--source-sha', required=True)
    args = ap.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.source_sha):
        raise SystemExit('Exact source commit required.')
    for name, sha in RUNTIMES.values():
        if digest(args.runtimes / name) != sha:
            raise SystemExit(f'Runtime digest mismatch: {name}')
    if args.native.read_bytes()[:2] != b'MZ':
        raise SystemExit('A Windows PE bridge is required.')
    root = Path(__file__).resolve().parent
    repo = root.parent
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    client, runtime, licenses = out / 'client', out / 'runtime', out / 'licenses'
    client.mkdir(); runtime.mkdir(); licenses.mkdir()
    python = runtime / 'python'; python.mkdir()
    with zipfile.ZipFile(args.runtimes / RUNTIMES['python'][0]) as archive:
        for member in archive.infolist():
            # The pinned embedded distribution is flat; never accept traversal.
            if Path(member.filename).name != member.filename or member.is_dir():
                raise SystemExit('Unexpected embedded Python archive layout.')
            (python / member.filename).write_bytes(archive.read(member))
    (python / 'python314._pth').write_text('python314.zip\n.\n../../client\n', encoding='utf8')
    shutil.copyfile(python / 'LICENSE.txt', licenses / 'Python.txt')
    with zipfile.ZipFile(args.runtimes / RUNTIMES['node'][0]) as archive:
        prefix = 'node-v24.22.0-win-x64/'
        (runtime / 'node.exe').write_bytes(archive.read(prefix + 'node.exe'))
        (licenses / 'Node.txt').write_bytes(archive.read(prefix + 'LICENSE'))
    for name in MODULES:
        shutil.copyfile(root / f'{name}.py', client / f'{name}.py')
    shutil.copyfile(args.native, client / 'mizar_observer.dll')
    shutil.copyfile(args.parser_bundle, client / 'parser_worker.mjs')
    shutil.copyfile(repo / 'LICENSE', licenses / 'Mizar.txt')
    parser = repo / 'node_modules/cs2parser'
    shutil.copyfile(parser / 'LICENSE', licenses / 'cs2parser.txt')
    shutil.copyfile(parser / 'ACKNOWLEDGEMENTS', licenses / 'cs2parser-acknowledgements.txt')
    shutil.copyfile(root / 'licenses/protobuf-es-Apache-2.0.txt', licenses / 'protobuf-es-Apache-2.0.txt')
    protobuf = parser.resolve().parent / '@bufbuild/protobuf'
    shutil.copyfile(protobuf / 'dist/esm/wire/varint.js', licenses / 'protobuf-varint-BSD-notice.js')
    source = out / 'source'; source.mkdir()
    shutil.copytree(protobuf / 'dist', source / 'protobuf-dist')
    shutil.copytree(root / 'native', source / 'native')
    shutil.copytree(parser / 'dist', source / 'cs2parser-dist')
    shutil.copyfile(parser / 'package.json', source / 'cs2parser-package.json')
    shutil.copytree(args.parser_source / 'src', source / 'cs2parser-source/src')
    shutil.copyfile(args.parser_source / 'LICENSE', source / 'cs2parser-source/LICENSE')
    shutil.copyfile(args.parser_source / 'package.json', source / 'cs2parser-source/package.json')
    shutil.copyfile(root / 'cs2parser-online.patch', source / 'cs2parser-online.patch')
    (out / 'Start.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\n"runtime\\python\\python.exe" "client\\launcher.py"\r\npause\r\n')
    (out / 'README.txt').write_text('''Mizar 普通 GOTV 观众测试客户端

解压到可写目录，保持 Steam 已登录自己的账号，双击 Start.cmd。
填写 CS2 安装目录，核对当前游戏协议版本，再输入获授权测试赛的普通观战地址和密码。
默认运行五分钟，结果位于 runs 子目录。密码和票据只在进程中使用。
无需安装 Python、Node 或额外游戏组件；使用本机 CS2 已有 steam_api64.dll。

当前构建用于验证普通观众接入、初始化和持续事件输出。云端已验证编译、录像解析及合成网络状态；Windows 实际运行与完美在线互操作待验证。
在线实例基线、PVS 更新和缺帧全量恢复已加入研究实现，并通过离线数据与合成传输验证。完美在线互操作仍待集中验证。
报告中的 FULL 是协议状态；成功验收还需连续收数、实际事件与游戏对照。
只分享 report.json 即可；channel.frames 和 events.jsonl 默认保留本机。

源代码：https://github.com/Starfie1d1272/cs2-headless-observer/tree/''' + args.source_sha + '''/client
cs2parser 2.7.2（MPL-2.0）：https://github.com/osztenkurden/cs2parser/tree/deced963b86d3ec26b28a225824130fdf9fe3167
Node.js 24.22.0：https://nodejs.org/dist/v24.22.0/
Python 3.14.8：https://www.python.org/ftp/python/3.14.8/
SDK 头文件来源：ValveSoftware/Proton，bc896217ffcd67f892f952b010f898fe7bd0f0a1，steamworks_sdk_165。
第三方许可证、解析器修改源码及补丁保存在 licenses 和 source 目录。
''', encoding='utf8')
    files = {p.relative_to(out).as_posix(): digest(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'manifest.json').write_text(json.dumps({'schema': 'mizar-observer-research/1',
        'sourceSha': args.source_sha, 'onlineVerified': False, 'windowsRuntimeVerified': False,
        'runtimes': RUNTIMES, 'filesSha256': files}, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    target = shutil.make_archive(str(out), 'zip', out)
    print(json.dumps({'archive': target, 'bytes': Path(target).stat().st_size, 'sha256': digest(Path(target)),
        'sourceSha': args.source_sha, 'onlineVerified': False}))


if __name__ == '__main__':
    main()
