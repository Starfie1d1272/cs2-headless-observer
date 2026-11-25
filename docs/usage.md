# 使用说明

## 离线回放自检

解压 Windows x64 发行包到可写目录后，可直接运行内置合成通道回放检查解码与输出：

```powershell
.\cs2-headless-observer.exe replay --input examples\synthetic-channel.json --host-version 14191 --output work\replay-check
```

也可将 `--input` 指向本机合法采集的通道帧文件进行离线确定性回放（每次指定新的 `--output` 目录）。

## 托管模式运行（`--managed`）

1. 登录本机 Steam，确认 CS2 已安装且可访问 `game/bin/win64/steam_api64.dll`；若需同时运行图形客户端，先启动游戏再启动观察器。
2. 宿主应用通过 `manifest.json` 定位 `cs2-headless-observer.exe` 与 `cs2_observer.dll`，以 `--managed` 启动并从 `stdin` 传入 `{"endpoint":"IP:port","password":"..."}`（详见[托管接口](managed-interface.md)）。
3. 保持 `stdin` 开放持续消费 `stdout`；关闭 `stdin`（EOF）或达到可选诊断参数 `--seconds <秒>` 时限后，组件排空输出并退出。

## 退出码与终态报告

| 退出码 | 含义 |
| --- | --- |
| `0` | 正常结束（`closed`：1038 正常停播并排空完成；`stopped`：`stdin` EOF 或 `--seconds` 到期） |
| `1` | 终止性故障（启动失败、排空超时、配置边界或不可恢复错误） |
| `2` | 命令行参数解析失败（`clap` 或缺少必需参数） |

终态报告保存为 `<output>/report.json`（`cs2-observer-report/3`），包含 `outcome`（`closed | stopped | failed`）、`reason`、`channel`、`world`、`lastOutputSequence`、`reconnects`、`phase`、`lastFault`、`faults` 与最后一条 `health`。

## 常见问题

| 现象或 `reason` | 处理方式 |
| --- | --- |
| `output-directory-unavailable` | 为 `--output` 指定尚未存在的新目录。 |
| `native-start-failed` | 核对本机 Steam 登录状态、`--steam-api` 路径与 `SteamAppId=730` 上下文（可查看 `nativeBootCode` / `steamInitResult`）。 |
| `connection-timeout` / `phase-timeout` | 核对来源是否开放观战、`--host-version` 与密码；使用新 `--output` 重试。 |
| `output-backpressure` / `output-closed` | 检查消费端是否持续读取 `stdout`；处理任意流分块并保持消费队列有界。 |
| `remote_end_reason=1000` | 同账号多路观战须使用不同 GOTV 端点；参见[兼容性](compatibility.md#多路连接与游戏客户端共存)。 |
| `source-hltv-stop`（1038） | 来源正常结束；安全排空后以退出码 `0` 退出。 |
