# 历史研发归档索引

早期研究阶段代码、阶段交接与历史探索已移出 `main` 工作树，由固定 Git 标签 `archive/research-era`（提交 `b680906`）完整保留，以便按原路径与原始摘要追溯或复现。当前运行与维护入口见[项目首页](../README.md)和[现行文档](../docs/architecture.md)。

## 固定引用与迁移去向

| 原路径 | 内容 | 当前状态 |
| --- | --- | --- |
| `archive/legacy/408`、`archive/legacy/409` | 文件增长与 relay 探索 | 已移出 `main`，见标签 `archive/research-era` |
| `archive/research-notes/` | 统一设计研究与按时间记录的实现过程 | 已移出 `main`，见标签 `archive/research-era`；有效约束已收敛至 `docs/protocol/` |
| `archive/parser-v1/` | Demo 包装 IPC 与对照脚本 | 已移出 `main`，见标签 `archive/research-era`；现行入口为 `client/ordered_parser_bridge.py`、`client/replay_ordered.py` |
| `archive/research-tools/` | 固定比较源码的研究脚本 | 已移出 `main`，见标签 `archive/research-era` |
| `archive/docs/`（阶段交接与早期证据） | `DESIGN.md`、`PHASE4-WIP.md`、`PHASE5-HANDOFF.md` 等 12 份阶段文档 | 已移出 `main`，见标签 `archive/research-era` |

## `main` 保留的历史证据

下列 `archive/docs/` 文件因仍被现行知识库摘要或文档直接引用而保留在 `main`：

- [CHANNEL-EVIDENCE.md](docs/CHANNEL-EVIDENCE.md)、[INITIALIZATION-EVIDENCE.md](docs/INITIALIZATION-EVIDENCE.md)：由 [`research/knowledge/sources.json`](../research/knowledge/sources.json) 固定 SHA-256 校验。
- [LIVE-2026-10-24.md](docs/LIVE-2026-10-24.md)：[兼容性](../docs/compatibility.md)引用的在线实测记录。
- [client-README.md](docs/client-README.md)：[验证](../docs/verification.md)引用的历史客户端说明。

迁移基线为 `0da25d0b51082979e50a47182bcb442abce7ae31`；[migration.json](migration.json) 保存 349 个原文件的路径映射与 `originalSha256` 摘要，可用于校验标签 `archive/research-era` 中的原始字节完整性。
