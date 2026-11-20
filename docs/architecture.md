# 架构

托管模式（v2）由 Session Supervisor 持有组件生命周期，以稳定 source 管理各次 GOTV 连接；单次连接通过私有 `--session-attempt` 子进程运行，在每次连接内部分别管理通道、世界与实体快照。交互诊断模式直接运行单次连接。

```text
交互启动器 / 消费应用
  → Session Supervisor（托管 v2）：启停、连接恢复、公开身份、stdout
  → 单次连接 Python driver：初始化控制、顺序、ACK 与 SDK/worker 生命周期
    → C++ 原生桥：官方 Steamworks API、认证、回调与网络收发
    → Node worker：schema、字符串表、实体事务、身份与事件
  ← JSON 记录、运行报告、退出状态
```

## 所有权与提交

单次连接内将状态划分为四类唯一 owner：**传输与认证**（`phase`、`_challenge`、`_account_id`）、**Signon 初始化**（`SignonSequence` 与 `WorldSyncState`，仅在当前世界与认证前提满足后推进）、**快照提交与 ACK**（`WorldSyncState` 仅消费通过 `checkpoint` 的 `receipt` 推进 `processed_entity_tick` / `baselineAck` / `FULL`，绝不把管道写入或接收进度当成已提交，`upstreamFreshness` 保持 `unknown`）、**资源生命周期**（`ManagedOwner`、`OutputWriter`、`OrderedParserBridge` Job）。

Supervisor 每次通过私有管道配置单次连接子进程，确认上一实例及其进程树已回收才创建下一实例。它消费内部完整 JSONL 行，通过数量有界的队列与一个 stdout 在途记录转发，按实际接纳写入分配公共序号。恢复前撤销未交付旧记录，完成已开始的行并发送断点。Driver 继续拥有 SDK 会话及解析子进程，C++ 桥管理官方接口的句柄和票据。Node 数据面统一解释 schema、类表、字符串表、实体与事件；驱动从实际解析完成的 checkpoint 和 receipt 推进初始化及 ACK。

正常 1038 收尾时，Supervisor 确认子进程完成报告、尾部交付与资源回收，再写出连接断点。启用 `--follow-source` 后，同一个 Supervisor 在没有旧连接和 Parser 的情况下等待原地址。每次尝试先交付新的 `session-start`，再启动独立子进程走完整认证和初始化。只有匹配代际且已交付的有效 cursor 才建立就绪。保留连接的世界重置继续使用世界断点。

实体更新以事务提交，来源代际、快照 epoch 与完整 serial 参与身份判定。控制器身份和 pawn 身份分别证明；未知值保留明确状态。世界重置撤销旧就绪、身份与待交付记录。

## 实时数据面

C++ 在 SDK owner 线程一次取至多 8 条 GNS 消息并记录各自的 SDK 出队年龄。SDK 持有原始内存，Python 按顺序消费时直接复制一份，每批消费完毕或会话退出时释放。已取出的尾部保留到下一轮，每条继续使用原出队时间。

驱动先消费已就绪的解析结果和需要推进的控制事务，再限量接收，最后推进结果与 ACK。接收和结果处理各有约 2 ms 的协作预算，并设数量和字节上限。一条合法 envelope 是原子边界，可以越过单轮目标。还有工作时立即继续，信用不足时等 worker 通知或短轮询期限，真正空闲时按 1–8 ms 有界退避。Steam SDK 反馈维持独立的 100 ms cadence。

初始化和控制屏障及时提交。进入 FULL 后，将当前已可用的 envelope 合并为一个有序 IPC 批，达到 64 条协议消息、256 KiB、控制屏障或单轮期限即可提交。高水位为 16 批、8192 条消息或 4 MiB 原始 payload，全部回到 8 批、4096 条与 2 MiB 时恢复接纳。一个合法 envelope 可越过批目标，硬上界包含该 envelope 的容量。信用到有序 `batch-complete` 才回收。管道写完只释放本地序列化缓冲。

Worker 按原顺序提交实体，结果分组返回，checkpoint 在批末及控制、世界和恢复边界及时推进。实体 receipt 只有通过覆盖它的 checkpoint 才进入 ACK owner，baseline ACK 与 FULL 保留原有条件。旧世界结果可归还旧批信用，已经退休的 receipt 永远无法授予当前世界 ACK。公共序号由驱动在进入 stdout 队列时编排。

固定版本 `svc_UserCmds=76` 对应 `CSVCMsg_UserCommands`。其客户端职责是命令历史和预测基线。驱动保留 framing、长度校验、可靠过滤和计数，省去 payload 提取及 worker 工作。其他消息保持现行处理路径。参见[入站控制证据](protocol/INBOUND-CONTROL-CONTRACT.md)。

## 输入、输出与停止

同一输入读取者处理私有配置和停止信号。公共记录由统一出口分配连续序号，经有界、可取消的写入队列交付。正常 1038 以独立期限排空 SDK、已接纳的解析批与 stdout，再发布终态。运行保护按阶段区分 SDK、SDK 已出队尾部、parser 与 stdout 的驻留。超过硬上限时终止来源并在报告写明断点原因，可恢复故障由 Session Supervisor 重连；owner 取消优先撤销旧来源交付。可选本地捕获经独立有界文件写入队列交付，饱和时标记截断，实时队列继续工作。

Windows 驱动持有解析器 Job，随驱动退出回收其自有 worker。Session Supervisor 在单独的 Job 中管理单次连接的进程树。消费应用拥有组件启停、业务数据消费和组件进程崩溃后的重启。

## 回放与辅助工具

`client/replay_ordered.py` 复用驱动和有序解析器，以本地帧文件替代网络端口。`tools/demo/` 提供 Demo 文件辅助解析，`tools/diagnostics/` 提供消息级研究工具。历史 Demo 包装器已归档至 Git 标签 `archive/research-era`（见[归档索引](../archive/README.md)）。

公开进程接口见[托管接口](managed-interface.md)，固定构建依据见[协议契约](protocol/README.md)，解析器源码组织见[构建](build.md)。
