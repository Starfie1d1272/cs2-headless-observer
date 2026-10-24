# 架构

```text
交互启动器 / 应用进程拥有者
  -> Python driver
     -> ctypes SDK 端口 -> 原生桥 -> 本机 Steam API / GOTV
     -> 应用帧、顺序、消息上下文和初始化控制
     -> OrderedParserBridge -> Node worker -> 固定解析器 NativeObserverCore
     <- 检查点、完整快照回执、恢复、事件
  <- JSON 事件 / 报告 / 退出状态
```

驱动拥有 SDK 会话，Python 桥拥有解析子进程。回执等待实际解析完成；收到网络消息不等于已提交实体快照。资源、队列和快照缓存有界。

来源、通道和世界代际随消息与回执传递；清表和恢复撤销旧就绪状态。控制器身份与 pawn 证明分开。网络时间、事件 server tick、提交 tick、接收时间和画面时间各有含义。

client/replay_ordered.py 复用同一个 ObserverDriver 和 OrderedParserBridge，替换网络端口为不发包的离线端口。它不会重现 Steam 认证或 SDK 原生断开通知。

tools/demo/ 是辅助文件解析路线，使用发布版解析器；archive/parser-v1/ 保留退出默认流程的 Demo 包装 IPC 原型。不能把两者当成当前有序 worker 的输入格式。

协议规则见[契约索引](protocol/README.md)，上游改动见[补丁说明](../patches/README.md)。
