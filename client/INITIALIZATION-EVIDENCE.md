# 普通观众初始化对照

2026-10-18，固定官方 engine2.dll SHA-256 `6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21`。从 Valve 匿名内容下载取得同一 depot/manifest；本轮使用 Ghidra 12.1.4 批处理直接分析并保存项目。地址与结果摘要见 [索引](evidence/initialization-static-index.json)，原始反编译文本仅留研究环境。

## CONNECTED 必须先应答

`0x18007edd0`（CNetworkGameClientBase::Connect）建立通道后调用 SetSignonState，参数为 CONNECTED=2、spawn count=`0xffffffff`。`0x180060310` 排队发送相应 CNETMsg_SignonState。服务器 `0x1800c4a30` 在 CONNECTED 应答后才发送 ServerInfo 和初始 spawn groups。

因此等待 ServerInfo 后才允许首次 CONNECTED 应答会形成循环等待。驱动现已在连接响应后、ServerInfo 尚未到达时发送该 CONNECTED 应答；未知 spawn count 仅在这一阶段使用 `0xffffffff`，其后仍核对 ServerInfo 的真实 server_count。

可靠通道使用 tag 1、初始 tick 上下文零及 GNS flags=8。networksystem 构造路径 `0x1800bba50` 在 `0x1800bbf4b` 将 `+0x8dbc/+0x8dc0` 同时清零；`0x1800be510` 在发送前复制上下文，`0x1800be6e0` 写入可靠帧并设置 SDK flags=8。驱动测试核对在 ServerInfo 为空时已发送准确的 CONNECTED/-1 消息，NEW 的后续实现见本文末节。

## 零 CRC 的完整表路径

`0x18005ff20` 取得本地/缓存 send-table CRC，缺少可用缓存时保留零，并发送当前 server_count、普通客户端角色及 Steam account id。`0x1800c9390` 将 ClientInfo 的 CRC 保存至连接对象。

`0x180120fa0` 只有在 CRC 非零且与本地匹配时才走复用路径；CRC 为零进入完整 send-table 发送分支，再调用 `0x1800c5fb0` 发送 sign-on 数据并推进 PRESPAWN。零值在此表示请求完整表，而不是伪造已有缓存。ClientInfo 编码默认使用零；非零值仅适用于已有匹配缓存。

## 后续顺序

`0x180061460` 在 NEW 阶段安装并调用已有字符串表回调，发送 ClientInfo，再发送 NEW 应答。服务器收到该应答后才提供下一阶段的表/sign-on 数据。初始化应按各阶段实际输入推进，完整实体快照不能无条件作为首次 CONNECTED 应答的前提。

本轮修改复用既有握手与 LiveDecoder 边界测试，27 项通过。后续表/实体处理已在下述解析进程接入；普通观众在线连接仍待实测。

## SpawnGroup manifest 与当前 Windows 构建

同一官方 engine2 的 `0x180082da0` 处理 Load、`0x180083690` 处理 ManifestUpdate；manifest 经 `0x1803f7d40` 解出资源名。外壳为 1 bit 压缩标志、24 bit 字节长度；压缩内容使用 LZSS。内层先保存三个 uint16 计数及扩展名/目录字典，随后按目录索引、名称和扩展名索引组成资源项。`resource_manifest.py` 独立实现有界格式读取；资源名仅保存在内存，不作为文件路径执行。

既有公开 Demo 的 8 个实际 SpawnGroup 包解出 47 项资源名，覆盖压缩、未压缩及空资源列表；[记录](evidence/resource-manifest-offline.json) 包含输入摘要和数量。LiveDecoder 保存各组及后续 manifest 片段。事件接收器按后述逻辑世界注册生成加载完成消息；它不创建图形场景。

当前 SDK 桥已使用固定 Valve Proton SDK 1.65 头文件、官方 CS2 `steam_api64.dll` 的导入符号和 LLVM MinGW 交叉编译为 Windows x64 DLL，13 个当前 C ABI 导出均存在，包括启动失败码。[构建记录](evidence/windows-native-build.json) 包含工具、大小和 SHA-256；Windows 原生启动与在线持续接收尚待执行。

## 普通客户端 NEW 请求全表

驱动现从 SDK 认证结果前缀读取自身 Steam account ID，在已收到 ServerInfo 的 NEW 路径，依次发送 ClientInfo（消息 20、CRC 0、普通客户端角色）及 NEW 应答（消息 7）。这对应 `0x18005ff20` / `0x180061460` 的请求完整表顺序。已有字符串表需等待解析进程消费对应包的回调检查点，再进入下一阶段。

复用了驱动链路测试，检查实际发送顺序、真实 SDK 身份低 32 位映射、零 CRC、服务器计数及 PRESPAWN 不重复 NEW；27 项测试通过。此次未连接服务器。

## 本地解析进程与无画面世界初始化

`parser_bridge.py` 通过有界管道连接 `parser_worker.mjs` 和既有实体解析器。每包追加本地 Demo CustomData 检查点；该标记仅用于进程间同步，不发送至服务器。检查点由解析器处理完此前输入后发出，报告实际 schema 字段数、字符串表数和 ServerInfo 状态。最多四包未确认输入，积压时暂停从 SDK 队列取包，继续泵回调与消费解析输出。

PRESPAWN 应答需要真实 schema、ClassInfo 和已完成检查点。`0x1800c5a00` / `0x1800c4a30` 的服务器顺序表明：PRESPAWN 应答后推进 SPAWN，SPAWN 应答后才激活客户端。驱动因此先完成事件解析所需的世界身份注册，再应答 SPAWN。世界组按 owner/parent 依赖顺序登记，等待 manifest 片段完整，处理创建 tick 与卸载，然后发送消息 13（LoadCompleted）；保存游戏世界仍需额外状态源。

这里的世界注册服务于事件解码，不加载或渲染地图美术资源。是否充分覆盖完美在线源，需要实际持续流验证。记录中的逻辑状态 FULL 与在线成功分别报告。

固定公开录像通过实际 Node 子进程消费 185932 包、185932 个顺序检查点，最终 22889 个 schema 字段及 2 个字符串表，事件计数与前次一致。独立驱动验证使用该录像真实 schema、8 个世界组及合成 sign-on，依次发出 CONNECTED、ClientInfo、NEW、PRESPAWN、8 个 LoadCompleted、SPAWN、FULL；网络端口为合成输入。这次联调还发现并修正 schema 字符串池合法空占位被拒绝的问题。

后续集中验证实际普通观众接入与服务器互操作。原始游戏二进制及反编译正文保留在研究环境；提交仅包含实现和证据摘要。

## 解析完成后的 tick 回执

`0x1800642d0` 的客户端发送路径取字段 `+0x24c`；`0x1800800e0` 日志称其为 `last_tick_recv`。该字段完整更新条件还在核对。原型选择在真实解析进程确认包含实体包的检查点后，按最多 10 Hz 发消息 4 的 tick 回执，并记录最后处理/确认的 tick。当前选择可靠 GNS 消息承载该回执；此调度是原型实现选择，仍需源端互操作验证。

固定录像的首次实体输入经真实解析子进程后，驱动发出 tick 1380 回执；同一轮有 22889 个 schema 字段、2 个字符串表与 8 个世界组。网络状态为合成输入。后续对照确认固定录像的 185922 个实体包全部使用基线 0，且没有 update_baseline；这份录像本身没有覆盖实例基线切换。

## 双基线、PVS 与全量恢复

固定官方模块的 `0x180044f10` 在实体进入时选择同类实体基线，缺失时读取类基线；`0x180088740` / `0x180097700` 复制两组基线，`0x180088620` 合并进入实体的数据到另一组。备用类基线覆盖在既有实体更新前应用。`0x18008b110` 和 `0x1800775b0` 读取非传输实体的递增索引及单比特状态；`0x180077630` 区分 PVS 外实体创建与更新。

研究补丁只为普通观众模式启用这些路径。历史保存有界的传输/非传输位图，实体基线保存两组独立属性副本；普通录像解析路径保持原样。源码与补丁随研究包提供，生产 npm 依赖不变。

`0x18007f1e0` 请求完整更新时清空实体基线并把最后确认 tick 设为 -1；`0x18006a960` 在完整状态恢复前忽略增量。研究驱动按此发送消息 4 的 0xffffffff，请求期间暂停依赖实体状态的事件输出。消息 23 的 tick/基线组号只来自成功处理的实体回执，且等待对应本地检查点。

新版解析路径通过同一完整录像的 185932 个包、185922 个实体回执，事件数量与原路径一致。额外合成二进制覆盖基线保存、删除后重入、备用类基线、非传输状态、PVS 外创建/更新，以及缺少引用帧后的恢复。真实录像 schema 与合成网络端口的集成验证发送一次完整更新请求，收到合成完整状态后确认 tick 1382，并发送一次基线回执；见 `evidence/online-world-recovery.json`。这些结果覆盖云端实现，尚未连接完美在线源。

完整帧分片由 `0x18004ca50` 按 tick 和连续 section 组装，`0x180137a50` 序列化 PacketEntities 后压缩；压缩上界 `32+n+n/6` 及解压入口 `0x1804091f0` 对应 raw Snappy。RTTI 确认解码对象为 `CSVCMsg_PacketEntities`。研究路径处理消息 70，校验顺序、长度和 tick 后才交给实体解析；已落后的背景快照跳过。三片真实 Snappy 数据、缺片和 tick 错配有合成覆盖；完整驱动验证仅在第三片完成后发送恢复回执，见 `evidence/online-split-recovery.json`。

新版完整录像的事件语义摘要为 `ed3a9bb727159935b770f93aa9f143d873c0c97193ae45fcfbf5da70f324fdb4`，与原参考一致，覆盖事件顺序、武器、玩家/攻击者 Steam64、热身和回合状态；不仅比较事件数量。

NEW 前的字符串表检查现在计入全部已处理创建回调，包括事件解析器不消费数据的资源表。此前检查点只计两张相关表，与接收端统计所有表的口径不一致。增加 NEW 前的未使用表并清理后继续真实 schema 的集成验证通过；初始化快照共处理十二张表，见 `evidence/online-table-callback.json`。

`pending_full_frame` 占位通知与已解码实体状态分开记录。占位到来时等待对应完整快照，既不把空占位当作实体完成回执，也不重复请求服务端已在发送的快照；过早的旧快照忽略。合成占位加三片真实 Snappy 的驱动验证中，全量请求为零，第三片后才确认 tick 1382，见 `evidence/online-pending-frame.json`。

完整快照分片期间收到的增量暂存于有界队列，按原顺序在快照完成后应用，并保留各包对应的基线。合成网络集成覆盖占位 1382、提前到达的增量 1383、三片快照及后续增量 1384；最终确认 1384，全量请求零次、基线回执一次，见 `evidence/online-buffered-frame.json`。最新完整录像重放耗时 136.996 秒，解析子进程峰值 RSS 335360 KiB，事件语义摘要与参考一致；该内存数据是本次云端重放观测值。



## 连续恢复请求与 Tick 回执节流（2026-10-19）

驱动原先复用最后发送的 Tick 值 `0xffffffff` 判断完整更新请求是否尚未完成。若完整快照已被解析确认，但正常 Tick 回执尚处于 100 ms 节流窗口，此时又出现新的缺帧，旧值会抑制新的完整更新请求。

已将“完整更新请求待响应”独立为驱动标志：收到解析器有效实体回执即清除；同一次恢复等待期间仍只请求一次，正常 Tick 回执仍遵守原节流。最后发送的 Tick 记录保持真实发送值。

扩展既有驱动测试，以 810/820/830 ms 的缺帧、恢复确认、再次缺帧重现：修改前请求累计数为 2，独立预期为 3；修改后通过，后续重复轮询不重复请求。全部 28 项 Python 验证通过，包括真实 ctypes/C ABI 与无网络的合成端口。此项验证驱动恢复逻辑，未连接完美线上服务器。


## 首个完整实体快照推进 FULL（2026-10-19）

在相同 engine2.dll 摘要下，`0x18006a960` 完成实体解码后调用 `0x180086220`。后者在客户端处于 SPAWN=5 且实体包不是 delta 时调用 SetSignonState(6)，随后更新 last_tick_recv（+0x24c）。因此普通观众不能只等待远端额外发送 FULL；也不能仅凭远端 FULL 就声明本地实体初始化完成。

驱动现在消费解析器检查点确认的 full 快照回执，再推进本地 FULL 并发送应答。远端状态与本地有效状态在报告中分别记录；远端随后发送相同 FULL 不重复应答。解析器内部协议升级为 2，明确携带 full 布尔值，旧工作进程会被版本检查拒绝。

新增独立预期回归在修改前重现“已解析完整快照仍未发 FULL”，修改后全部 32 项 Python 测试通过；真实二进制实体基线/PVS/分片验证与 7 项事件测试通过。固定公开 Demo 的前 11 个包经过实际 Node 解析子进程，获得 22889 个 schema 字段、12 张字符串表及 tick 1380 的首个 full 回执；合成 SPAWN 状态在没有远端 FULL 消息时推进至 6。结果见 `evidence/first-full-snapshot.json`。

重现：构建协议 2 的 parser_worker 后，执行 `python client/verify_first_full.py --fixture <固定demo.dem> --worker <parser_worker.mjs> --output <新结果文件>`。该验证使用真实录像实体数据与合成初始化状态，不进行网络连接；Windows 及完美在线互操作仍由真实测试源验收。原始反编译正文仅保留在私有研究环境。
