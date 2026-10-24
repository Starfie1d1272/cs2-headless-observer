# 组件分发

同一份运行代码生成两种 Windows x64 包：

| 包类型 | 运行方式 |
| --- | --- |
| `standalone` | 提供 Python、Node 与交互入口，运行 `Start.cmd`；`Replay.cmd` 执行合成自检 |
| `external-node` | 提供 Python、原生桥和 worker，由应用托管，使用调用方或 PATH 中的 Node |

最低外部运行要求为 Node.js 24.0.0，具备 WebAssembly、ReadableStream、structuredClone。启动检查版本与能力，制品验证执行实际 worker 自检。独立包固定内置运行时归档与摘要，以支持复现构建。

## 构建与验证

完成[源码构建](build.md)后，可组装外部 Node 包：

```powershell
python tools/package_windows.py --kind external-node --runtimes <python-runtime-directory> --native work/native/cs2_observer.dll --parser-bundle work/build/parser_worker.mjs --parser-source work/parser --output dist/observer-external-node --source-sha <40-character-source-commit>
python tools/verify_package.py dist/observer-external-node --node <node.exe> --report work/external-verification.json
```

`--kind` 默认选择 `standalone`。两种包保留 Python、项目及修改解析器源码、生成脚本、第三方材料和许可。SDK 头文件属于外部构建输入，Steam API DLL 由本机 CS2 提供。

## 文件与版本

```text
client/driver.py、cs2_observer.dll、parser_worker.mjs
runtime/python/
runtime/node.exe                    standalone
examples/、schemas/、tools/replay_example.py
docs/、licenses/、source/
manifest.json
```

manifest 记录组件版本、源码提交、平台、原生 ABI、有序 IPC、托管 JSON 契约、已验证 host、Node 要求与文件摘要。`validatedHostVersions` 表达验证范围，实际兼容性由来源协议能力决定。

托管应用将输出目录安排在安装目录之外；独立交互入口默认写入包内 `runs/`，因此使用可写解压目录。Python 启动时保持源码文件状态，包验证在执行后再次核对文件与摘要。

## 应用安装与升级

应用可随安装包分发 `external-node`，复用已有 Node。按来源、归档摘要、manifest 和运行时能力验证组件，再定位入口并执行合成自检。

独立更新采用新目录安装：验证来源与文件，运行本地自检，等待当前会话收尾，再切换版本并创建新来源 UUID。保留上一验证版本用于恢复。消费应用管理下载、互斥、切换、回滚和用户提示。

本体以子进程接口提供观战数据，应用侧更新服务按自身发布渠道组织。CS2 编码、初始化或身份语义变化时，适配对应层并补充验证记录。
