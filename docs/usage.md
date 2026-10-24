# 使用说明

## Windows 便携包

解压到可写目录。Start.cmd 使用包内 Python、Node、原生桥和解析器；无需另装 Python 或 Node。
保持 Steam 已登录自己的合法账号，准备本机 CS2 安装目录、当前游戏 host version、获授权的数字 IP:port 观战地址和普通观战密码。程序使用本机 game/bin/win64/steam_api64.dll；该 DLL 不随包提供。

启动器从 steam.inf 提供版本建议，实际填写值以游戏 version 输出为准。支持范围见[兼容性](compatibility.md)。密码当前只支持不含 NUL 的 ASCII 字节，最长 95 字节；空密码可以显式输入。

Start.cmd 默认持续运行，直到 Ctrl+C、来源结束或失败；不再有五分钟默认停止或四小时上限。运行结果位于 runs/<UTC时间>/，默认只保存 report.json，事件由 stdout 输出。需要限定诊断时长时显式传入 --seconds <正整数>。

源码交互驱动可用 --capture 选择本机原始采集，events.jsonl 与 channel.frames 合计默认最多 256 MiB，可用 --capture-budget-mib 调整。达到预算后停止写入采集文件，观战继续，report.capture.truncated 为 true。采集是完整记录边界上的前缀，不是滚动录像；channel.frames 是应用通道记录，不是游戏原生 Demo。托管模式禁止原始采集。

Ctrl+C 请求清理。由应用托管时通过关闭 stdin 请求停止，详见[托管接口](managed-interface.md)。

## 退出和报告

| 退出码 | 含义 |
| --- | --- |
| 0 | 已初始化来源收到正常 HLTVSTOP 1038，清理完成 |
| 1 | 失败，包括清理或报告写入失败 |
| 2 | 已启动会话的不完整停止；也可能是参数用法错误，需结合报告和stderr判断 |

FULL 只表示处理过符合条件的完整快照；不代表任意赛事功能或任意来源验收通过。检查 reason、outcome、finalization_failures、解析检查点和实际事件。报告 schema 为 cs2-observer-report/1：reachedFull 表示本次运行曾到达 FULL，lastProcessedSequence 是内部已处理消息序号，lastOutputSequence 是公共输出序号；drainCompleted 表示正常来源结束的尾队列已排空，cleanupCompleted 表示各项清理完成。报告原子写入，reportWritten 表示写入成功；写入失败只可能在最终 stderr 报告中说明。不要用单一字段代替验收。

## 常见问题与下一步

先检查本次输出目录的 report.json，保留 reason、native_boot_code、steam_init_result、remote_end_reason 和 finalization_failures；字段不一定在每次报告中出现。参数或配置阶段未建立会话时，可能只有 stderr，没有报告。分享前检查内容，只私下提供必要记录。

| 现象或原因 | 下一步 |
| --- | --- |
| configuration-boundary | 使用获授权的数字 IP:port；密码为不含 NUL 的 ASCII，至多95字节。托管配置只包含 endpoint、password，保持 stdin 开放。 |
| native-start-failed | 核对 Steam 已登录合法账号、CS2 安装与本机 steam_api64.dll 路径，结合原始启动码判断。Steam 显示 CS2 运行中时，按[启动顺序](compatibility.md#多路连接与游戏客户端共存)停止自有观察器后再启动游戏。 |
| phase-timeout / initialization-timeout | 核对授权源仍在提供观战、密码和实际 source host；版本号可输入不等于该协议已验证。保留报告，重试使用新来源身份和新输出目录。 |
| output-backpressure / output-closed | 消费者持续读取 stdout，按记录预算处理分块；检查消费进程是否退出或阻塞。先停止旧观察器，不能用无限重连掩盖消费故障。 |
| source-drain-timeout、解析或清理失败 | 保留报告中的失败阶段；不要把来源结束或进程退出当作完整排空。确认自有旧进程退出后再尝试新来源。 |
| remote_end_reason=1000 | 这是通用关闭码。核对同账号是否已有游戏或观察器连接相同端点，并结合发生时间判断，不能只凭数字认定账号冲突。 |
| source-hltv-stop / 1038 | 已初始化来源正常结束；只有 drainCompleted、cleanupCompleted 和最终结果相符才算完整收尾。等待新授权来源，不反复争抢已结束连接。 |
| duration-limit-incomplete | 达到显式 --seconds 诊断时限；需要持续观战时省略该参数。默认运行没有五分钟或四小时停止限制。 |

## 离线重放

Replay.cmd 重放包内五帧合成样例，验证 cursor 和 round_freeze_end。它只证明工具链和输出可用，不含真实玩家、认证、网络初始化或真实比赛覆盖。

源码方式：

```powershell
python tools/replay_example.py --worker work/build/parser_worker.mjs
```

重放自己合法采集的应用通道，输入和输出均留本机，输出目录必须不存在：

```powershell
python client/replay_ordered.py --input <private-channel.frames> --worker work/build/parser_worker.mjs --host-version 14192 --output <new-private-output>
```

重放不初始化 Steam、不连接源、不发送网络应答。它不能证明认证或原生断开清理。

## 其他工具

tools/demo/decode.ts 是独立的 Demo/增长文件解析辅助工具；tools/diagnostics/capture.py 采集本机有限诊断；tools/diagnostics/replay.py 仅作旧消息级诊断。它们都不是实时接收的启动前置步骤。
