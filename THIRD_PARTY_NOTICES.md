# 第三方来源与分发材料

项目自有代码采用根目录的 AGPL-3.0，并附 [Steamworks SDK 链接例外](LICENSE-STEAMWORKS-EXCEPTION.txt)。迁自 Mizar 的代码保留来源，第三方组件适用各自许可证。

| 组件 | 固定来源 | 随包材料与使用方式 |
| --- | --- | --- |
| cs2parser | 2.7.2，`deced963b86d3ec26b28a225824130fdf9fe3167` | MPL-2.0；修改源码、补丁、LICENSE、ACKNOWLEDGEMENTS |
| @bufbuild/protobuf | `pnpm-lock.yaml` 的精确版本 | Apache-2.0、varint 内 BSD 通知及对应分发源码 |
| Node.js | Windows 24.22.0 归档与固定摘要 | 独立包提供原始 LICENSE 及第三方声明 |
| Python | Windows embeddable 3.14.8 归档与固定摘要 | 两类包提供原始 LICENSE.txt |
| Steamworks SDK 头文件 | ValveSoftware/Proton `bc896217ffcd67f892f952b010f898fe7bd0f0a1` 的 `steamworks_sdk_165` | 外部编译输入；归档协议见 [Steamworks-SDK.txt](licenses/Steamworks-SDK.txt) |
| Steam API | 使用者本机 CS2 安装 | 运行时从本机加载 |
| ICE 独立对照 | `verify_password.py` 指定的外部来源 | 可选测试输入，按该输入原始许可使用 |

`external-node` 使用调用方提供的 Node，其通知由运行时提供方保留。两个 Windows 包均提供项目、Python、解析器及其余实际分发组件的许可与对应源码材料。

Steamworks SDK 链接例外适用于项目权利人有权授权的代码；Valve 材料的使用和分发遵循 SDK 协议。SDK 头文件作为构建前提准备，账号、票据和游戏模块保存在使用者本机。

研究参考的版本和复用范围见[来源说明](research/references/REFERENCE-BASIS.md)。固定模块研究提供摘要和观察结果，公开示例采用合成输入。

发行材料按固定提交、构建输入和实际 bundle 核对，包含间接依赖的通知与重建资料。手动打包流程生成候选资产，正式 Release 使用版本化归档、摘要和验证记录。
