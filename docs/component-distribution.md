# 通用分发包与组件

同一份运行代码生成两个Windows x64产物：

| 包 | 使用方式 |
| --- | --- |
| standalone | 自带Python、Node和交互入口，解压运行Start.cmd；Replay.cmd执行完全合成的离线自检 |
| external-node | 自带Python、原生桥和worker，由任意应用托管；调用方提供Node，或使用PATH |

最低外部运行要求为Node.js 24.0.0；不绑定小版本、安装来源或二进制哈希。启动前检查版本和必要能力；包验证还执行实际worker的离线自检。当前验证过的运行时写入验证报告，测试清单不作为允许列表。未来版本仍需满足接口和能力要求。

独立包为重现构建固定其内置Node归档与摘要，这不会限制external-node使用者。Python保持完整嵌入式运行时，源码、修改解析器和许可随两个包保留。

## 构建

从[固定干净上游](build.md)构建后：

```powershell
python tools/package_windows.py --kind external-node --runtimes <python-runtime-directory> --native work/native/cs2_observer.dll --parser-bundle work/build/parser_worker.mjs --parser-source work/parser --output dist/observer-external-node --source-sha <HEAD>
python tools/verify_package.py dist/observer-external-node --node <node.exe> --report work/external-verification.json
```

external-node组装不需要安装Node，也不读取Node归档。验证可用--node选择运行时，省略时从PATH查找。
省略--kind生成独立包，此时需要固定Python和Node归档。两种包都使用client/cs2_observer.dll，运行接口见[托管协议](managed-interface.md)。

## 文件和版本

manifest.json包含包格式、发行版本、源码提交、平台、ABI3、内部IPC3、托管JSON契约1、已验证host、最低Node要求及全文件摘要。
源码、接口、CS2兼容与运行时版本独立表达。host版本接受非零uint32，清单validatedHostVersions记录实测范围；Node的小版本变化不直接要求观察器更新。
若解码编码、初始化或身份规则变化，按实际受影响部分适配并验证。收到动态schema不等于支持所有未来协议。

文件布局：

```text
client/driver.py、cs2_observer.dll、parser_worker.mjs
runtime/python/
runtime/node.exe             仅独立包携带
tools/replay_example.py
examples/synthetic-channel.json
docs/、licenses/、source/
manifest.json
```

输出目录应位于安装目录之外。启动不写字节码；包验证会在执行后再次核对文件和摘要。连接配置只经私有stdin传入，不进入包清单或启动参数。

## 消费者分发与升级

消费者可把external-node放进自己的安装包，复用已有Node。先验证组件来源、文件摘要、托管契约和当前Node能力，再根据清单定位文件。某应用为自身发行固定Node是该应用的策略，不属于本体要求。

独立更新应将来源认证、下载准备与激活分开：验证版本/归档，安装到新内容目录，运行无网络自检，等当前会话结束且旧进程清理后切换，再创建新来源UUID。保留上一验证版本用于恢复；旧版本也可能不兼容新的CS2。
本体不自带下载器、不绑定消费端更新服务，也不会在比赛中替换自身。消费应用负责授权发布链、互斥、回滚和用户提示；本地manifest本身不是下载授权。
