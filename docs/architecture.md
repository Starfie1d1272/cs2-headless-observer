# 架构

每个观察器进程拥有一个来源会话，以来源、通道和世界代际隔离解析状态。

```text
交互启动器 / 消费应用
  → Python driver：会话、初始化控制、顺序、ACK、进程与输出
    → C++ 原生桥：官方 Steamworks API、认证、回调与网络收发
    → Node worker：schema、字符串表、实体事务、身份与事件
  ← JSON 记录、运行报告、退出状态
```

## 所有权与提交

Python 驱动拥有 SDK 会话及解析子进程，C++ 桥管理官方接口的句柄和票据。Node 数据面统一解释 schema、类表、字符串表、实体与事件；驱动从实际解析完成的 checkpoint 和 receipt 推进初始化及 ACK。

实体更新以事务提交，来源代际、快照 epoch 与完整 serial 参与身份判定。控制器身份和 pawn 身份分别证明；未知值保留明确状态。世界重置撤销旧就绪、身份与待交付记录。

## 输入、输出与停止

同一输入读取者处理私有配置和停止信号。公共记录由统一出口分配连续序号，经有界、可取消的写入队列交付。正常来源结束依次排空已接收数据和解析结果，再发布终态；owner 取消先撤销旧来源交付，再清理资源。

Windows 驱动持有解析器 Job，随驱动退出回收其自有 worker。消费应用负责驱动本身的生命周期、重试和应用级退出回收。

## 回放与辅助工具

`client/replay_ordered.py` 复用驱动和有序解析器，以本地帧文件替代网络端口。`tools/demo/` 提供 Demo 文件辅助解析，`tools/diagnostics/` 提供消息级研究工具。历史 Demo 包装器保存在 `archive/parser-v1/`。

公开进程接口见[托管接口](managed-interface.md)，固定构建依据见[协议契约](protocol/README.md)，解析器源码组织见[构建](build.md)。
