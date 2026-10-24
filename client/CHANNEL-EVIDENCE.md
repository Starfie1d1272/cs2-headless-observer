# 第三轮：GNS 内层通道格式

2026-10-24 运行时修正：下文固定构建历史记录中的“两层可靠性必须相等”推断不成立。
GNS 可将过大消息升级为可靠传输，tag2/4 的应用头仍按不可靠帧解析、过滤序号。
tag1/3 仍要求可靠传输。实际失败消息与回归结果见 [Windows 实测](LIVE-2026-10-24.md)。

本批 `channel.py` 只消费**已通过合法 GNS 接收、解密、重组的完整消息**，不会从 PCAP 解密、不会自己处理 Steam 证书、也没有自动发送 ACK 或 sign-on。当前证据支持以下格式实现；尚无真实普通观众互操作。

目标 networksystem SHA-256 仍为 `be7e13ad771b21c986e25d9469993a1225be5649473f3d722ca5eefe375d1bec`。查询、结果 hash 和限制见 [channel-evidence-index.json](evidence/channel-evidence-index.json)，配方见 [channel-queries.json](evidence/channel-queries.json)。地址不可用于其他文件版本。

## 已交叉核对的层次

| 证据点                        | 当前构建的观察                                                                                                                       | 实现和界限                                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `0x1800be6e0` Transmit        | 可靠消息的 SDK flags=8，不可靠 flags=1；最后调用 sockets `+0x60` SendMessages。message 内 flags 位于 `+0xc4`、connection 位于 `+0xc` | SDK 1.65 头文件和编译期 offsetof 同时核对这些布局。可靠重发/分片委托 GNS，不复制 Source 1 netchannel 算法 |
| `0x1800c2230` 接收            | 读取 VarInt32 类型 1/3 为可靠、2/4 为不可靠；3/4 解压调用 V_LZ4_decompress_safe                                                      | `decode_frame` 检查类型、实际 GNS reliability、头部边界及长度；没有使用 Demo 的 Snappy 外壳               |
| `0x1800e23d0` / `0x1800e28b0` | 写/读 UBitVar message ID；非短形式由 `0x1801bf5c0` 读取额外 4/8/28 bits；再用 VarInt32 长度和 protobuf bytes                         | `encode_message` / `messages` 实现非字节对齐序列；实际 schema 解码尚需接入数据状态                        |
| `0x1800c00b0` ParseMessages   | 循环在剩余不足 8 bits 时停止；对注册类型、类别、protobuf 和处理预算另有检查                                                          | 这里只切分原始 body，保留少于 8 bits 的尾部计数，不假定其值为 0；不冒充官方消息注册/类别验证              |
| `0x1800c10b0` ProcessMessages | 后续排队消息进入游戏侧处理与回调                                                                                                     | 切分成功不等于 ServerInfo、实体或事件已处理                                                               |

`0x1800fb100` 是另一个通用 buffer 解压入口。不能因为它引用其他压缩 helper，就把该通用路径误套到上面已确认调用 LZ4 的通道分支。

## 已实现的头部

这里的 tag 是内层 VarInt32，**不是外层 UDP/GNS 控制包的 32..37**。所有固定 uint16 为 little-endian。

| tag | 头部字段（之后是消息 bits 或压缩块）                                                   |
| --- | -------------------------------------------------------------------------------------- |
| 1   | tag、reliable tick hint（VarInt32）、消息 bits                                         |
| 3   | tag、reliable tick hint（VarInt32）、展开字节数（VarInt32）、LZ4 raw block             |
| 2   | tag、发送帧序号（VarInt32）、对端帧确认号（VarInt32）、3 个 uint16 历史字段、消息 bits |
| 4   | 与 2 相同的头部、展开字节数（VarInt32）、LZ4 raw block                                 |

可靠分支的第一个数传入 ParseMessages 的 tick 上下文；本实现谨慎命名为 `reliable_tick_hint`，不把它升级为已解码事件 tick 或画面时间。它**不是 GNS 的可靠字节流 ACK**。不可靠分支读入序号/确认号后分别写入 channel `+0x8dac/+0x8db0`；发送端从对应字段填头。3 个历史字段参与发送统计，现只保留原始整数，不构建调度或对时算法。

`UnreliableOrder` 只过滤重复/倒序并报告间隙。符号位边界、序号回绕、建连初始值尚未恢复，所以超出非负 int32 范围直接拒绝，并要求重建实例；不能用它自动生成合法客户端 ACK。可靠分支的顺序、重传、碎片与 SNP ACK 由合法 GNS API 承担，其公开 [SNP 格式](https://github.com/ValveSoftware/GameNetworkingSockets/blob/d534c19aa760df3fb75fd20db13ba1932b8a5463/src/steamnetworkingsockets/clientlib/SNP_WIRE_FORMAT.md) 将 message segmentation、stream position 和 ACK 分层描述。开源说明不等于已取得 Steam 运行时接入权限。

纯 Python LZ4 解码按官方 [Block Format](https://github.com/lz4/lz4/blob/70ed016500d1e098d334766b4097529308ec9781/doc/lz4_Block_format.md) 实现有界 literal/match 拷贝，不支持字典或 LZ4 Frame。严格核对完整展开长度、offset 和末尾约束；通道层拒绝展开长度 0（当前接收路径拒绝解压返回值 <=0）。4 MiB 是本研究资源预算，不宣称是目标源上限；超出即报告不支持，不能静默截断。

## 独立验证与可复现命令

18 项 Python 测试包含 UBitVar 四种宽度的字面量向量、非字节对齐的连续消息、头部截断、可靠标记不符、乱序/重复和恶意 LZ4 边界。[原始输出](evidence/channel-tests.txt)。

```bash
python -m unittest discover -s apps/companion/research/ordinary-gotv -p 'test_*.py' -v
python apps/companion/research/ordinary-gotv/verify_channel.py \
  --output /private/new-channel-oracle.json
```

第二条命令只使用本机 liblz4 oracle 和内部生成的合成字节，不连接服务器。云端 liblz4 1.10.0 的 256 组压缩输出被纯 Python 解码器全部还原；其中 169 组确实小于输入。255 组非空样本另验证 tag 3/4，共 510 次头部+压缩解码；空块仅验证 LZ4 原语，不伪造为合法游戏通道帧。[实际报告](evidence/channel-oracle.json)。没有将任何合成结果标记为持续收数。

## 初始化仍缺什么

沿上一轮 engine2 的 `0x180061460` / `0x18005ff20` 已确认：NEW 阶段要完成字符串表回调安装、取得真实 send_table_crc/server_count/自身 account ID，发送 ClientInfo 后才应答 NEW；ServerInfo `0x18006a280` → `0x180084810` 还消费 session manifest、编码配置和世界尺度。SPAWN 应答存在延后分支。

现在已能表示/切分这些消息的封装，但**没有完成 serializer/class 信息、字符串表更新、实例基线、地图/manifest 依赖及应答完成条件**。Demo parser 的初始化依赖其自己的文件状态，不能给它塞一个 live protobuf 就宣称完成。`SignonSequence` 的初始化门禁保持关闭，不发送假的地图已就绪或跳过 NEW/SPAWN。

| 状态                                    | 项目                                                                                                               |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 已有实现，待真实互操作                  | password 已知 bytes 子集、challenge/connect 内层、UBitVar 消息、tag 1..4/LZ4；SDK 桥接已编译，生命周期经过合成测试 |
| 仍缺静态证据/实现，不能归咎于用户未测试 | 初始/回绕序号与发送调度、完整初始化依赖及 CRC 来源、资源与实体状态、SDK 桥与 Python 协议组件的连接                 |
| 真正外部运行条件                        | 合法 App 730 用户 SDK/证书上下文、当前授权的测试源、其实际普通观众流量/可诊断出口；本轮云端均没有                  |

本批已经实现不依赖上述外部条件的格式与生命周期部分。后续集成必须先保留这些门禁，再接真实上下文验证；完整无画面客户端和连续比赛事件仍未完成。没有重试 relay 密码、改认证标记、注入游戏或越过源端延迟。
