# CS2 Headless Observer

> 🎮 轻量级 CS2 GOTV 无图形后台观战与结构化事件接收组件（Rust 单二进制版）

[![Platform](https://img.shields.io/badge/platform-Windows%20x64-0078D6)](#快速开始)
[![Protocol](https://img.shields.io/badge/managed%20protocol-v3-2EA44F)](docs/managed-interface.md)
[![Rust](https://img.shields.io/badge/Rust-4.1.0-orange)](rust/Cargo.toml)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE-STEAMWORKS-EXCEPTION.txt)

**CS2 Headless Observer** 使用合法的普通 Steam 观众身份连接获授权的 CS2 GOTV 服务器，在不启动完整游戏客户端的情况下实时接收并解码 Source 2 网络帧，向消费应用持续交付有序、可信的 JSONL 比赛事件与时间游标。

它是 [Mizar](https://github.com/Starfie1d1272/Mizar) 的底层 Lookahead 数据接收组件，也可以作为独立工具或子进程组件接入任何赛事制播、数据采集或直播自动化系统。

---

## ✨ 核心能力

- 🔇 **无图形后台观战**：通过原生 Steamworks 桥接（`cs2_observer.dll`，ABI 4）建立授权 GOTV 连接，无需渲染画面或启动 CS2 窗口。
- ⚡ **单二进制高性能解码**：4.0.0 起以纯 Rust 单二进制（`cs2-headless-observer.exe`）统一承担传输、协议解码、实体快照与托管监督，无 Python/Node.js 运行时依赖与跨进程 IPC 开销。
- 📡 **结构化实时事件流**：输出回合时钟（`cursor`）、击杀、伤害、投掷物、炸弹事件与实体身份证明（Steam64 / Controller / Pawn）。
- 🔄 **连接恢复与连续序号**：内置 `Supervisor` 管理断线指数退避重连、首次连接快速失败与跨连接严格连续序号。
- 🛡️ **可控资源边界与离线自检**：支持有界异步 stdout/stderr 排空、窗口解析耗时观测（`decodeUs` / `decodeMaxUs`）与 `replay` 本地合成回放自检。

---

## 🚀 快速开始

从 [GitHub Releases](https://github.com/Starfie1d1272/cs2-headless-observer/releases) 下载对应版本的 Windows x64 发行包（仅包含 `cs2-headless-observer.exe`、`cs2_observer.dll`、`manifest.json`、示例、Schema 与许可文件，无需安装 Python 或 Node.js）：

### 离线回放自检

解压发行包到可写目录后，运行内置合成通道回放验证解码与输出格式：

```powershell
.\cs2-headless-observer.exe replay --input examples\synthetic-channel.json --host-version 14191 --output work\replay-check
```

### 托管运行（`--managed`）

1. 登录本机 Steam 客户端，准备好 CS2 安装目录中的 `steam_api64.dll` 以及获授权的 GOTV `IP:port` 与观战密码（如需同时运行游戏客户端，请先启动 CS2）。
2. 宿主应用按 `manifest.json` 的 `entrypoints.executable` 与 `entrypoints.native` 启动 `cs2-headless-observer.exe --managed ...`，向 `stdin` 写入一行配置 JSON 并保持 `stdin` 开放；关闭 `stdin`（EOF）可触发安全排空并退出。

> 💡 **提示**：Steam 会将观众的 App 730 上下文显示为 CS2 运行状态。重启游戏客户端前，请先停止观察器并等待其进程完全退出。

---

## 🧾 输出示例与集成方式

组件通过 `stdout` 逐行输出 JSONL 记录（`cs2-observer-managed-json/3`），`stderr` 输出周期性健康快照，并在输出目录写入终态报告 `report.json`。以下是[合成自检输出](examples/managed-events.json)的典型片段（完整字段定义见 [JSON Schema](schemas/managed-event.schema.json)）：

```jsonl
{"kind":"session-start","protocol":3,"channel":1,"world":1,"sequence":1}
{"kind":"cursor","channel":1,"world":1,"sequence":2,"committedTick":100,"tickInterval":0.015625,"map":"de_test"}
{"kind":"event","name":"round_freeze_end","channel":1,"world":1,"sequence":3,"eventTick":100,"committedTick":100,"fields":{},"players":{}}
```

宿主应用按[托管接口契约](docs/managed-interface.md)接入，可参考完整调用示例：[Python 消费者](examples/managed_consumer.py) · [Node.js 消费者](examples/managed_consumer.mjs)。

---

## 🧱 架构概览

```text
GOTV 服务器 ──▶ C++ Steam Bridge (cs2_observer.dll, ABI 4) ──▶ cs2-headless-observer.exe (Rust, Managed v3) ──▶ JSONL 输出 ──▶ Mizar / 消费应用
                                                                     ├─ wire: 位流 / LZ4 / Snappy / LZSS / Channel / Handshake
                                                                     ├─ parser: Schema / FieldPath / StringTable / Entities / Projection
                                                                     ├─ native: ABI 4 FFI / ICE 密码加密
                                                                     └─ session: Supervisor / Driver / Reporting / Replay
```

---

## ⚠️ 兼容性与已知限制

- **运行平台**：Windows x64（依赖本机已登录的 Steam 与 CS2 安装目录中的 `steam_api64.dll`）。
- **已验证基线**：真实授权 GOTV 历史实测覆盖 CS2 build 10955 / host 14192，后续构建已补充静态 descriptors 与离线合成回放核对；最新构建的真实在线复测仍在持续跟进（见 [#1](https://github.com/Starfie1d1272/cs2-headless-observer/issues/1)）。
- **多路观战**：同一 Steam 账号并行观战需连接不同的 GOTV 端点；连接同一 `IP:port` 的新会话会替换已有连接。
- **时间域边界**：组件仅交付来源时间线的结构化事实；实际提前量计算、节目画面对齐与 OBS 联动由消费应用负责。

更多细节请参阅[兼容性与验证范围](docs/compatibility.md)及[使用说明](docs/usage.md)。

---

## 📚 文档导航

- **使用与集成**：[使用说明](docs/usage.md) · [托管接口](docs/managed-interface.md) · [组件分发](docs/component-distribution.md)
- **开发与维护**：[架构说明](docs/architecture.md) · [构建指南](docs/build.md) · [验证体系](docs/verification.md) · [贡献指南](CONTRIBUTING.md) · [更新日志](CHANGELOG.md)
- **协议与证据**：[协议契约](docs/protocol/README.md) · [研究知识库](research/README.md) · [历史归档](archive/README.md)

---

## 🛠️ 从源码构建与验证

```bash
cd rust
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release
```

原生桥编译与完整 Windows 发行包组装请见[构建指南](docs/build.md)。

---

## 📄 许可证

本项目自有代码基于 **AGPL-3.0** 许可开源，并附 [Steamworks SDK 链接例外](LICENSE-STEAMWORKS-EXCEPTION.txt)。对应源码通过 GitHub Release tag 与源码归档提供；第三方组件适用各自许可（见[第三方来源](THIRD_PARTY_NOTICES.md)）。
