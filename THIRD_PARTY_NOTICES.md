# 第三方来源与分发清单

本仓库根 LICENSE 保留 AGPL-3.0 文本；迁自 Mizar 的代码保留原来源。项目自有代码附[Steamworks SDK 链接例外](LICENSE-STEAMWORKS-EXCEPTION.txt)，第三方代码不因该例外更换许可。下表追踪构建和分发资产。

| 组件 | 固定来源 | 使用与保留材料 |
| --- | --- | --- |
| cs2parser | 2.7.2；deced963b86d3ec26b28a225824130fdf9fe3167 | MPL-2.0；修改补丁、修改后的源码、LICENSE、ACKNOWLEDGEMENTS |
| @bufbuild/protobuf | pnpm-lock.yaml 的精确版本 | Apache-2.0 声明；varint 文件内 BSD 通知；随包保留相关源码和通知 |
| Node.js | Windows 24.22.0 ZIP及脚本固定摘要 | 随运行时提供原始 LICENSE，含其第三方声明 |
| Python | Windows embeddable 3.14.8 ZIP及脚本固定摘要 | 随运行时提供原始 LICENSE.txt |
| Steamworks SDK 头文件 | ValveSoftware/Proton bc896217ffcd67f892f952b010f898fe7bd0f0a1 / steamworks_sdk_165 | 仅作编译输入；固定归档中的完整许可保留于 licenses/Steamworks-SDK.txt |
| Steam API | 用户本机 CS2 安装 | 不随本包复制，不分发账号、票据或游戏 DLL |
| ICE 独立对照 | verify_password.py 指定的外部源码 | 仅可选合成测试；不进入运行包，使用前核对该输入的原始许可 |

其他研究参考在 research/references/REFERENCE-BASIS.md 中固定；参考阅读与直接复制实现分开核对。研究中的 Valve 模块仅保留摘要和观察结果，不附原始模块或完整反编译正文。

正式制品需核对运行文件、依赖通知、重建源码、构建参数与实际 bundle 一致，尤其是打入 bundle 的间接依赖。手动打包工作流不会自动公开仓库或创建 Release。

external-node不携带Node，调用方提供满足最低要求的运行时；其分发通知由运行时提供方保留。独立包附带固定Node与原始通知。两种包继续提供Python许可、修改解析器源码、补丁和依赖声明。

原生桥编译使用 Valve 保留权利的 SDK 头文件，包内不附 SDK 头文件或 Steam/CS2 DLL。[SDK 许可](licenses/Steamworks-SDK.txt)来自上述固定输入归档；其开发使用及可再分发部分受该协议约束。项目权利人已为有权授权的项目代码授予限定链接例外；这不授予 Valve 材料的权利，也不免除 SDK 协议义务。
