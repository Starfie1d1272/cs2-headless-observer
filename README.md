# CS2 Headless Observer

以普通 Steam 观众身份连接获授权的 GOTV 源，在后台接收比赛数据，输出逐行 JSON 事件。运行时不启动游戏画面；Steam 认证及可靠传输使用本机官方接口。

这是独立的 Windows x64 接收程序。可以交互运行，也可以由任意应用以子进程方式管理。当前版本为1.0.0。

本组件为 [Mizar](https://github.com/Starfie1d1272/Mizar) 的 Lookahead 功能提供底层观战数据。

## 使用

Windows 便携包解压到可写目录后：

- `Start.cmd`：交互连接，需要本机 Steam 登录、CS2 安装和有效观战授权。
- `Replay.cmd`：运行包内完全合成的离线样例，无需 Steam、CS2 或网络。
- 应用集成：按[托管接口](docs/managed-interface.md)启动 `client/driver.py --managed`，通过 stdin 传入配置，从 stdout 消费 JSON。

external-node包使用调用方提供或PATH中的Node.js 24.0.0及以上版本，不绑定Node小版本。便携包的实际验证范围由制品 manifest 及验证报告说明。源码使用者见[构建步骤](docs/build.md)。

## 支持范围

原生桥 ABI 3、有序解析 IPC 3；显式支持 host 14191、14192。真实普通观众接入已在 CS2 build 10955 / host 14192 验证。其他 build 和来源需要单独验证。

身份缺失保留未知；控制器 Steam 身份与可选 pawn 证明分别输出。事件接收时间不是画面时间。换图使用新 GOTV 地址和新来源实例。项目不承诺固定提前量，也不提供渲染或完整游戏模拟。

同一 Steam 账号重复连接同一 GOTV IP、端口，本次实测出现已有连接被替换；不同端点可以并行。与游戏客户端共用同一观战端点时，不应依赖额外观众连接稳定共存。

完整限制见[兼容性](docs/compatibility.md)，启动、停止及报告含义见[使用说明](docs/usage.md)。

## 开发与维护

- [构建](docs/build.md)、[验证](docs/verification.md)、[贡献说明](CONTRIBUTING.md)
- [架构](docs/architecture.md)、[托管接口](docs/managed-interface.md)、[协议契约](docs/protocol/README.md)
- [通用外部Node组件与独立研究包](docs/component-distribution.md)：共享运行时、随包安装及独立更新方案
- [研究知识库与证据](research/README.md)、[历史归档](archive/README.md)
- [第三方来源](THIRD_PARTY_NOTICES.md)、[许可证](LICENSE)

真实比赛捕获、玩家资料、认证信息和游戏二进制不作为公开示例。仓库样例由合成字节生成。

## 许可

项目自有代码采用 AGPL-3.0，并附[限定的 Steamworks SDK 链接例外](LICENSE-STEAMWORKS-EXCEPTION.txt)，允许与 Steamworks SDK、Steam API 库链接及分发组合产物；项目代码及对应源码的其他 AGPL 义务继续适用。第三方组件各自遵循原许可证，例外不替 Valve 授权，详见[第三方来源](THIRD_PARTY_NOTICES.md)。
