# 历史研发归档

本目录按原文和原始代码保存各阶段材料，用于追溯证据和复现对应版本。当前运行与维护入口见[项目首页](../README.md)和[现行文档](../docs/architecture.md)。

| 目录 | 历史内容 | 当前入口 |
| --- | --- | --- |
| `docs/` | 阶段交接、客户端说明、采集路线、实测与包装记录 | 根 README、`docs/` |
| `research-notes/` | 统一设计研究和按时间记录的实现过程 | `docs/protocol/`、`research/knowledge/` |
| `parser-v1/` | Demo 包装 IPC 与对照脚本 | `client/ordered_parser_bridge.py`、`client/replay_ordered.py` |
| `research-tools/` | 固定比较源码的研究脚本 | `research/tools/` |
| `legacy/408`、`legacy/409` | 文件增长与 relay 探索 | `client/` 普通观众路线 |

迁移基线为 `0da25d0b51082979e50a47182bcb442abce7ae31`；[migration.json](migration.json)保存 349 个原文件的路径映射与原始摘要。历史命令按相应提交、worker、依赖及工作区复现。

完整对应源码包包含这些归档。研究 JSON、压缩向量和历史报告保持原字节；现行协议文档的结构性维护与摘要索引同步记录。
