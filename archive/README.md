# 历史研发归档

归档内容保留原文与原始代码，退出默认执行与测试入口；完整对应源码包仍保留这些历史材料。旧文档的相对路径及阶段状态保留历史上下文；查找新位置使用 migration.json，不把旧命令直接套到当前 checkout。

| 目录 | 历史内容 | 当前入口 |
| --- | --- | --- |
| docs/ | 阶段交接、旧客户端说明、采集路线、实测与包装记录 | 根 README、docs/ |
| research-notes/ | 统一设计研究过程、门槛与按时间追加的实现记录 | docs/protocol、research/knowledge |
| parser-v1/ | 旧 Demo 包装 IPC 与两个对照脚本 | client/ordered_parser_bridge.py、replay_ordered.py |
| research-tools/ | 依赖旧 gotv-parser-audit 源码的比较脚本 | research/tools 的固定证据复现 |
| legacy/408、409 | 迁移前的文件增长与 relay 探索 | client/ 当前普通观众路线 |

迁移基线为 0da25d0b51082979e50a47182bcb442abce7ae31；migration.json 为全部 349 个原文件记录旧路径、新路径与原始摘要。
历史材料可用固定 Git 提交还原；parser-v1 四个文件本身不是自包含可运行包，还需要当时匹配的 worker、依赖和调用方。

研究 JSON、压缩向量和历史报告按原字节保留；维护中的协议文档仅修正可解析的相对链接，摘要索引同步更新。
归档不是脱敏措施；公开前仍要审查完整历史和拟分发资产。
