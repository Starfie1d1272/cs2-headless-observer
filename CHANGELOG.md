# 更新日志

## [Unreleased]

## 3.0.1 — 2026-11-26

### 修复

- **移除激进的 2 秒驻留硬杀重连**：取消 `driver.py`、`session_supervisor.py` 与 `attempt_runner.py` 中因 SDK 排队或 Parser 解析耗时超过 2 秒而主动断连重连的限制，避免初始化快照或短暂解析积压触发反复重连直至 `reconnect-budget-exhausted`。继续保留驻留时间健康指标上报、初始化/阶段超时及 stdout 阻塞背压保护。

## 3.0.0 — 2026-11-20

### 破坏性变更

- **正式退役公开托管协议 v1**：移除 `--managed-protocol 1` / `cs2-observer-managed-json/1` 对外支持，传入旧版本请求将显式拒绝并提示迁移至 `cs2-observer-managed-json/2`；Supervisor 内部单次连接改用私有 `--session-attempt` 接口。原生 ABI（`4`）、有序 IPC（`4`）与公开托管协议（`cs2-observer-managed-json/2`）保持向后兼容。

### 架构稳定化与运行时解耦

- **拆解单次连接外围职责**：移除混合职责的 `driver_support.py`，拆分为 `attempt_contract.py`（结果契约与分类）、`attempt_reporting.py`（基于显式 `HealthInputs` / `ReportInputs` 的纯投影）与 `attempt_runner.py`（CLI 与运行生命周期），并移除 `driver.py` 的冗余兼容重导出。
- **结构化错误分类与采样优化**：`ProbeError` 与 `DriverError` 携带稳定机器码与结构化 `transient` / `detail` 字段，彻底消除依赖诊断文本 `partition(": ")` 与类名字符串的错误分类；提前健康采样间隔检查，避免非采样周期执行冗余队列扫描。
- **退役旧 Demo 在线实体路径**：生产 Node worker 统一收敛至 `NativeObserverCore`，并核对保留所有生产必需的 `cs2parser` 上游补丁与解码证据。

### 可靠性与契约加固

- **进程回收与终态报告 fail-closed**：将 `ProcessJob.reap()`、进程等待与句柄关闭异常统一归类为 `AttemptCleanupError`，防止 `owner-stop` 掩盖既有清理或终态失败；完善 `AttemptResult` 的类型、类别与跨字段一致性校验，并在写盘失败时同步更新 `attemptResult`。
- **有序 IPC v4 全类型校验**：补全 `checkpoint`、`receipt.baselineAck`、`recovery`、`event-subscriptions`、`cursor`、`raw-event`、`gap`、`diagnostic`、`batch-complete` 与 `world >= 1` 的运行时形状与 tick 类型校验。

### 工程体系与发布门禁

- **测试分层与双平台 CI**：为 `tools/run_python_tests.py` 增加 `--fast` 单元模式供 `pnpm run test:fast` 使用，完整门禁仍严格禁止跳过；新增 Ubuntu `posix-lifecycle` 生命周期 CI 与 `client/parser_worker.mjs` / `AGENTS.md` 门禁检查。
- **文档同步**：重构 `README.md`，并同步更新架构、托管接口、组件分发、验证与 `AGENTS.md` 工程规范。

## 2.1.0 — 2026-11-19

- 托管 v2 新增可选的 `--follow-source`。正常 GOTV 结束且排空、清理完成后，组件低频重连同一授权地址，延续 source 与公共序号。默认仍在正常结束后退出。
- 托管健康与最终报告分别记录正常结束、跟随尝试和故障重连。包清单通过 `managedFeatures` 声明跟随能力。

## 2.0.0

- 实时路径按工作与预算推进，批量接收和解析，只有累计处理完成才回收信用。
- 记录 SDK 接收队列、解析和输出驻留，超龄时发布可恢复的来源退出原因。
- 保留 ID 76 的 framing、可靠过滤和计数，移除内部 payload 提取及 Node 转发。
- 原生 ABI 与有序 IPC 升至 4。托管 JSON 默认使用版本 2，内置 Session Supervisor、退避重连、新 channel 与稳定公共序号。原单次连接契约可通过显式指定 `--managed-protocol 1` 使用。
- 静态核对 CS2 1.41.9.8 / Steam build 26748068，兼容矩阵记录相应证据。

## 1.1.1

- 修复压缩字符串表省略可选解压长度时初始化失败的问题；从有效 Snappy 块读取长度，原始字节回退使用实际长度，继续执行解压与存储容量限制。

## 1.1.0

- cursor 新增同一已提交快照的回合时钟事实和明确的未知状态；暂停计算语义仍待验证。

## 1.0.0 — 2026-10-25

首个正式版本，提供 Windows x64 的 GOTV 后台接收与 JSON 事件输出。

### 功能

- 使用合法 Steam 普通观众身份连接获授权的 GOTV，输出来源实际提供的击杀、伤害、武器、炸弹和回合事件。
- 提供选手 Steam64、控制器槽位和可用的 pawn 身份证明，支持按来源和世界代际消费事件。
- 提供自带 Python、Node 的独立包，以及复用宿主 Node 的 `external-node` 包。
- 提供 `Replay.cmd` 本地自检、Python/Node 消费者示例和 JSON Schema。

### 相比 1.0.0-rc.1 的调整

- 默认持续观战至来源结束或主动停止；诊断时长和原始数据采集由参数显式选择，采集容量可配置。
- 完善来源结束排空、世界重置、输出背压和进程回收；消费者停止或关闭管道后可完成会话收尾。
- 统一跨世界的公共记录序号和 UTF-8 行预算，完善有效 Steam64 的识别及新增事件类型的隔离处理。
- 按来源握手和协议能力判断兼容性，已验证的 host 版本作为测试记录保留。
- 根据真实通道 profiling 减少投影字段读取中的复制开销。

适用条件、连接共存方式与在线补验范围见[兼容性](docs/compatibility.md)。许可及第三方材料见[第三方来源](THIRD_PARTY_NOTICES.md)。

## 1.0.0-rc.1

发布前候选包，提供普通 GOTV 接入、结构化事件、离线回放和托管进程接口，支持独立运行与复用外部 Node。
