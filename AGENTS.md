# AGENTS.md — cs2-headless-observer 工程规范与导航

面向本仓库开发者与 Agent 的权威工程约定。公开接口以 [`README.md`](README.md) 与 [`docs/managed-interface.md`](docs/managed-interface.md) 为准，协议依据以 [`docs/protocol/README.md`](docs/protocol/README.md) 与 [`research/knowledge/README.md`](research/knowledge/README.md) 为准。

## 开发前核对

1. 核对开放重构系列 Issue（#30–#37）的边界与依赖：
   - **#30** 生产链路一致性与已确认缺陷修复
   - **#31** 早期研究路线与历史材料归档（`archive/research-era` 标签）
   - **#32** 退役旧 Demo 在线实体适配器，收敛生产解析路径
   - **#33** 开发者入口、术语、`AGENTS.md` 与分层验证规范
   - **#34** 正式退役公开 Managed v1，分离私有单次连接 Attempt 接口
   - **#35** 精简 `client/driver.py` 外围职责
   - **#36** 重构 Supervisor 与生命周期基础设施
   - **#37** 重构 IPC、初始化与快照 ACK 状态所有权
2. **每类状态唯一 owner**：
   - **Session Supervisor**（`client/session_supervisor.py`）：公开 `cs2-observer-managed-json/2` 输出、`source` / `channel` / `public sequence`、连接恢复与 `--follow-source`。
   - **单次连接 Driver**（`client/driver.py`）：单次连接握手、Signon、控制流、ACK、SDK 与 worker 协调。
   - **Node Worker**（`client/parser_worker.mjs` + `parser/src/`）：schema、类表、字符串表、实体快照与事件投影。
   - **Native Bridge**（`native/` + `client/sdk.py`）：Steamworks API、认证句柄与 GNS 收发。
3. **诊断文本不决定控制**：`reason`、`health`、stderr 诊断仅用于观测与报告；恢复、重试和清理决策必须依据显式结构化字段或枚举。
4. **时间域不得隐式混用**：严禁将 `contextTick`、`networkTick`、`committedTick`、`eventServerTick`、SDK 单调排队年龄、Python 单调时钟和墙钟 `observedAt` 混算。
5. **研究代码不默认进入生产**：`tools/diagnostics/`（含 `LiveDecoder`）、`tools/demo/` 与 `research/` 不作为生产控制或事件解析权威。
6. **协议行为修改有证据**：改动协议/解码语义前先核对 `docs/protocol/`、`research/knowledge/` 或固定回归向量；不将未实测的在线行为写成已验证事实。
7. **小步收敛**：优先复用现有模块与普通函数/小型类型，不引入无必要框架、DI 容器、事件总线或兼容双栈。

## 任务导航

| 任务 | 负责模块与入口 | 参考文档 |
| --- | --- | --- |
| 连接恢复与托管生命周期 | `client/session_supervisor.py`、`client/process_io.py` | [托管接口](docs/managed-interface.md)、[架构](docs/architecture.md) |
| 单次连接握手、Signon 与 ACK | `client/driver.py`、`client/handshake.py`、`client/channel.py`、`client/control.py` | [传输](docs/protocol/TRANSPORT-CONTRACT.md)、[恢复](docs/protocol/RECOVERY-CONTRACT.md) |
| 实体快照与事件投影 | `client/parser_worker.mjs`、`parser/src/parser/entities/nativeObserverCore.ts` | [事件生命周期](docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)、[世界生命周期](docs/protocol/WORLD-LIFECYCLE-CONTRACT.md) |
| 认证、密码与原生桥 | `native/sdk_host.cpp`、`native/steam_bridge.hpp`、`client/sdk.py`、`client/password.py` | [组件分发](docs/component-distribution.md) |
| 进程输入/输出与子进程清理 | `client/process_io.py`、`client/process_job.py`、`client/ordered_parser_bridge.py` | [使用说明](docs/usage.md) |
| 构建、打包与发版 | `tools/build_parser.mjs`、`tools/build_native.py`、`tools/package_windows.py`、`.github/workflows/observer-research.yml`（Windows 打包） | [构建](docs/build.md)、[验证](docs/verification.md) |

## 术语与版本导航

- **Steam bridge vs Source 2 parser**：`native/` + `client/sdk.py` 负责 Steam 认证与 GNS 传输；`client/ordered_parser_bridge.py` + `client/parser_worker.mjs` 负责 Source 2 schema 与实体/事件解码。
- **序号域**：`parser sequence`（Python->Node IPC 内部消息序号）、`attempt sequence`（单次连接 driver 内部输出序号）、`public sequence`（Supervisor 对外分配的连续递增序号）。
- **Tick 域**：`contextTick`（帧/消息接收上下文）、`networkTick`（最近处理的 `net_Tick`）、`committedTick`（已提交实体快照 tick）、`eventServerTick`（游戏事件消息自带的 `server_tick`）。
- **代际与世界**：`source`（组件级来源标识）、`channel`（v2 每次连接递增）、`world`（单次连接内 `svc_ClearAllStringTables` / `CHANGELEVEL` 递增）、`snapshot`（同一世界内的 FULL/delta 快照 epoch）。
- **健康与新鲜度**：`local processing health`（本地 SDK/staging/parser/stdout 排队与驻留状态）；`upstreamFreshness` 始终为 `unknown`。
- **版本标识**：`managed protocol`（`cs2-observer-managed-json/2`）、`native ABI`（ABI 4）、`ordered IPC`（protocol 4）、`ordinaryViewerProtocol`（2，上游补丁接缝标识）。

## 分层验证

- **快速检查**：`pnpm run test:fast`（格式化、lint、TypeScript 类型检查、Node 事件测试、Python 单元测试）。
- **生产链路完整门禁**（需先按 [构建](docs/build.md) 准备 `work/parser` 与 `work/build/parser_worker.mjs`）：`python tools/verify_all.py --parser-source work/parser --worker work/build/parser_worker.mjs`。
- **发布验收**：`python tools/verify_package.py <dist-dir>`（检查 Windows 独立包与 `external-node` 制品、清单、摘要、合成回放与清理）。
- **独立 Research**：`tools/verification/verify.py`、`tools/verification/verify_live.py` 等仅用于离线对照或固定证据复现。
