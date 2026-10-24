# 验证

## 默认离线检查

按[构建步骤](build.md)从固定上游生成 worker 后运行：

```powershell
python tools/verify_all.py --parser-source work/parser --worker work/build/parser_worker.mjs
```

可追加 `--node <absolute-node.exe>` 选择共享运行时。报告记录实际 Node 版本、可执行文件和 worker 摘要。

检查覆盖原生 ABI、会话生命周期、七个解析组件、Python 与事件测试、类型、codec 对照、知识库、仓库链接、公开契约及合成回放。Windows 使用本机 MSVC，Linux 源码检查使用 g++；在线客户端的发布平台见[兼容性](compatibility.md)。

结果写入 `work/verification/<UTC时间>/verification.json` 与分项日志。完整通过要求所有必需项实际执行，并保持研究证据和协议材料的原始摘要。

## 真实捕获与性能

`client/replay_ordered.py` 重放本机授权通道，用同一份输入比较事件字段、顺序、代际和身份。样例及操作见[使用说明](usage.md)。

[性能检查](performance.md)记录投影字段与 GameRules 的采样方法、局部成本和总体回放耗时。实际制播负载按对应硬件、游戏与消费应用组合测量。

## SDK 与在线层级

`python tools/verify_sdk_drain.py --help` 提供 Windows 官方 SDK 本地 socket pair 检查，使用合法 Steam 上下文和本机游戏 DLL，覆盖连接关闭后的尾消息读取。

授权 GOTV 验证记录实际 build/host、握手、FULL、连续事件、来源结束和清理。首个 FULL 恢复与远程 1038 尾队列的补验范围集中在[兼容性](compatibility.md#验证证据)。

## 制品检查

手动 Windows 打包流程从固定输入编译原生桥，生成独立包和 external-node 包。`tools/verify_package.py` 核对清单、摘要、文档链接、WASM 源码、合成回放、启动失败清理及执行后的文件状态。

正式发布为源码和两类包固定同一提交，提供版本化资产、SHA256SUMS 与验证摘要。原始捕获保存在本机，公开样例采用合成输入。

## 研究工具

`tools/verification/verify.py` 提供 Linux Demo 增长文件、停止与截断对照，使用固定外部 fixture；来源和摘要见[历史客户端记录](../archive/docs/client-README.md)。`verify_channel.py`、`verify_password.py`、`verify_live.py` 的参数与 oracle 输入见各自 `--help`。

原生函数模拟的模块、工具链与固定输入见[研究配方](../research/tools/TYPE-PROFILE-REPRODUCTION.md)。
