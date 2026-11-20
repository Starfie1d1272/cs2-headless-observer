# CS2 Headless Observer

> 🎮 轻量级 CS2 GOTV 无图形后台观战与结构化事件接收组件

[![Platform](https://img.shields.io/badge/platform-Windows%20x64-0078D6)](#快速开始)
[![Protocol](https://img.shields.io/badge/managed%20protocol-v2-2EA44F)](docs/managed-interface.md)
[![Node](https://img.shields.io/badge/Node.js-%E2%89%A524.0.0-339933)](docs/component-distribution.md)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE-STEAMWORKS-EXCEPTION.txt)

**CS2 Headless Observer** 使用合法的普通 Steam 观众身份连接获授权的 CS2 GOTV 服务器，在不启动完整游戏客户端的情况下实时接收并解码 Source 2 网络帧，向消费应用持续交付有序、可信的 JSONL 比赛事件与时间游标。

它是 [Mizar](https://github.com/Starfie1d1272/Mizar) 的底层 Lookahead 数据接收组件，也可以作为独立工具或子进程组件接入任何赛事制播、数据采集或直播自动化系统。

---

## ✨ 核心能力

- 🔇 **无图形后台观战**：通过原生 Steamworks 桥接建立授权 GOTV 连接，无需渲染画面或启动 CS2 窗口。
- 📡 **结构化实时事件流**：输出回合时钟（`cursor`）、击杀、伤害、投掷物、炸弹事件与实体身份证明（Steam64 / Controller / Pawn）。
- 🔄 **连接恢复与来源跟随**：内置 `Session Supervisor` 管理断线退避重连、跨连接连续序号与 `--follow-source` 自动跟随换图/换场。
- 🛡️ **隔离且可控的资源边界**：多进程隔离网络收发与协议解析，支持有界背压、驻留超时保护、进程树回收与本地合成回放自检。
- 📦 **双形态分发**：提供开箱即用的独立包（`standalone`），以及供宿主应用集成复用的轻量组件包（`external-node`）。

---

## 🚀 快速开始

从 [GitHub Releases](https://github.com/Starfie1d1272/cs2-headless-observer/releases) 下载对应版本的 Windows x64 发行包：

| 发行包 | 适用场景 | 包含内容 |
| --- | --- | --- |
| **`standalone`** | 独立运行、人工值守或本地测试 | 内置 Python、Node.js 运行时、原生桥接、`Start.cmd` 与 `Replay.cmd` |
| **`external-node`** | 宿主应用集成（如 Mizar） | Python 协调层、原生桥接与解析 worker，复用宿主提供的 Node.js 24.0.0+ |

### 独立运行（3 步上手）

1. 解压发行包到可写目录，先双击或运行 `Replay.cmd` 完成离线合成自检。
2. 登录本机 Steam 客户端，准备好 CS2 安装目录以及获授权的 GOTV `IP:port` 与观战密码（如需同时运行游戏客户端，请先启动 CS2）。
3. 运行 `Start.cmd`，按提示填入路径、来源 host 版本与连接信息；组件将持续输出事件流，按 `Ctrl+C` 可安全排空并退出。

> 💡 **提示**：Steam 会将观众的 App 730 上下文显示为 CS2 运行状态。重启游戏客户端前，请先停止观察器并等待其进程完全退出。

---

## 🧾 输出示例与集成方式

组件通过 `stdout` 逐行输出 JSONL 记录（`cs2-observer-managed-json/2`），`stderr` 输出周期性健康快照与终态报告。以下是[合成自检输出](examples/managed-events.json)的典型片段（完整字段定义见 [JSON Schema](schemas/managed-event.schema.json)）：

```jsonl
{"kind":"session-start","source":"ahead:...","channel":1,"world":1,"sequence":1,"protocol":2}
{"kind":"cursor","source":"ahead:...","channel":1,"world":1,"sequence":2,"tick":100,"committedTick":100,"map":"de_test"}
{"kind":"round_freeze_end","source":"ahead:...","channel":1,"world":1,"sequence":3,"committedTick":100,"players":{},"identityResolved":false}
```

宿主应用按[托管接口契约](docs/managed-interface.md)通过私有 `stdin` 传入连接配置、读取 `stdout` 事件流，并以关闭 `stdin`（EOF）触发安全停止。可参考完整调用示例：[Python 消费者](examples/managed_consumer.py) · [Node.js 消费者](examples/managed_consumer.mjs)。

---

## 🧱 架构概览

```text
GOTV 服务器 ──▶ C++ Steam Bridge (ABI 4) ──▶ Python Driver & Supervisor (Managed v2) ──▶ JSONL 输出 ──▶ Mizar / 消费应用
                                                      │
                                                      ▼
                                            Node.js Worker (IPC 4)
                                       Schema · 快照事务 · 实体与事件投影
```

- **Managed v2 为唯一公开托管接口**：3.0.0 起正式退役旧版 `--managed-protocol 1`，所有连接级重试、世界代际隔离与公共序号重排统一由内置 `Session Supervisor` 承担。
- **职责清晰的单次连接域**：`Attempt Runner`、`Attempt Contract`、`Attempt Reporting` 与 `Observer Driver` 各自独立，状态所有权与错误分类均基于显式结构化字段而非诊断文本。

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

## 🛠️ 从源码验证

```bash
pnpm install --frozen-lockfile
pnpm run test:fast
```

完整生产离线门禁（需按[构建指南](docs/build.md)准备固定上游解析器与打包脚本）：

```bash
python tools/verify_all.py --parser-source work/parser --worker work/build/parser_worker.mjs
```

---

## 📄 许可证

本项目自有代码基于 **AGPL-3.0** 许可开源，并附 [Steamworks SDK 链接例外](LICENSE-STEAMWORKS-EXCEPTION.txt)。发行包随附完整对应源码与许可证声明，第三方组件适用各自许可（见[第三方来源](THIRD_PARTY_NOTICES.md)）。
