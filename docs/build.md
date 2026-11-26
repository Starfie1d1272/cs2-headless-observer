# 从源码构建

准备 Git、Rust 工具链（`stable`，含 `rustfmt` 与 `clippy`）以及 Python 3.11+（用于调用原生桥编译脚本）。Windows 原生桥使用 Visual Studio x64 C++ 工具链。

## Rust 主程序

在仓库根目录执行：

```powershell
cd rust
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release
```

编译产物位于 `rust/target/release/cs2-headless-observer.exe`（Windows）或 `rust/target/release/cs2-headless-observer`（POSIX）。无需外部 `protoc` 或 Node.js / pnpm 工具链。

## 原生桥（`cs2_observer.dll`）

SDK 输入为 `ValveSoftware/Proton` 提交 `bc896217ffcd67f892f952b010f898fe7bd0f0a1` 中的 `lsteamclient/steamworks_sdk_165`。将 `steam/` 头文件目录置于 `<sdk-root>` 后运行：

```powershell
python tools/build_native.py --sdk <sdk-root> --output work/native
```

编译输出为 `work/native/cs2_observer.dll`，并自动校验 ABI 4 全部导出符号。

## Windows 发行包组装

Windows 发行包由 `cs2-headless-observer.exe`、`cs2_observer.dll`、`manifest.json`（`cs2-headless-observer-package/6`）、`examples/`、`schemas/` 与 `licenses/` 组成，无内置 Python/Node 运行时或 `source/project/` 冗余副本；对应源码通过 GitHub Release tag 与官方源码归档提供。

自动化组装与自检定义在 [`.github/workflows/observer-research.yml`](../.github/workflows/observer-research.yml) 中，包含 Rust Release 构建、原生桥编译、`replay` 合成通道自检与产物哈希清单生成。

原生桥编译引用外部 SDK 头文件，运行时使用本机 CS2 提供的 `steam_api64.dll`。发行材料按[第三方来源](../THIRD_PARTY_NOTICES.md)保留许可与声明。
