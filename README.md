# CS2 Headless Observer

私有研发仓库。目标是以普通观众身份无画面接收获授权的 GOTV 流，输出比赛事件。

## 开发

Node 24、Python 3、pnpm 12.9.1。

- `pnpm install --frozen-lockfile`
- `pnpm test`
- `pnpm test:events`
- `pnpm typecheck`

固定解析器源码：`osztenkurden/cs2parser` 的 `deced963b86d3ec26b28a225824130fdf9fe3167`。
运行 `pnpm build:parser <源码目录> <输出 parser_worker.mjs>`，应用研究补丁、检查源码类型并构建独立解析进程。
Windows 包可通过 `Observer Research Package` 手动构建；触发前核对免费额度。2026-10-19 的 ABI 2 测试包已在云端交叉编译并私下交付，未使用私有 Actions 分钟，见[构建记录](client/PACKAGE-EVIDENCE.md)。

## 状态

185932 包的完整离线录像重放和合成网络初始化、双基线、PVS、缺帧恢复、完整快照分片与增量交错已验证。Windows 实际运行及完美普通观众在线互操作待集中实测。

研究说明与验证结果见 [client](client/README.md) 和 [初始化对照](client/INITIALIZATION-EVIDENCE.md)。

## 迁移

2026-10-19（北京时间）从 Mizar #410 迁入，基于公开 head `5ff1a5a13e007224550ae25f39ed846f06ca6293`，包含之后尚未公开的完整快照交错恢复实现。原始游戏二进制、反编译正文、认证凭据和用户诊断包不入库。

后续公开方式由用户决定。第三方源码与许可证保持各自许可；已有 Mizar 来源代码沿用原许可证。
