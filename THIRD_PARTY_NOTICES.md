# 第三方来源与分发材料

项目自有代码采用根目录的 AGPL-3.0，并附 [Steamworks SDK 链接例外](LICENSE-STEAMWORKS-EXCEPTION.txt)。4.0.0 起以纯 Rust 单二进制（`cs2-headless-observer.exe`）与 C++ 原生桥（`cs2_observer.dll`）分发，不再包含 Node.js、Python、`cs2parser` 或 WASM 依赖；第三方组件适用各自许可证。

## 原生桥与运行时外部输入

| 组件 | 固定来源 | 随包材料与使用方式 |
| --- | --- | --- |
| Steamworks SDK 头文件 | ValveSoftware/Proton `bc896217ffcd67f892f952b010f898fe7bd0f0a1` 的 `steamworks_sdk_165` | 外部编译输入；归档协议见 [Steamworks-SDK.txt](licenses/Steamworks-SDK.txt) |
| Steam API | 使用者本机 CS2 安装 | 运行时从本机加载 `steam_api64.dll` |

Steamworks SDK 链接例外适用于项目权利人有权授权的代码；Valve 材料的使用和分发遵循 SDK 协议。SDK 头文件仅作为构建前提准备，账号、票据和游戏模块保存在使用者本机。

## Rust 静态链接依赖（`rust/Cargo.lock`）

直接依赖及传递依赖的版本锁定于 [`rust/Cargo.lock`](rust/Cargo.lock)：

| Crate | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| `clap`（含 `clap_builder`、`clap_derive`、`clap_lex` 等） | `4.6.10` | MIT OR Apache-2.0 | 命令行参数解析 |
| `libloading` | `0.8.9` | ISC | 动态加载 `cs2_observer.dll`（ABI 4） |
| `lz4_flex` | `0.11.7` | MIT | GOTV 帧 LZ4 块解压 |
| `prost`（含 `prost-derive`、`bytes`） | `0.13.5` | Apache-2.0 | Source 2 Protobuf 线格式编解码 |
| `serde`（含 `serde_core`、`serde_derive`） | `1.0.229` | MIT OR Apache-2.0 | 结构体序列化与反序列化 |
| `serde_json` | `1.0.154` | MIT OR Apache-2.0 | Managed JSON v2 输出与报告序列化 |
| `snap` | `1.1.2` | BSD-3-Clause | StringTable Snappy 解压 |
| `thiserror`（含 `thiserror-impl`） | `2.0.21` | MIT OR Apache-2.0 | 结构化错误类型定义 |
| `uuid`（含 `getrandom`） | `1.29.3` | Apache-2.0 OR MIT | 默认 `source-id` UUIDv4 生成 |

其余传递支撑 crate（如 `windows-sys`、`windows-link`、`libc`、`memchr`、`twox-hash`、`itoa`、`zmij`、`syn`、`quote`、`proc-macro2` 等）均采用 `MIT OR Apache-2.0`、`MIT`、`Apache-2.0` 或 `Unicode-3.0`（`unicode-ident`）等兼容许可，完整锁定清单见 [`rust/Cargo.lock`](rust/Cargo.lock)。

对应完整源码通过 GitHub Release tag 与官方源码归档提供。
