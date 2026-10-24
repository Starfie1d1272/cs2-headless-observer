# 应用托管接口

观察器以独立子进程接入，适用于任何能管理本机子进程的应用。集成无需把解析器嵌入应用，也没有 HTTP 服务或端口发现要求。

## 启动

从本地已安装便携包获取路径，启动包内 runtime/python/python.exe，参数为：

```text
client/driver.py --managed
  --native <absolute-client/cs2_observer.dll>
  --steam-api <absolute-CS2/game/bin/win64/steam_api64.dll>
  --node <absolute-runtime/node.exe>
  --parser-worker <absolute-client/parser_worker.mjs>
  --source-role ahead --source-id <new-UUID>
  --host-version 14192 --output <new-local-directory>
```

使用绝对路径、shell=false、Windows 隐藏子窗口；进程环境选择 SteamAppId=730，Steam 仍验证真实合法账号上下文。
source-role 为 ahead 或 delayed，source-id 为 UUID；每个新连接尝试使用新身份和新输出目录。

启动后向 stdin 写一行 UTF-8 JSON，精确包含 endpoint、password 两个字段，末尾换行。地址是数字 IP:port，可用方括号包 IPv6。配置行至多 4096 字节。不要把连接配置放进 argv、日志或版本控制。

写完该行后保持 stdin 开放；EOF 是停止信号，额外输入也会请求停止。不要用 write-and-close 的一次性管道来维持长时间观战。

## 输出

stdout 只有逐行 JSON 事件，不含最终报告；单行 UTF-8 字节数连同 LF 上限 64 KiB。sequence 是每次进程运行从 1 递增的公共记录序号，换世界不重置，不等同内部消息序号。stderr 可含原生日志及最终报告，不能直接转发到公共日志或当作纯 JSON 流。report.json 位于指定输出目录。
托管模式不落盘 events.jsonl 或 channel.frames。消费者必须持续读取 stdout，处理 EOF、非法记录、来源代际和有界缓存。

按 kind 区分 cursor、实际游戏事件和 discontinuity。保留 source/channel/world、eventServerTick、committedTick、players、pawns 与 identityResolved 的原始含义。
row.tick 在部分原始事件中可能为 0；不要据此覆盖非零 eventServerTick。消费归一化需由适配器显式选择和验证。

仅完整快照回执和有效来源检查建立就绪；discontinuity、EOF、错误或来源替换立即撤销旧提示。未知选手保持未知。字段结构见 [JSON Schema](../schemas/managed-event.schema.json)，可运行消费者见 [Python 示例](../examples/managed_consumer.py) 和 [Node 示例](../examples/managed_consumer.mjs)，[合成输出](../examples/managed-events.json) 不含比赛数据。

| 字段或记录 | 含义 |
| --- | --- |
| source / channel / world | 连接尝试身份、通道和世界代际；共同确定记录所属的连续段。新连接使用新 source，世界断点撤销旧证明。 |
| sequence | 本进程公共记录顺序，从1连续递增，跨 world 不重置；不是游戏 tick 或内部解析消息序号。 |
| kind=cursor | 已提交实体快照的时间依据；tick 为正整数，tickInterval 为每 tick 的秒数，map 是来源地图名。它不提供 Program 画面时间。 |
| type=raw-event | kind/name 为游戏事件名，fields 保留事件原始字段。fields 中 type9 玩家值是控制器槽位，不能直接当作 userinfo userid。 |
| tick / networkTick | tick 是该消息的帧上下文，可能为0；networkTick 是最近处理的网络 Tick 控制值。它们都不是墙钟或接收时间。 |
| eventServerTick / committedTick | 前者来自事件消息的 server_tick，后者是事件处理时最后提交的实体快照 tick；两者可能不同。null或非正时间值不能用于时间映射，不补成当前时间。 |
| players | 按 userid/attacker 等原始字段键提供当前控制器与 userinfo 一致性证明；slot 为零基槽位，steamId 为十进制字符串，userId 为实际 userinfo ID或null，controller 含 index/serial。未知项为null。 |
| pawns | 可选、独立的实体 index/serial 证明；控制器身份成立不等于 pawn 成立。不能以旧世界或截短 serial 补齐。 |
| actor / target / identityResolved | 事件投影得到的 Steam64 或null；布尔值说明该事件要求的身份是否解析，不表示整个来源或所有 pawn 都有效。 |
| descriptorGeneration | 当前事件目录代际；目录变化后不能沿用旧字段解释。 |
| kind=discontinuity | reason 描述失效原因；立即撤销所属来源的就绪、身份和提示，等待匹配当前代际的新有效 cursor。 |

消费者忽略新增未知字段和未知记录种类；未知记录不能建立就绪、身份或时间映射。已知字段结构错误、记录超预算或截断应停止该来源的可信交付，不截断 JSON 后继续使用。

## 停止与重试

默认持续运行；--seconds 只用于显式限定诊断时长，没有四小时上限。先停止事件交付、关闭 stdin，等待旧进程释放 SDK 句柄及解析器退出；建议给予至少 12 秒清理宽限，仅在超时后终止本应用拥有的子进程。Windows 上驱动持有 kill-on-close Job，驱动被强制结束时回收其解析器。应用仍须确保自己异常退出时驱动也被回收，例如使用应用拥有的 Windows Job；仅依靠主动发送停止并不覆盖宿主崩溃。stdout 堵塞由有界队列报 output-backpressure，管道关闭报 output-closed；停止不等待消费者恢复读取。正常 1038 会先排空已接收通道和解析输出，再发布断点并关闭。退出码含义见[使用说明](usage.md)。
观察器单次运行不重连。消费者决定哪些失败可重试；不能对正常 1038、明确拒绝或清理失败无限循环。

同一消费者应避免对同一账号、同一端点创建重复连接；与游戏客户端共用端点时也需要考虑已有连接被替换。1000 是通用关闭码，不能单凭该数字判定账号冲突；重复连接替换时盲目重连可能互相挤占。具体实测边界见[兼容性](compatibility.md)。

## 运行要求与契约

Windows x64；Node.js 24.0.0 或更高，具备 WebAssembly、ReadableStream 和 structuredClone。独立包自带运行时；external-node 包接受 --node，省略时使用 PATH。不要求任何特定消费应用，不核对外部 Node 的小版本或文件哈希。

托管 JSON 契约标识为 cs2-observer-managed-json/1，由包清单声明，不新增 stdout 头记录。内部有序 IPC3 与它是不同版本轴。1.x 保持已公开字段的含义、未知值、来源代际、EOF停止和退出语义；消费者应忽略新增未知字段，以便兼容扩展。实际支持事件受源覆盖限制。

`kind` 为事件分派键。cursor 发布已提交tick；discontinuity撤销该来源就绪；游戏事件保留原始fields与eventServerTick。Steam64使用字符串，未知身份为空或未解析，players证明与pawns证明独立。所有事件均按输出顺序消费；退出/断点后不沿用旧来源证明。

包清单给出python、driver、native和worker相对路径。消费者提供合法Steam上下文、授权连接、输出目录和生命周期。
