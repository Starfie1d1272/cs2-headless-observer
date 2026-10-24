# 使用说明

## Windows 便携包

解压到可写目录。Start.cmd 使用包内 Python、Node、原生桥和解析器；无需另装 Python 或 Node。
保持 Steam 已登录自己的合法账号，准备本机 CS2 安装目录、当前游戏 host version、获授权的数字 IP:port 观战地址和普通观战密码。程序使用本机 game/bin/win64/steam_api64.dll；该 DLL 不随包提供。

启动器从 steam.inf 提供版本建议，实际填写值以游戏 version 输出为准。支持范围见[兼容性](compatibility.md)。密码当前只支持不含 NUL 的 ASCII 字节，最长 95 字节；空密码可以显式输入。

Start.cmd 默认运行 300 秒。运行结果位于 runs/<UTC时间>/：report.json、events.jsonl 和 channel.frames。后两项含源数据，默认留本机。channel.frames 是应用通道记录，不是游戏原生 Demo。

Ctrl+C 请求清理。由应用托管时通过关闭 stdin 请求停止，详见[托管接口](managed-interface.md)。

## 退出和报告

| 退出码 | 含义 |
| --- | --- |
| 0 | 已初始化来源收到正常 HLTVSTOP 1038，清理完成 |
| 1 | 失败，包括清理或报告写入失败 |
| 2 | 已启动会话的不完整停止；也可能是参数用法错误，需结合报告和stderr判断 |

FULL 只表示处理过符合条件的完整快照；不代表任意赛事功能或任意来源验收通过。检查 reason、outcome、finalization_failures、解析检查点和实际事件。现有 online_success=INCONCLUSIVE 字段不代替独立验收记录。
report.json 内 report_written 可能仍为 false；进程最后输出的报告才记录写入完成状态。

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
