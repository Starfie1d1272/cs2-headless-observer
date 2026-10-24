# 从源码构建

需要 Git、Node 24、Python 3.11+ 和 package.json 指定的 pnpm 12.9.1。Windows 原生构建需要 Visual Studio 的 x64 C++ 工具链。
pnpm shim 应按 packageManager 选择锁定版本；安装输出应显示使用 12.9.1。

## 解析器

从仓库根目录运行，work/parser 必须是新的干净目录；构建会修改这个一次性上游 checkout：

```powershell
pnpm install --frozen-lockfile
New-Item -ItemType Directory -Force work | Out-Null
git clone https://github.com/osztenkurden/cs2parser.git work/parser
git -C work/parser checkout --detach deced963b86d3ec26b28a225824130fdf9fe3167
node tools/build_parser.mjs work/parser work/build/parser_worker.mjs
python tools/verify_all.py --parser-source work/parser --worker work/build/parser_worker.mjs
```

锁定源码、补丁和工具链共同决定 worker。不要把本机诊断候选目录当成生产补丁来源；重复构建使用新的干净 checkout。

## 原生桥与便携包

SDK 头文件输入固定为 ValveSoftware/Proton 提交 bc896217ffcd67f892f952b010f898fe7bd0f0a1 的 lsteamclient/steamworks_sdk_165。文件与摘要固定在手动打包工作流中。
SDK 根目录需要包含 steam/ 子目录及其头文件。下载依赖不会连接比赛。

```powershell
python tools/build_native.py --sdk <sdk-root> --output work/native
python tools/package_windows.py --runtimes <verified-runtime-zips> --native work/native/cs2_observer.dll --parser-bundle work/build/parser_worker.mjs --parser-source work/parser --output dist/observer --source-sha <40-character-source-commit>
python tools/verify_package.py dist/observer
```

运行时 ZIP 名称和 SHA-256 在 tools/package_windows.py 中固定；Node 为 24.22.0，Python 为 3.14.8。打包前须核对许可与拟分发资产。包不携带 Steam/CS2 DLL。
包内 source/ 保存本项目运行源码、构建材料、补丁及修改后的解析器源快照。该解析器源快照已经打补丁；从固定上游干净 checkout 构建时才再次应用补丁。

打包要求干净、已提交的源码；manifest记录固定提交，源码目录保留完整项目快照、修改解析器及依赖材料。制品启动验证和历史在线验收分别记录。候选构建不自动表示公开许可审查已通过。

调用方自带Node时选择 `--kind external-node`；组装时不需要指定Node。独立研究包保持默认。最低运行要求与升级边界见[组件分发](component-distribution.md)。
