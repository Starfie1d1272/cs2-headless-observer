"""Assemble a portable observer artifact from pinned official runtimes and a CI-built bridge."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

RUNTIMES = {
    'python': ('python-3.14.8-embed-amd64.zip', 'a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310'),
    'node': ('node-v24.22.0-win-x64.zip', 'f9683a19877e12a9b167305c8db71040d812876359de21f0d2e97c3f321f80c3'),
}
MODULES = ['driver', 'launcher', 'ordered_parser_bridge', 'observer_settings', 'wire', 'control', 'process_io', 'process_job', 'host_version', 'channel',
           'handshake', 'password', 'resource_manifest', 'replay_ordered', 'sdk', 'node_runtime']


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
    ap.add_argument('--kind', choices=('standalone', 'external-node'), default='standalone')
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    contract = json.loads((repo / 'packaging/component-contract.json').read_text(encoding='utf-8'))
    if contract['componentVersion'] != json.loads((repo / 'package.json').read_text())['version']:
        raise SystemExit('Package and component versions differ')
    component = args.kind == 'external-node'
    if not re.fullmatch('[0-9a-f]{40}', args.source_sha):
        raise SystemExit('Exact source commit required.')
    for key, (name, sha) in RUNTIMES.items():
        if component and key == 'node':
            continue
        if digest(args.runtimes / name) != sha:
            raise SystemExit(f'Runtime digest mismatch: {name}')
    if args.native.read_bytes()[:2] != b'MZ':
        raise SystemExit('A Windows PE bridge is required.')
    root = repo / 'client'
    dirty = bool(subprocess.check_output(['git','-C',str(repo),'status','--porcelain']).strip())
    head = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    if head != args.source_sha:
        raise SystemExit('Source commit must match this checkout HEAD')
    if dirty:
        raise SystemExit('Release packaging requires a clean committed checkout')
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
    if not component:
        with zipfile.ZipFile(args.runtimes / RUNTIMES['node'][0]) as archive:
            prefix = 'node-v24.22.0-win-x64/'
            (runtime / 'node.exe').write_bytes(archive.read(prefix + 'node.exe'))
            (licenses / 'Node.txt').write_bytes(archive.read(prefix + 'LICENSE'))
    for name in MODULES:
        if component and name == 'launcher':
            continue
        shutil.copyfile(root / f'{name}.py', client / f'{name}.py')
    shutil.copyfile(args.native, client / 'cs2_observer.dll')
    shutil.copyfile(args.parser_bundle, client / 'parser_worker.mjs')
    shutil.copyfile(repo / 'LICENSE', licenses / 'cs2-headless-observer-AGPL-3.0.txt')
    shutil.copyfile(repo / 'LICENSE-STEAMWORKS-EXCEPTION.txt', licenses / 'LICENSE-STEAMWORKS-EXCEPTION.txt')
    shutil.copyfile(repo / 'licenses/Steamworks-SDK.txt', licenses / 'Steamworks-SDK.txt')
    parser = repo / 'node_modules/cs2parser'
    shutil.copyfile(parser / 'LICENSE', licenses / 'cs2parser.txt')
    shutil.copyfile(parser / 'ACKNOWLEDGEMENTS', licenses / 'cs2parser-acknowledgements.txt')
    shutil.copyfile(repo / 'licenses/protobuf-es-Apache-2.0.txt', licenses / 'protobuf-es-Apache-2.0.txt')
    protobuf = parser.resolve().parent / '@bufbuild/protobuf'
    shutil.copyfile(protobuf / 'dist/esm/wire/varint.js', licenses / 'protobuf-varint-BSD-notice.js')
    source = out / 'source'; source.mkdir()
    shutil.copytree(protobuf / 'dist', source / 'protobuf-dist')
    project = source / 'project'; project.mkdir()
    # A clean release contains all maintained sources, tests, evidence and rebuild tools.
    snapshot = subprocess.check_output(['git', '-C', str(repo), 'archive', '--format=zip', 'HEAD'])
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            destination = (project / entry.filename).resolve()
            if project.resolve() not in destination.parents:
                raise SystemExit('Unsafe source archive path')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(entry))
    (source / 'SOURCE.txt').write_text('Project snapshot: project/\n'
        'Pinned modified parser: cs2parser-source/\n'
        'Read project/docs/build.md for a clean upstream checkout build.\n'
        'SDK headers and Steam/CS2 DLLs are external prerequisites and are not included.\n', encoding='utf-8')
    shutil.copytree(args.parser_source / 'src', source / 'cs2parser-source/src')
    shutil.copyfile(args.parser_source / 'LICENSE', source / 'cs2parser-source/LICENSE')
    shutil.copyfile(args.parser_source / 'package.json', source / 'cs2parser-source/package.json')
    shutil.copyfile(args.parser_source / 'tsconfig.json', source / 'cs2parser-source/tsconfig.json')
    shutil.copytree(args.parser_source / 'wasm', source / 'cs2parser-source/wasm')
    shutil.copytree(args.parser_source / 'scripts', source / 'cs2parser-source/scripts')
    for name in ('pnpm-lock.yaml', 'bun.lock', 'README.md'):
        if (args.parser_source / name).is_file():
            shutil.copyfile(args.parser_source / name, source / 'cs2parser-source' / name)
    shutil.copyfile(repo / 'THIRD_PARTY_NOTICES.md', licenses / 'THIRD_PARTY_NOTICES.md')
    shutil.copytree(repo / 'schemas', out / 'schemas')
    shutil.copytree(repo / 'examples', out / 'examples')
    tools = out / 'tools'; tools.mkdir()
    shutil.copyfile(repo / 'tools/replay_example.py', tools / 'replay_example.py')
    examples = out / 'examples'
    shutil.copyfile(repo / 'tests/fixtures/synthetic-channel.json', examples / 'synthetic-channel.json')
    docs = out / 'docs'; docs.mkdir()
    for name in ('usage.md', 'compatibility.md', 'managed-interface.md', 'component-distribution.md', 'build.md', 'verification.md'):
        shutil.copyfile(repo / 'docs' / name, docs / name)
    # Entry docs resolve within the artifact; complete source remains canonical and unmodified.
    from urllib.parse import unquote
    for document in docs.glob('*.md'):
        text = document.read_text(encoding='utf-8')
        def local_link(match):
            target = match.group(1)
            if '://' in target or target.startswith('#'):
                return match.group(0)
            path, separator, anchor = target.partition('#')
            if (document.parent / unquote(path)).exists():
                return match.group(0)
            original = (repo / 'docs' / path).resolve()
            if repo not in original.parents or not original.exists():
                raise SystemExit('Broken maintained document link: ' + target)
            replacement = '../source/project/' + original.relative_to(repo).as_posix()
            return '](' + replacement + ('#' + anchor if separator else '') + ')'
        document.write_text(re.sub(r'\]\(([^)\s]+)\)', local_link, text), encoding='utf-8')
    if not component:
        (out / 'Start.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\n"runtime\\python\\python.exe" -B "client\\launcher.py"\r\npause\r\n')
        (out / 'Replay.cmd').write_bytes(b'@echo off\r\ncd /d "%~dp0"\r\n"runtime\\python\\python.exe" -B "tools\\replay_example.py"\r\npause\r\n')
    (out / 'README.txt').write_text('CS2 Headless Observer ' + contract['componentVersion'] + '''

1. 解压到可写目录，运行 Replay.cmd 完成本地解析与输出自检。
2. 登录自己的 Steam 账号。需要同时使用游戏时，先启动 CS2。
3. 运行 Start.cmd，填写 CS2 安装目录、来源 host 和获授权的观战地址、密码。

会话持续至来源结束或主动停止。Ctrl+C 请求清理，等待进程退出后开始新会话。
报告保存在 runs 子目录，原始采集由独立驱动参数选择并受容量预算管理。
Python、Node 随包提供；Steam API 使用本机 CS2 的 steam_api64.dll。

运行与故障处理：docs/usage.md
应用集成：docs/managed-interface.md
平台与验证范围：docs/compatibility.md
构建与对应源码：docs/build.md、source/
许可与第三方材料：licenses/

源代码：https://github.com/Starfie1d1272/cs2-headless-observer/tree/''' + args.source_sha + '''
cs2parser 2.7.2：https://github.com/osztenkurden/cs2parser/tree/deced963b86d3ec26b28a225824130fdf9fe3167
Node.js 24.22.0：https://nodejs.org/dist/v24.22.0/
Python 3.14.8：https://www.python.org/ftp/python/3.14.8/
SDK 构建输入：ValveSoftware/Proton bc896217ffcd67f892f952b010f898fe7bd0f0a1 / steamworks_sdk_165。
''', encoding='utf8')
    if component:
        (out / 'README.txt').write_text('CS2 Headless Observer ' + contract['componentVersion'] + ' — external-node\n'
            '使用调用方或 PATH 中的 Node.js 24.0.0 及以上版本，通过 --node 选择运行时。\n'
            '按 manifest.json 的 entrypoints 定位包内 Python、driver、原生桥与 worker。\n'
            '应用以 --managed 启动，写入一行私有配置后保持 stdin 开放并持续消费 stdout。\n'
            '关闭 stdin 请求停止，等待进程退出后以新来源身份重试。\n'
            '运行报告位于调用方选择的输出目录。\n'
            '接口与示例：docs/managed-interface.md、examples/、schemas/。\n'
            '平台与验证范围：docs/compatibility.md。\n'
            '对应源码与许可：source/、licenses/。\n'
            '源代码：https://github.com/Starfie1d1272/cs2-headless-observer/tree/' + args.source_sha + '\n', encoding='utf-8')
    with (out / 'README.txt').open('a', encoding='utf-8') as readme:
        readme.write('\n连接共存：同一账号的并行客户端使用不同 GOTV 端点。相同端点的新连接可能替换已有连接，游戏客户端也占用端点。\n'
            'Steam 通过 App730 管理观众会话，重启游戏前先停止观察器并等待退出。\n'
            '1000 的原因结合端点、操作时间和完整回执判断，完整条件见 docs/compatibility.md。\n')
    files = {p.relative_to(out).as_posix(): digest(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'manifest.json').write_text(json.dumps({'schema': 'cs2-headless-observer-package/4',
        'distribution': args.kind, 'componentId': contract['componentId'], 'componentVersion': contract['componentVersion'],
        'sourceSha': args.source_sha, 'workingTreeDirty': dirty,
        'platform': contract['platform'], 'nativeAbi': contract['nativeAbi'], 'parserIpc': contract['parserIpc'],
        'managedProtocol': contract['managedProtocol'], 'validatedHostVersions': contract['validatedHostVersions'],
        'nodeRequirement': contract['nodeRequirement'],
        'entrypoints': {'python': 'runtime/python/python.exe', 'driver': 'client/driver.py',
                        'native': 'client/cs2_observer.dll', 'worker': 'client/parser_worker.mjs'},
        'verification': {'artifactRuntime': 'not-run-by-assembler', 'artifactOnline': 'not-run-by-assembler'},
        'runtimes': {key:value for key,value in RUNTIMES.items() if not (component and key == 'node')}, 'filesSha256': files}, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    target = shutil.make_archive(str(out), 'zip', out)
    print(json.dumps({'archive': target, 'bytes': Path(target).stat().st_size, 'sha256': digest(Path(target)),
        'sourceSha': args.source_sha, 'workingTreeDirty': dirty, 'distribution': args.kind}))


if __name__ == '__main__':
    main()
