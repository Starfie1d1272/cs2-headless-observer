# 使用说明

## 启动独立包

1. 将 `windows-x64` 包解压到可写目录，运行 `Replay.cmd` 完成本地自检。
2. 登录 Steam，准备 CS2 安装目录与获授权的 GOTV 地址、密码。需要共用账号的图形客户端时，先启动游戏。
3. 运行 `Start.cmd`，填写 CS2 路径、来源 host 版本和连接信息。

启动器从 `steam.inf` 提供 host 建议值，实际来源版本由使用者核对。地址使用数字 IP:port；密码支持至多 95 字节的 ASCII，空密码可显式输入。程序使用本机 `game/bin/win64/steam_api64.dll`。

会话持续运行至来源结束或主动停止。Ctrl+C 请求清理；等待进程退出后可开始新会话。Steam 中的运行状态和共存顺序见[兼容性](compatibility.md#多路连接与游戏客户端共存)。

## 输出与采集

独立入口将会话报告写入 `runs/<UTC时间>/report.json`，事件从 stdout 输出。托管调用可选择自己的输出目录，见[托管接口](managed-interface.md)。

直接调用 `client/driver.py` 时，可用 `--seconds <正整数>` 选择诊断时限。原始采集由独立交互驱动的 `--capture` 开启，`--capture-budget-mib` 设置容量，默认 256 MiB。`Start.cmd` 使用启动器默认参数。

采集生成 `events.jsonl` 与 `channel.frames`，共享总容量预算。写入保留完整记录前缀；达到预算后会话继续，报告中的 `capture.truncated` 标记采集范围。通道文件用于本地回放，游戏原生 Demo 使用游戏提供的格式。托管模式以 stdout 交付记录，默认文件输出为会话报告。

报告按需私下分享，原始比赛材料留在本机。

## 退出与报告

| 退出码 | 含义 |
| --- | --- |
| 0 | 已初始化来源正常结束，排空和清理完成 |
| 1 | 运行、清理或报告写入失败 |
| 2 | owner 停止、诊断时限等不完整停止，或参数用法错误；结合报告与 stderr 判断 |

报告格式为 `cs2-observer-report/1`，以原子替换方式保存。

| 字段 | 含义 |
| --- | --- |
| `reason` / `outcome` | 会话结束原因和结果 |
| `reachedFull` | 该次运行曾到达有效完整快照状态 |
| `lastProcessedSequence` | 内部已处理消息序号 |
| `lastOutputSequence` | 已接纳的公共输出序号 |
| `drainCompleted` | 正常来源结束的尾队列已排空 |
| `cleanupCompleted` | 自有资源清理完成 |
| `reportWritten` | 报告写入完成；写入失败时由最后的 stderr 报告提供结果 |
| `finalization_failures` | 收尾失败的具体阶段 |

FULL 描述协议状态。来源当前是否可用由匹配代际的 cursor 和断点决定，完整验收结合事件、来源画面与对应验证记录判断。

## 常见问题

配置阶段的信息由 stderr 提供；建立会话输出目录后，结合 `report.json` 中的原始启动码、Steam 初始化结果、远端结束码与失败阶段定位。

| 现象或原因 | 处理方式 |
| --- | --- |
| `configuration-boundary` | 使用获授权的数字 IP:port、支持的密码字节；托管配置包含 `endpoint`、`password`，随后保持 stdin 开放。 |
| `native-start-failed` | 核对 Steam 登录、CS2 安装及本机 DLL 路径，保存 `native_boot_code`、`steam_init_result`。 |
| `phase-timeout` / `initialization-timeout` | 核对来源当前提供观战、实际 host 和密码；保存报告，重试时分配新来源身份与输出目录。 |
| `output-backpressure` / `output-closed` | 检查消费者存活和持续读取状态；按 JSON 行处理任意分块，停止旧会话后再建立新会话。 |
| `source-drain-timeout`、解析或清理失败 | 保存失败阶段与报告，确认自有旧进程已退出，再开始新的来源尝试。 |
| `remote_end_reason=1000` | 结合操作时间、端点和完整回执判断；共存客户端使用不同端点。 |
| `source-hltv-stop` / 1038 | 对照 `drainCompleted`、`cleanupCompleted` 和最终结果确认来源收尾，之后等待新的授权来源。 |
| `duration-limit-incomplete` | 达到显式诊断时限；持续观战使用默认运行时长。 |

## 离线回放

`Replay.cmd` 使用五帧合成样例检查 cursor 与 `round_freeze_end` 输出。源码方式：

```powershell
python tools/replay_example.py --worker work/build/parser_worker.mjs
```

回放本机合法采集的应用通道，使用新的输出目录：

```powershell
python client/replay_ordered.py --input <private-channel.frames> --worker work/build/parser_worker.mjs --host-version 14192 --output <new-private-output>
```

回放在本地复用驱动与解析器，检查捕获内的数据处理。Steam 认证、SDK 回调与在线来源接受行为使用[对应验证层级](verification.md)。

## 辅助工具

`tools/demo/decode.ts` 提供 Demo/增长文件解析，`tools/diagnostics/` 保存消息级诊断与采集入口。各脚本参数见其 `--help`；技术研究与运行入口的职责见[架构](architecture.md)。
