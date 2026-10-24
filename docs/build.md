# 从源码构建

准备 Git、Node.js 24、Python 3.11+、pnpm 12.9.1。Windows 原生桥使用 Visual Studio x64 C++ 工具链。包管理器版本由 `package.json` 的 `packageManager` 固定。

## 解析器

从仓库根目录运行，`work/parser` 使用新的干净目录：

```powershell
pnpm install --frozen-lockfile
New-Item -ItemType Directory -Force work | Out-Null
git clone https://github.com/osztenkurden/cs2parser.git work/parser
git -C work/parser checkout --detach deced963b86d3ec26b28a225824130fdf9fe3167
node tools/build_parser.mjs work/parser work/build/parser_worker.mjs
python tools/verify_all.py --parser-source work/parser --worker work/build/parser_worker.mjs
```

构建工具核对上游提交和工作树，应用 `patches/` 的接缝修改，将 `parser/src/` 复制为解析模块，再执行类型检查和单文件构建。每次重建准备新的干净上游目录。

普通构建使用固定上游的 WASM。对应 C 源码位于上游 `wasm/`，生成脚本位于 `scripts/`；重新生成时按脚本准备 Bun 和 Clang 20.1.8。

## 原生桥

SDK 输入为 ValveSoftware/Proton 提交 `bc896217ffcd67f892f952b010f898fe7bd0f0a1` 中的 `lsteamclient/steamworks_sdk_165`。SDK 根目录下放置 `steam/` 头文件目录，归档与摘要由 `.github/workflows/observer-research.yml` 固定。

```powershell
python tools/build_native.py --sdk <sdk-root> --output work/native
```

## Windows 包

准备 `tools/package_windows.py` 固定的运行时归档：Python embeddable 3.14.8、Node 24.22.0。源码工作树保持干净并已提交，`--source-sha` 使用当前完整提交：

```powershell
python tools/package_windows.py --runtimes <verified-runtime-zips> --native work/native/cs2_observer.dll --parser-bundle work/build/parser_worker.mjs --parser-source work/parser --output dist/observer --source-sha <40-character-source-commit>
python tools/verify_package.py dist/observer
```

`--kind external-node` 生成复用宿主 Node 的组件包，组装时准备 Python 归档即可；验证时用 `--node` 选择运行时。详细布局见[组件分发](component-distribution.md)。

包内 `source/project/` 保存本项目的固定提交，`source/cs2parser-source/` 保存完成修改的解析器及 WASM 对应源码。重新从上游构建使用干净 checkout 路线；阅读包内修改结果时直接使用对应快照。

原生桥编译引用外部 SDK 头文件，运行时使用本机 CS2 提供的 Steam API DLL。发行材料按[第三方来源](../THIRD_PARTY_NOTICES.md)保留许可、来源与重建资料。
