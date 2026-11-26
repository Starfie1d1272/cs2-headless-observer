# 兼容性与验证范围

## 运行条件

| 项目 | 当前范围 |
| --- | --- |
| 运行平台 | Windows x64，合法 Steam App730 普通观众上下文 |
| 本机依赖 | 已登录的 Steam、已安装的 CS2（提供 `steam_api64.dll`）、获授权的数字 `IP:port` 与观战密码 |
| 分发形态 | 单一纯 Rust 制品（`cs2-headless-observer.exe` + `cs2_observer.dll`，无外部 Python/Node 依赖） |
| 协议与 ABI | 原生 ABI `4`、托管 JSON 契约 `cs2-observer-managed-json/3`、包清单 `cs2-headless-observer-package/6` |
| 已验证基线（历史 v1–v3 实测） | 真实授权 GOTV 实测覆盖 CS2 build 10955 / host 14192（Patch 1.41.9.2）；静态核对至 Steam build 26748068 / host 14198 |

CLI 接受非零 `uint32` `--host-version`，`manifest.json` 中的 `validatedHostVersions` 记录已验证范围。4.0.0 完整继承原生 ABI 4、Managed JSON v2 与协议解码语义，并已通过 `MockPort` 集成测试与合成通道回放；最新 CS2 构建的 4.0.0 真实在线复测持续在 [#1](https://github.com/Starfie1d1272/cs2-headless-observer/issues/1) 跟进。

## 身份、时间与来源切换

- 控制器身份由当前世界 controller 与 userinfo 一致性证明，pawn 另行验证完整 serial；世界重置或空 userinfo 撤销旧身份。
- 切换 GOTV 端点或独立重启时，须使用新的 `--output` 目录启动新实例。

## 多路连接与游戏客户端共存

观察器使用真实 Steam App730 上下文。共用账号时先启动图形游戏再启动观察器；重启游戏前先停止观察器并等待进程退出。同一账号连接同一 `IP:port` 会替换已有连接（触发 `remote_end_reason=1000`），并行观战需为各客户端分配不同 GOTV 端点。

> **历史实测参考（v1.x，2026-10-24）**：旧版 Python/Node 架构在 Windows 6 路并行（16 逻辑核）下实测 CPU 中位约 20.0%、工作集内存中位约 2084 MiB（详见[2026-10-24 记录](../archive/docs/LIVE-2026-10-24.md)）。4.0.0 已转为纯 Rust 单二进制并在离线真实回放中取得约 15× 解码提速，4.0.0 实机多路性能基准待在 [#52](https://github.com/Starfie1d1272/cs2-headless-observer/issues/52) 补充。
