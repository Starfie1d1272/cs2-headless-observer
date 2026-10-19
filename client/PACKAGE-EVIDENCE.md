# ABI 2 测试包构建记录

2026-10-19，Asia/Shanghai。

## 交付身份

- 源提交：`c4221f2eb3fa65bf3d9eb59a602bd30af1a1dd39`，包含普通观众 auth=2 / auth=3 分支。
- 包：`client-abi2.zip`，49,283,283 字节。
- SHA-256：`17621a7249b3369349a158ca0f6203cb7adeccacbcb0f98a636c4254b8dd50a1`。
- 包内 `manifest.json` 记录源提交、运行时来源摘要与逐文件 SHA-256。
- 通过私有对话交付六个不超过 8 MiB 的分卷及 `Extract-GOTV.cmd`；脚本拼接、校验上述完整包摘要后解压，由使用者手动运行 `Start.cmd`。

## 构建与检查

在 Linux 云环境使用 Debian 官方 MinGW GCC 14 交叉编译 Windows x64 SDK 桥，静态链接编译器运行库。PE 导入仅有 `steam_api64.dll`、`KERNEL32.dll`、`msvcrt.dll`，ABI 2 导出已核对。Steam API 使用用户本机正式 CS2 安装文件。

Python 3.14.8 embeddable 与 Node 24.22.0 Windows 运行时来自官方发行包，下载摘要已核对。解析器使用固定 `cs2parser` 提交 `deced963b86d3ec26b28a225824130fdf9fe3167`，应用仓库补丁后构建；第三方许可证和对应源码随包保留。

相关离线检查：30 项 Python 检查、10 项原生生命周期检查、7 项事件检查、解析器类型检查及实际二进制实体消息检查通过。打包 manifest 的文件摘要已逐项验证。此次未触发私有 GitHub Actions。

## 待实测

Windows 原生启动、Steam 登录环境及完美普通观众持续收流和事件输出尚待实测，manifest 中 `windowsRuntimeVerified` 与 `onlineVerified` 均为 `false`。Linux Wine 尝试在 Python 启动前退出，未构成 Windows 启动证据。

后续提交 `ac600b6fd0a8a2dd8a979b62e29f971a3d6d429c` 修正仓库冻结安装配置；上述测试包的源身份仍为包内记载的 `c4221f2`。
