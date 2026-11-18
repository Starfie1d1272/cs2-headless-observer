# 应用托管接口

观察器以本机子进程方式接入应用。消费应用拥有来源选择、组件进程生命周期、时间对齐和展示。托管 v2 将连接重试交给组件内的 Session Supervisor。

## 启动与私有配置

从包清单的 `entrypoints` 获取 Python、driver、native 和 worker 路径。以绝对路径、`shell=false`、Windows 隐藏子窗口方式启动：

```text
<python> -B <driver> --managed
  --native <client/cs2_observer.dll>
  --steam-api <CS2/game/bin/win64/steam_api64.dll>
  --node <node.exe> --parser-worker <client/parser_worker.mjs>
  --source-role ahead --source-id <new-UUID>
  --host-version 14192 --output <new-local-directory>
```

环境使用 `SteamAppId=730`，Steam 提供真实合法账号上下文。每次启动组件使用新 UUID；准备输出父目录，由组件创建末级目录。默认 `--managed-protocol 1`，显式增加 `--managed-protocol 2` 启用组件内恢复。`source-role` 可选 `ahead` 或 `delayed`，实际时间线由消费应用绑定。

向 stdin 写入一行 UTF-8 JSON，包含 `endpoint`、`password`，行末为 LF，总计至多 4096 字节。地址使用数字 IP:port，IPv6 可使用方括号。密码支持至多 95 字节的 ASCII，空密码可显式传入。凭据通过私有 stdin 进入会话内存。

写入配置后保持 stdin 开放。EOF 或额外输入请求停止。完整调用见 [Python 示例](../examples/managed_consumer.py) 和 [Node 示例](../examples/managed_consumer.mjs)。

## 输出通道

stdout 为 UTF-8 JSONL，单条记录连同 LF 至多 64 KiB。消费者持续读取并按行处理任意流分块，对未完成行与消费队列设置边界。

stderr 包含原生日志、低频健康记录及最终报告，作为私有诊断通道处理。`report.json` 位于会话输出目录。托管会话默认仅保存报告，公共记录由 stdout 交付。

完整类型见 [JSON Schema](../schemas/managed-event.schema.json)，实际合成记录见[样例](../examples/managed-events.json)。

| 字段或记录 | 含义 |
| --- | --- |
| `source` / `channel` / `world` | v2 中 source 绑定整个组件运行，channel 从 1 起每次连接递增，world 每个 channel 从 1 起独立管理。v1 一次启动对应单次连接 |
| `kind=session-start` | v2 专用，`protocol=2`、`world=1`，首次连接及每次重连时建立新 channel，等待有效 cursor 后就绪 |
| `sequence` | 从 1 连续递增的公共记录顺序，v2 跨 channel 和 world 持续递增 |
| `kind=cursor` | 已提交实体快照的时间依据。兼容字段 `tick` 与 `committedTick` 都是该快照的正整数 tick，`tickInterval` 为每 tick 的秒数，`map` 为来源地图 |
| `type=raw-event` | `kind`、`name` 为事件名，`fields` 保留原始字段；其中 type9 玩家值表示控制器槽位 |
| `contextTick` / `networkTick` | 帧上下文与最近处理的网络 Tick。帧上下文可能为 0，事件仍以 `tick` 保留同一上下文 |
| `eventServerTick` / `committedTick` | 事件消息的 `server_tick`，以及处理事件时最后提交的实体快照 tick |
| `players` | 按事件玩家字段提供当前 controller 与 userinfo 的一致性证明：零基 `slot`、字符串 `steamId`、实际 `userId` 或 null、controller 的 index/serial；未知项为 null |
| `pawns` | 独立的 pawn index/serial 证明，按完整实体身份验证 |
| `actor` / `target` / `identityResolved` | 当前对 `weapon_fire`、`player_death` 提供投影身份结果；其他事件通过自身字段消费，投影值保持 null/false |
| `descriptorGeneration` | 事件目录代际，绑定本条记录的字段解释 |
| `kind=discontinuity` | 撤销当前就绪、身份和提示。v2 的 `scope` 为 `connection`、`world` 或 `snapshot`，`reason` 用于诊断 |

控制器槽位与 userinfo userid 分别保留。有效身份基于当前世界与 serial 证明；未知身份保持明确值。

各 tick 属于来源时间域。有效时间映射采用正整数 tick 与相应证据；null、0 等值表示该项时间依据尚未建立。接收墙钟和节目画面时间由消费应用另外记录。

## 本地时间与健康

新版 cursor 和事件附带可选的 `sdkQueueAgeUs`、`dequeueToSubmitUs`、`submitToObservedUs`、`resultQueueUs` 和 `observedAt`。这些字段按各记录所属的 GNS envelope 关联。前四项单位为微秒，未提供的 SDK 年龄为 null。

| 字段 | 计量范围 |
| --- | --- |
| `sdkQueueAgeUs` | Steam SDK 从收到应用消息至出队的本地时长 |
| `dequeueToSubmitUs` | Python 看到 SDK 出队至 parser IPC 入队，含已出队尾部等待、framing 与序列化 |
| `submitToObservedUs` | Python IPC 入队至 owner 消费结果，含发送、Node 处理、结果传输和结果排队 |
| `resultQueueUs` | 上一项的子区间，从 Python 读线程解析结果批至 owner 消费 |
| `observedAt` | Python owner 消费解析输出时的 Unix 毫秒，仅用于观测 |

同进程单调时钟计算 Python 驻留。Worker 单独汇总 base64 解码及协议事务耗时 `workerDecodeUs`。SDK 时间、Python 墙钟、节点单调计时和游戏 tick 各有自己的时域。SDK 年龄描述本地接收队列，上游播放位置、单程延迟以及绝对 freshness 仍为 unknown。stdout writer 完成表示写入管道，消费应用仍需观测其自身排队。报告的 `lastOutputSequence` 记录最后接纳入队的公共序号，与实际写入位置分别观测。

stderr 大约每秒尝试交付一条 `type=cs2-observer-health/1`，最终报告的 `health` 保留最后一次观测，按 source/channel/world 标识。记录包含 SDK 年龄、出队尾部、parser 和 stdout 的队列水位及驻留、窗口计数、预算用尽次数、context/network/committed tick 与已写入 stdout 的最后 cursor。窗口计数和时间跨度对应相同采样周期，队列峰值与预算用尽次数为本次尝试累计。诊断可丢失，游戏队列和公共 sequence 独立推进。

`state` 为 `unknown`、`catching-up`、`live`、`discontinuity` 或 `overloaded`，`reason` 描述判定依据。`live` 需要近期可用的 SDK 年龄、低排队及同一连续段的有效 cursor 持续前进并成功写入。gap、世界切换、暂停和 tick 停滞会使进度速率失效。`upstreamFreshness` 始终为 `unknown`。这些字段用于来源健康和诊断，展示时间仍由消费应用按来源证据计算。

## 就绪、扩展与停止

接纳匹配 source/channel/world 的有效 cursor 后建立就绪。断点、EOF、错误和来源替换撤销就绪；新的连续段从匹配代际的有效 cursor 恢复。

消费者支持忽略新增未知字段和未知记录种类。已知记录的结构、字节预算和完整行尾满足契约后才参与可信交付；就绪、身份和时间映射由已定义记录建立。

默认持续运行；`--seconds` 用于显式诊断时限。停止时先撤销应用侧投递，再关闭 stdin，v1 给予至少 12 秒、v2 给予至少 15 秒收尾宽限，超时后结束本应用拥有的进程。Windows 驱动通过 Job 管理解析器；宿主可用自己的 Job 将驱动绑定到应用生命周期。

正常 1038 在独立期限内有序排空通道和解析，写出 `source-hltv-stop` 断点并完成 stdout 排空。短突发可进入 `catching-up`。实时软阈值为 250 ms，硬保护为 2 秒，初始化内部队列可等待至多 10 秒。上线前的公共 cursor 和事件仍采用 2 秒保护。这些值是运行保护。

过载导致退出码 1，报告 `reason` 标识故障阶段。常见原因包括 `sdk-receive-overload`、`receive-staging-overload`、`parser-residence-overload`、`output-residence-overload`、`source-residence-overload`、`output-backpressure` 与 `output-closed`。发生过载时撤销仍待写入的公共记录。EOF、未完成行或失败报告均使原连续段失效。重连时分配新 source，等待新会话完成初始化并收到有效 cursor。退出码与报告字段见[使用说明](usage.md)。

### 托管 v2 的连接恢复

收到 `session-start` 才接纳新 channel。接纳匹配当前 source、channel、world 的有效 cursor 后恢复就绪。连接断点之后，旧 channel 不再接纳事实。world 变更由同 channel 的世界断点声明，快照恢复沿用当前 world。普通事件和 cursor 无权切换代际。消费应用可用 EOF 或组件异常退出撤销当前就绪。

SDK 或解析硬过载、意外传输断开、初始化超时和意外 parser 退出可以重连。退避以 500 ms 起步、每次翻倍，加入 ±20% 抖动，允许连续 5 次重试。有有效 cursor 且连续就绪 30 秒会重置退避。认证或协议拒绝、密码发出后一直无连接响应、确定性协议错误、公共 stdout 故障或无法确认旧实例清理时结束组件。初始化完成后的正常 1038 排空后结束组件。宿主只需要管理组件进程意外崩溃后的重启。v1 仍由消费应用管理单次连接重试，每次分配新 source。

v2 的 `supervisorForwardUs` 记录子进程提交转发至 Supervisor 接纳写入的时长，含内部管道和待转发队列。父子使用同一 Python 运行时的系统单调时钟计算，公共字段只提供时长。参见 [Python 单调时钟文档](https://docs.python.org/3.14/library/time.html#time.monotonic)。监督层仍使用 250 ms 软阈值与 2 秒实时硬保护。已经开始写入的完整行在连接断点前完成，未接纳的旧记录撤销。消费者停止读取时终止组件，EOF 后残缺行无效。

stderr 的 `cs2-observer-health/2` 包含连接代际、就绪、重连次数、最近故障、退避、转发和最终 stdout 交付位置，`attempt` 保留最近的当前代际底层摘要。磁盘最终报告为 `cs2-observer-report/2`，最多保留 8 条故障摘要和最后的健康状态。只有当前尝试使用临时报告目录，回收后删除。Supervisor 在内存中保留重连所需的最小私有配置，每次通过私有 stdin 发送，退出时清理。

## 运行时与版本

运行平台为 Windows x64。独立包提供运行时，`external-node` 使用调用方或 PATH 中的 Node.js 24.0.0 及以上版本，具备 WebAssembly、ReadableStream、structuredClone。

manifest 的 `managedProtocol` 声明默认 `cs2-observer-managed-json/1`，`managedProtocols` 同时列出可选的 `cs2-observer-managed-json/2`。1.x 保持公开字段含义、未知值、来源代际和停止语义；扩展采用新增字段或记录。原生 ABI、有序 IPC 与托管 JSON 各自独立标识，详见[组件分发](component-distribution.md)。

### 回合时钟快照

新版 cursor 提供 `roundClock`；旧版可能没有该字段。其 `committedTick` 是本条 cursor 对应的已提交快照 tick，与 cursor 的 source、channel、world、map 和 tickInterval 属于同一快照。对象内未知值为 null，不沿用前次值。

`totalRoundsPlayed`、`startTime` 和 `duration` 分别来自 GameRules 的已完成回合数、回合开始时间和回合时长；时间单位为秒。`freezePeriod`、`warmupPeriod`、`bombPlanted` 为对应的来源布尔值。`roundInProgress` 和 `roundWinStatus` 原样提供来源的回合进行标志和数值状态，不解释其枚举。`phase` 是不完整的快照分类，为 `warmup`、`freezetime`、`live`、`over` 或 `unknown`；当前仅有充分依据时输出 warmup 和 freezetime，freeze 结束本身不能证明 live。`pause` 包含 `active`、`totalPausedTicks`、`startTick`、`technical`，以及语义标记 `semantics`（当前为 `unknown`）。不要未经验证将暂停 tick 补偿进时钟。

`status` 统计 `totalRoundsPlayed`、`startTime`、`duration`、`freezePeriod`、`warmupPeriod`、`bombPlanted`、`pause.active`、`pause.totalPausedTicks`、`pause.startTick` 和 `pause.technical`；不计 `roundInProgress`、`roundWinStatus`、`phase` 或 `pause.semantics`。这十个来源值均可用时为 `available`，全部未知时为 `unavailable`，其他情况为 `partial`；它不证明 phase 或暂停计算语义。消费方仅在已知普通未暂停 live 的条件下，可用 `duration + startTime - committedTick * tickInterval` 计算剩余秒数。事件的 tick、networkTick、eventServerTick、committedTick 保持各自含义，快照 tick 不是事件精确时间。

现有输出还包括 cursor 来源时钟、事件原始字段、已验证身份和回合投影。解析器可解码的其他实体字段并不自动成为稳定公共接口：字段的类型、含义及生命周期需先有证据与规范，避免暴露内部对象或原始完整流。
