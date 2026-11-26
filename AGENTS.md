# AGENTS.md — cs2-headless-observer 工程规范与导航

面向本仓库开发者与 Agent 的权威工程约定。公开接口以 [`README.md`](README.md) 与 [`docs/managed-interface.md`](docs/managed-interface.md) 为准，协议依据以 [`docs/protocol/README.md`](docs/protocol/README.md) 与 [`research/knowledge/README.md`](research/knowledge/README.md) 为准。

## 开发前核对

1. **开发前先核对开放 Issue**：动手前检查与当前任务相关的开放 GitHub Issue，避免重复建设或破坏已有边界：
   - **#1** 授权 GOTV 实机在线验证与兼容性门禁
   - **#52** 持续性能、资源成本与长期运行治理（仅由真实 profiling / 实测数据驱动，不做预防性重写）
   - **#53** CS2 Host、协议演进与兼容性维护
2. **Rust 单 Crate 4 模块架构（v4.0）**：核心实现位于 `rust/`（`cs2-headless-observer`），拆分为 4 个职责明确的模块，无子进程解析 worker 或内部 IPC：
   - **`rust/src/wire/`**：位流读取、LZ4/Snappy/Valve LZSS 解压、Protobuf 解码、GOTV 帧通道（`channel.rs`）与 Auth2/Auth3 握手（`handshake.rs`）。
   - **`rust/src/parser/`**：Source 2 schema（`schema.rs` / `schema_profile.rs`）、字段路径（`field_paths.rs`）、字符串表（`string_tables.rs`）、实体快照状态（`packet_entities.rs` / `entity_fields.rs`）、事件投影（`projection.rs`）与解码核心（`core.rs`）。
   - **`rust/src/native/`**：Native ABI 4 动态加载与生命周期管理（`abi.rs`，对接 `native/sdk_host.cpp`）及 GOTV ICE 密码加密（`password.rs`）。
   - **`rust/src/session/`**：`Supervisor`（`supervisor.rs`，公开 `cs2-observer-managed-json/3`、`channel` / `world` / `sequence` 与退避重连）、单次连接 `ObserverDriver`（`driver.rs`，握手、Signon、控制流、ACK 与 Native 调度）、异步 stdout/stderr 报告（`reporting.rs`）与离线合成回放（`replay.rs`）。
3. **诊断文本不决定控制**：`reason`、`health`、stderr 诊断仅用于观测与报告；恢复、重试和清理决策必须依据显式结构化字段或枚举（`AttemptCategory` / `RecoveryAction`）。
4. **时间域不得隐式混用**：严禁将 `contextTick`、`networkTick`、`committedTick`、`eventServerTick`、SDK 单调排队年龄（`sdkQueueAgeUs`）、单调时钟和墙钟 `observedAt` 混算。
5. **协议行为修改有证据**：改动协议/解码语义前先核对 `docs/protocol/`、`research/knowledge/` 或固定回归向量；不将离线 CI 通过等同于真实在线验证通过。
6. **小步收敛**：保持单一 Crate、零冗余抽象、有界退出排空与明确的所有权边界，不引入不必要的框架或双栈兼容层。

## 任务导航

| 任务 | 负责模块与入口 | 参考文档 |
| --- | --- | --- |
| 连接恢复与托管生命周期 | `rust/src/session/supervisor.rs`、`rust/src/session/reporting.rs` | [托管接口](docs/managed-interface.md)、[架构](docs/architecture.md) |
| 单次连接握手、Signon 与 ACK | `rust/src/session/driver.rs`、`rust/src/wire/handshake.rs`、`rust/src/wire/channel.rs` | [传输](docs/protocol/TRANSPORT-CONTRACT.md)、[恢复](docs/protocol/RECOVERY-CONTRACT.md) |
| 实体快照与事件投影 | `rust/src/parser/core.rs`、`rust/src/parser/packet_entities.rs`、`rust/src/parser/projection.rs` | [事件生命周期](docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)、[世界生命周期](docs/protocol/WORLD-LIFECYCLE-CONTRACT.md) |
| 认证、密码与原生桥 | `native/sdk_host.cpp`、`native/steam_bridge.hpp`、`rust/src/native/abi.rs`、`rust/src/native/password.rs` | [组件分发](docs/component-distribution.md) |
| 构建、打包与发版 | `rust/Cargo.toml`、`tools/build_native.py`、`.github/workflows/observer-rust.yml`、`.github/workflows/observer-research.yml` | [构建](docs/build.md)、[验证](docs/verification.md) |

## 版本标识

- **`managed protocol`**：`cs2-observer-managed-json/3`
- **`native ABI`**：`4`
- **`package schema`**：`cs2-headless-observer-package/6`

## 本地与 CI 验证

在 `rust/` 目录下运行（CI 覆盖 `ubuntu-latest` 与 `windows-2025`）：

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release
```
