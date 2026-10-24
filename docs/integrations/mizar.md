# Mizar 接入示例

Mizar 是通用观察器的一个消费者，不是运行前置条件。

## Mizar 现有接入

已合并基线 Mizar 6f787d44c1f597f7e125fe9d7a99bead2d5729ca 的 startObserverProcess 接收 Python、driver、native、Steam API、Node、worker 和输出目录路径。
它用 spawn 启动托管子进程，consumeObserverOutput 逐行读取输出，来源管理器消费事件。可恢复失败采用 1/2/4/8/15 秒有界退避；先清理旧进程，再使用新 UUID 启动。

这是文件路径配置与进程协议接缝。该能力不自动意味着 Mizar 已实现下载器、安装器、默认应用接线或完整私有提示产品。ObserverAssistProjection 仍是独立的未完成部分。

公开分发建议为源码仓库加 Windows x64 便携 Release；Mizar 固定一个经验证的包版本、核验摘要、配置上述路径。自动下载/升级及 UI 留待消费端另行设计。

随 Mizar 分发时可选择不带重复 Node 的组件，按发行回执定位运行文件；最低运行时及后续更新边界见[组件分发](../component-distribution.md)。

通用包类型为 `external-node`，不指定 Node 小版本和哈希。Mizar 自己可固定运行时以重现产品构建；它在组装阶段检查最低 Node 要求，并把实际版本和摘要记入回执。
