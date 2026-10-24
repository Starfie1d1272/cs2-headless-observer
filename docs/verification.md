# 验证

字段读取与GameRules扫描的离线profiling结果见[性能检查](performance.md)。局部采样变化与整体回放耗时分开记录，不以合成启动或局部基准代替实际制播负载。

先按[构建步骤](build.md)从固定干净上游生成 worker，再执行：

```powershell
python tools/verify_all.py --parser-source work/parser --worker work/build/parser_worker.mjs
```

验证指定共享运行时可追加 `--node <absolute-node.exe>`。该路径传给解析组件、Python 子进程和离线样例，报告记录实际 Node 版本与可执行文件摘要。外部Node的版本和摘要仅作为测试来源记录，不是运行准入条件。

默认检查包括：合成原生 ABI、10 项会话生命周期、七个解析组件、Python 测试、TS 事件测试、仓库类型检查、四项旧解析路径 codec 回归、知识库、目录和链接、合成通道重放。
Windows 自动发现本机 MSVC；Linux 需要 g++。默认检查不登录 Steam、不使用游戏 DLL、不连接观战源。

每轮生成 work/verification/<UTC时间>/verification.json 和各项日志。必需测试跳过会失败；无 GOTV_ORDERED_WORKER 或 ABI 编译工具不能当成完整通过。
research/data、research/evidence 与协议文档只读；检查前后摘要必须一致。

## 其他验证层级

- tools/verification/verify.py 是 Linux 专用的公开 Demo 增长文件/停止/截断对照，需要外部固定 fixture；不属于 Windows 默认检查。
- verify_channel.py、verify_password.py 与 verify_live.py 需要明确的独立 oracle 或系统库输入，按各脚本 --help 使用。
- research/tools 中的原生模拟需要独立研究环境、固定模块和摘要，详见[研究说明](../research/README.md)。
- 实际 SDK 编译和便携包验证由手动打包流程完成；验证包内 runtime、导出、哈希和合成重放不等于在线验收。
- 本机真实捕获可用 client/replay_ordered.py 做回归，不提交原始素材，也不将离线结果称为新在线连接。

公开 Demo fixture 的固定来源、SHA-256 和历史 oracle 说明保留在[历史客户端说明](../archive/docs/client-README.md)。本轮不把网络下载作为默认回归前置条件。

默认验证还覆盖托管 JSON Schema、消费者世界代际、缓冲配置后立即停止、输出管道堵塞与关闭、驱动强杀后的解析器回收。需要本机合法 Steam 和游戏 DLL 时，可运行 `python tools/verify_sdk_drain.py --help`，以官方 SDK 本地 socket pair 检查关闭后尾消息仍可读取；该测试不连接比赛，不等同 GOTV 在线验收。
