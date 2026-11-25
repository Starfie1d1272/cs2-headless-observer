# 应用托管接口

观察器以本机单二进制子进程方式接入应用。消费应用拥有来源选择、进程启停、时间对齐和展示；托管 v2 将单次连接内的握手、重连退避与公共序号连续性交给内置 `Supervisor`。

## 启动与私有配置

从包清单（`cs2-headless-observer-package/5`）的 `entrypoints` 读取 `executable` 与 `native` 路径，以绝对路径、`shell=false`、Windows 隐藏子窗口方式直接启动：

```text
<cs2-headless-observer.exe> --managed
  --native <cs2_observer.dll>
  --steam-api <CS2/game/bin/win64/steam_api64.dll>
  --source-role ahead --source-id <new-UUID>
  --host-version 14192 --output <new-local-directory>
```

- 运行环境需设置 `SteamAppId=730` 且本机 Steam 已登录有效普通账号；每次启动使用新 UUID，`--output` 指向尚不存在的目录（由组件创建）。
- `--managed` 固定使用 `cs2-observer-managed-json/2`。`source-role` 可选 `ahead` 或 `delayed`。
- 当 `manifest.json` 的 `managedFeatures` 包含 `follow-source` 时，可追加 `--follow-source`，在来源正常 1038 结束后低频重连同一授权地址。切换地址时需关闭旧实例 `stdin` 并等待退出，再以新 UUID 与输出目录启动新实例。
- 启动后向 `stdin` 写入一行 UTF-8 JSON（`{"endpoint":"IP:port","password":"..."}`，以 `\n` 结尾，不超过 4096 字节；密码支持至多 95 字节 ASCII，可为空字符串），随后保持 `stdin` 开放；关闭 `stdin`（EOF）或发送任意额外字节（无需换行）即请求安全停止。
- 若在写出 `report.json` 之前发生边界错误（例如输出目录已存在/不可创建，或 `stdin` 配置无效），进程会向 `stderr` 输出单行固定原因码（`output-directory-unavailable` 或 `configuration-boundary`）并以非 0 退出。

完整调用参见 [Python 示例](../examples/managed_consumer.py) 与 [Node.js 示例](../examples/managed_consumer.mjs)。

## 输出通道（stdout / stderr / report.json）

- **`stdout`**：UTF-8 JSONL，单条记录含换行符不超过 64 KiB。消费者须按行解析任意流分块，完整字段定义见 [JSON Schema](../schemas/managed-event.schema.json) 与[合成样例](../examples/managed-events.json)。
- **`stderr`**：私有诊断通道，周期性输出 `cs2-observer-health/2` JSONL。
- **`report.json`**：会话结束时写入 `--output` 目录，遵循 `cs2-observer-report/2`。

| 记录或字段 | 含义 |
| --- | --- |
| `source` / `channel` / `world` | `source` 绑定整个组件运行；`channel` 从 1 起每次连接递增；`world` 每个 channel 从 1 起独立递增 |
| `kind=session-start` | 仅 `protocol=2`、`world=1`；首次连接及每次重连时发送，等待有效 `cursor` 后建立就绪 |
| `sequence` | 从 1 起跨 `channel` 和 `world` 连续递增的公共序号 |
| `kind=cursor` | 已提交实体快照的时间依据：`tick` 与 `committedTick` 为正整数 tick，`tickInterval` 为每 tick 秒数，`map` 为地图名 |
| `type=raw-event` | `kind` / `name` 为事件名，`fields` 保留原始字段；`eventServerTick` 为事件自带 `server_tick`，`committedTick` 为当时最新已提交快照 tick |
| `players` / `pawns` / `actor` / `target` | 基于当前世界 controller/userinfo/serial 证明的实体身份；`identityResolved` 为 `true` 时表示 `weapon_fire` / `player_death` 身份已解析 |
| `kind=discontinuity` | 撤销当前就绪与身份；`scope` 为 `connection`、`world` 或 `snapshot`，`reason` 仅用于诊断 |

各 tick 属于来源时间域；接收墙钟与节目画面时间由消费应用自行记录。

## 本地时间、健康与恢复（`HealthV2` / `ReportV2`）

`cursor` 与 `raw-event` 附带可选的 `sdkQueueAgeUs`（Steam SDK 本地入队至出队微秒数）与 `observedAt`（Unix 毫秒）。`upstreamFreshness` 始终为 `"unknown"`。

`stderr` 周期输出 `type="cs2-observer-health/2"`，`state` 取值为 `initializing | connected | catching-up | retiring | backoff | stopped`：

- **纯观测不触发硬杀**：`sdkQueueAgeUs`、`sdkMaxAgeUs`、`decodeUs`（窗口累计解析微秒）与 `decodeMaxUs`（窗口单包最大解析微秒）**仅用于健康观测与诊断**，不会因单包或窗口解析超过固定时长而主动断连重连。
- **就绪与退避**：接纳匹配当前 `source/channel/world` 的有效 `cursor` 后 `ready=true`；断线重连采用指数退避（`state="backoff"`，`waitReason="fault-retry"` 或 `"follow-source"`，附 `retryInMs`），`sourceEnds`、`followAttempts`、`reconnects` 分别计数。
- **有界退出与报告**：正常 1038 排空后发送 `discontinuity(scope="connection", reason="source-hltv-stop")`；异步 `stdout` 排空上限 2 秒、`stderr` 上限 200 ms。若 `closed` 终态排空超时导致 `cleanupCompleted=false`，则 `outcome` 置为 `"failed"` 并返回非 0 退出码。终态写入 `report.json`（`schema="cs2-observer-report/2"`），含 `outcome`、`reason`、`cleanupCompleted`、`reportWritten`、`lastOutputSequence`、可选 `nativeBootCode` / `steamInitResult`（`native-start-failed` 时提供）、`lastAttemptEnd`、最近最多 8 条 `faults` 及最后一次 `health`。

### 回合时钟快照（`roundClock`）

`cursor` 可选包含 `roundClock`，与该条 `cursor` 属于同一已提交快照（未知字段为 `null`）：

- `totalRoundsPlayed`、`startTime`、`duration`（秒）、`freezePeriod`、`warmupPeriod`、`bombPlanted`、`roundInProgress`、`roundWinStatus` 与 `phase`（`warmup | freezetime | live | over | unknown`）。
- `pause` 包含 `active`、`totalPausedTicks`、`startTick`、`technical` 与 `semantics`（当前为 `unknown`，未经验证勿将暂停 tick 直接补偿进时钟）。
- `status` 统计上述 10 个来源字段（不含 `roundInProgress`、`roundWinStatus`、`phase`、`pause.semantics`）的可用性，取值为 `available`、`partial` 或 `unavailable`。
