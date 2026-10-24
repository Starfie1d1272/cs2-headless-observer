# CS2 Headless Observer

Windows x64 的 GOTV 后台接收工具。使用普通 Steam 观众身份连接获授权的观战地址，输出逐行 JSON 比赛事件，可独立运行，也可由应用管理。

[Mizar](https://github.com/Starfie1d1272/Mizar) 使用本组件提供 Lookahead 来源数据。

## 快速开始

从 [Releases](https://github.com/Starfie1d1272/cs2-headless-observer/releases) 下载发行包：

| 包 | 适合的用法 |
| --- | --- |
| `windows-x64` | 独立运行，包内提供 Python、Node 和交互启动入口 |
| `windows-x64-external-node` | 应用集成，复用已有的 Node.js 24.0.0 或更高版本 |

独立包使用步骤：

1. 解压到可写目录，运行 `Replay.cmd` 完成本地自检。
2. 登录自己的 Steam 账号，准备 CS2 安装目录和获授权的 GOTV 地址、密码。需要同时使用游戏时，先启动游戏。
3. 运行 `Start.cmd`，按提示填写路径、来源 host 版本和连接信息。程序持续运行，Ctrl+C 请求停止。

Steam 会将观众的 App730 上下文显示为 CS2 运行状态。重启游戏前，先停止观察器并等待进程退出。

## 事件与应用集成

输出包括来源时钟、游戏事件和来源断点。下面是[合成自检输出](examples/managed-events.json)的字段节选；完整结构见 [JSON Schema](schemas/managed-event.schema.json)。

```jsonl
{"kind":"cursor","sequence":1,"world":1,"tick":100,"map":"de_test"}
{"kind":"round_freeze_end","sequence":2,"world":1,"committedTick":100,"players":{},"identityResolved":false}
```

应用按[托管接口](docs/managed-interface.md)启动子进程，通过私有 stdin 传入配置，持续读取 stdout，并以 stdin EOF 请求停止。[Python](examples/managed_consumer.py) 和 [Node](examples/managed_consumer.mjs) 示例展示了完整进程调用。

## 适用范围

当前在线验证环境为 Windows x64、CS2 build 10955 / host 14192。解析器依据来源 schema 处理实体和事件；身份有当前证据时输出 Steam64，其余保留为 null 或未解析状态。

同账号并行观战使用不同的 GOTV 端点；同一 IP:port 的后续连接可能替换已有连接，游戏客户端也占用该端点。每次换场或换图使用新授权地址与新来源实例。

事件时间属于来源时间线。实际领先量、节目时间对齐和展示由消费应用管理。完整条件与在线补验范围见[兼容性](docs/compatibility.md)，运行和故障处理见[使用说明](docs/usage.md)。

## 文档

- 使用与集成：[使用说明](docs/usage.md)、[托管接口](docs/managed-interface.md)、[组件分发](docs/component-distribution.md)
- 开发与维护：[构建](docs/build.md)、[验证](docs/verification.md)、[架构](docs/architecture.md)、[贡献指南](CONTRIBUTING.md)、[更新日志](CHANGELOG.md)
- 协议与证据：[协议契约](docs/protocol/README.md)、[研究知识库](research/README.md)、[历史归档](archive/README.md)

## 许可

项目自有代码采用 AGPL-3.0，并附[Steamworks SDK 链接例外](LICENSE-STEAMWORKS-EXCEPTION.txt)。对应源码与许可随发行包提供；第三方组件适用各自许可证，详见[第三方来源](THIRD_PARTY_NOTICES.md)。
