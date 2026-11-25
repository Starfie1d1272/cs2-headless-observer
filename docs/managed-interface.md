# 应用托管接口

观察器以本机单二进制子进程方式接入应用。消费应用拥有来源选择、进程启停、时间对齐和展示；托管 v3 将单次连接内的握手、断线重连与公共序号连续性交给内置 `Supervisor`。

## 启动与私有配置

从包清单（`cs2-headless-observer-package/6`）的 `entrypoints` 读取 `executable` 与 `native` 路径，以绝对路径、`shell=false`、Windows 隐藏子窗口方式直接启动：

```text
<cs2-headless-observer.exe> --managed
  --native <cs2_observer.dll>
  --steam-api <CS2/game/bin/win64/steam_api64.dll>
  --host-version 14192 --output <new-local-directory> [--seconds <f64>]
```

- 运行环境需设置 `SteamAppId=730` 且本机 Steam 已登录有效普通账号；`--output` 指向尚不存在的目录（由组件创建）。
- `--managed` 固定使用 `cs2-observer-managed-json/3`。
- 启动后向 `stdin` 写入一行 UTF-8 JSON（`{"endpoint":"IP:port","password":"..."}`，以 `\n` 结尾，不超过 4096 字节；密码支持至多 95 字节 ASCII，可为空字符串），随后保持 `stdin` 开放；**关闭 `stdin`（EOF）是唯一的优雅停止信号**。
- 若在写出 `report.json` 之前发生边界错误（例如输出目录已存在/不可创建，或 `stdin` 配置无效），进程会向 `stderr` 输出单行固定原因码（`output-directory-unavailable` 或 `configuration-boundary`）并以退出码 `1` 退出。

完整调用参见 [Python 示例](../examples/managed_consumer.py) 与 [Node.js 示例](../examples/managed_consumer.mjs)。

## 输出通道（stdout / stderr / report.json）

- **`stdout`**：UTF-8 JSONL，单条记录含换行符不超过 64 KiB。消费者须按行解析任意流分块，完整字段定义见 [JSON Schema](../schemas/managed-event.schema.json) 与[合成样例](../examples/managed-events.json)。
- **`stderr`**：纯诊断通道，周期性输出 `cs2-observer-health/3` JSONL（不参与控制）。
- **`report.json`**：会话结束时写入 `--output` 目录，遵循 `cs2-observer-report/3`。

| 记录或字段 | 含义 |
| --- | --- |
| `channel` / `world` | `channel` 从 1 起每次重连递增；`world` 每个 channel 从 1 起独立递增 |
| `sequence` | 从 1 起跨 `channel` 和 `world` 严格连续递增的公共序号 |
| `kind=session-start` | `protocol=3`、`world=1`；首次连接及每次重连时发送 |
| `kind=cursor` | 已提交实体快照的时间依据：`committedTick` 为正整数 tick，`tickInterval` 为每 tick 秒数，`map` 为地图名，附 `warmup`、`round` 与 `roundClock` |
| `kind=event` | `name` 为事件名，`eventTick`（优先 `server_tick`，否则 `context_tick`），`committedTick` 为当时最新已提交快照 tick，`residenceUs` 为本机累计驻留微秒，`fields` 与 `players` 保留原始字段与玩家身份 |
| `kind=discontinuity` | 撤销当前就绪与身份；`scope` 为 `connection`、`world` 或 `snapshot`，`reason` 仅用于诊断 |

各 tick 属于来源时间域；接收墙钟与节目画面时间由消费应用自行记录。

## 本地时间、健康与恢复（`HealthV3` / `ReportV3`）

`stderr` 周期输出 `type="cs2-observer-health/3"`，`state` 取值为 `connecting | receiving | ended | failed`：

- **纯观测不触发硬杀**：`sdkQueueAgeUs`、`sdkMaxAgeUs`、`decodeUs`（窗口累计解析微秒）与 `decodeMaxUs`（窗口单包最大解析微秒）**仅用于健康观测与诊断**。
- **重连与快速失败**：可恢复的网络/传输/握手/初始化超时与普通收发失败采用带抖动的指数退避（500 ms 起步，上限 30 s）持续重连，仅在真正发起下一次重连前递增 `reconnects`；首次连接阶段（尚未 `ever_full`）的 `Connection` 阶段超时（如密码错误或服务器无响应）直接快速失败（`outcome="failed"`）。
- **退出码与报告**：
  - 退出码 `0`：`outcome="closed"`（1038 HLTV 正常停播且排空完成）或 `outcome="stopped"`（`stdin` EOF 或 `--seconds` 到期主动停止）。
  - 退出码 `1`：`outcome="failed"`（启动失败、排空超时 `output-drain-timeout` 或不可恢复错误）。
  - 退出码 `2`：CLI 参数错误。
- 终态写入 `report.json`（`schema="cs2-observer-report/3"`），含 `outcome`、`reason`、`channel`、`world`、`lastOutputSequence`、`reconnects`、可选 `nativeBootCode` / `steamInitResult`、`phase`、`lastFault`、最近最多 8 条 `faults` 及最后一次 `health`。

### 回合时钟快照（`roundClock`）

`cursor` 可选包含 `roundClock`，与该条 `cursor` 属于同一已提交快照（未知字段为 `null`）：

- `totalRoundsPlayed`、`startTime`、`duration`（秒）、`freezePeriod`、`warmupPeriod`、`bombPlanted`、`roundInProgress`、`roundWinStatus` 与 `phase`（`warmup | freezetime | live | over | unknown`）。
- `pause` 包含 `active`、`totalPausedTicks`、`startTick`、`technical` 与 `semantics`（当前为 `unknown`，未经验证勿将暂停 tick 直接补偿进时钟）。
- `status` 统计上述 10 个来源字段（不含 `roundInProgress`、`roundWinStatus`、`phase`、`pause.semantics`）的可用性，取值为 `available`、`partial` 或 `unavailable`。
