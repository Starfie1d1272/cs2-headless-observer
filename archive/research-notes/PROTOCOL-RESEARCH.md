# 普通 GOTV 观众：先研究、后统一实现

更新：2026-10-19。现有研究分支与本地 enum 修改冻结为验证原型；不继续逐点补代码、打包或发布。

## 交付目标

一个轻量普通观众客户端，使用合法 Steam 身份和源端观战密码连接获准 GOTV，持续输出可归属到玩家、回合和武器的事件。两个实例可独立读取不同延迟源。渲染、音频输出、玩家控制不属于目标；必须先证明这些子系统可以从网络状态与事件依赖中切开。

## 研究完成条件

1. 固定构建的所有入站消息经注册表定位到处理者；每个处理者归入必要状态、必要应答、可省略的显示、明确不支持的可选模式。不能以当前 Demo 没出现为省略依据。
2. 每一阶段列出进入条件、输入、状态写入、输出应答、失败出口；识别异步加载和跨消息依赖。初始化完成以必要网络状态完整为准。
3. schema/字符串表/实例基线/实体/游戏事件的依赖链闭合；关键虚函数调用定位到实际模块和实现。仅 engine2/networksystem 的结果不能替代 client.dll 的游戏层消费者。
4. 对丢失、重复、迟到、乱序、完整更新、回退、清表、换图和断线给出统一状态设计及旧状态隔离方法。任何恢复策略须区分官方行为与自行选择的有界简化。
5. 已知必须支持的分支没有未解释的解码/应答缺口。尚需现场验证的环境条件单独列出。静态结论不等于在线验收。
6. 完成以上工作后，统一实现一次，再做独立字节向量、真实录像回放、Windows 与获准实时源的分层验收。

## 全链路证据与待闭合项

|阶段|固定构建锚点|已有证据|研究尚需闭合|
|---|---|---|---|
|模块与接口|Valve depot2347771 manifest8766757721818354077|engine2/networksystem已固定摘要|补同manifest client.dll/schemasystem，定位游戏层接口与虚表|
|Steam/GNS|engine2 07e9a0、networksystem factory/setup|认证和SDK生命周期已有原型|官方连接配置、身份/加密条件、回调销毁顺序整体核对|
|challenge/connect|engine2 057370、003360|0.5s重发、challenge上下文、密码和ticket路径|全部拒绝/迟到/重排出口与相位截止统一图|
|通道封装|networksystem 0be510/0be6e0/0c2230/0c3780|tag、seq/ack、历史字段、压缩、方向mask|序号回绕、可靠/不可靠上下文交叉、分包/预算所有出口|
|消息分派|CNetworkGameClient虚表与protobuf绑定|部分处理者已定位|完整注册集合、每条消息是否应答、是否依赖client游戏层|
|CONNECTED/NEW|engine2 07edd0/060310/061460/05ff20/120fa0|CONNECTED先应答、零CRC完整表|异步表回调、缓存失效、服务器复用分支|
|世界/资源|engine2 082da0/083690/05c180/3f7d40|manifest结构与父组关系|实体资源加载实际依赖、删除/重载/失败/循环关系、无渲染替代是否充分|
|SPAWN/FULL|engine2 06a960/086220|有效full推进FULL|远端状态与本地状态全部排列及副作用|
|schema/字符串表|networksystem 0779c0；engine2 060ae0|schema与enum/codec线索，基线表入口|所有编码器表和容器、动态schema、userinfo/game层回调|
|实体状态|engine2 047960/088620/08b110/0775b0/077630|双基线、PVS、分片、缺帧|序列号重用、同tick包、全量回退、创建序号与世界关联|
|完整更新|engine2 04ca50/137a50/07f1e0|Snappy、分片、-1请求|分片代际切换、旧增量隔离、重复/过期与源端重发|
|时钟|engine2 069cd0/0800e0/086220/047960|时钟与实体确认独立；full回退清帧|回放状态切换、事件时间线标记、ACK与实体应用先后|
|事件|client游戏层，待定位|录像有击杀/武器/回合输出|在线订阅/ListenEvents、事件缓存、玩家实体/UserCommands依赖|
|断线/换图|待整理整体调用链|现原型终止旧实例|官方清理顺序、自动重连边界、新旧schema/事件隔离|
|双实例|SDK上下文与客户端对象|尚无实机证据|Steam会话共享、各实例连接/事件状态、资源成本|

## 新确认但尚不落地的时钟语义

- engine2 069cd0 在 net_Tick 回退时重置前一时钟并接受当前 tick，不据此自动清除所有实体。
- engine2 0800e0 更新到包频率统计，不构成实体重置依据。
- engine2 047960 对非增量快照回退调用 RemoveAllFrames；增量按 delta_from 查询已有帧，缺失时放弃处理。完整快照还重置双实体基线。
- engine2 086220 的 last_tick_recv 与 ProcessTick 时钟不同；HLTV回放状态影响低tick确认处理。需要与游戏层应用和网络消息上下文一起核实。
- 不能直接把原型的单调性异常改成放行；也不能未经区分在每次net_Tick回退时清空所有实体。恢复策略等完整调用链明确后统一决定。

## 原型验证边界

整数坐标修复已在私有分支cfe1d90；enum改动仅本地冻结。已有回放仍继续完成，结果只作为当前原型证据。Tick新用例确认现原型会拒绝低tick完整快照，尚未修改实现。原始模块与反编译正文仅保留研究环境，不上传仓库。

## 模块补齐与全量入口盘点（进行中）

从同一 Valve manifest 取得 client.dll（SHA256 659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0）与 schemasystem.dll（d2a9b5164cb68953e77d0ef424c1263d2cc452a75e935316bc8b4c4500e63648）。正在建立 client 静态分析项目，不执行游戏模块。

CNetworkGameClient RTTI 将主虚表定位为 engine2 0x180540bc8；0x2c0–0x410 共43个槽位已整体枚举。它们不是43个已完成的消息类型：包含stub、thunk和游戏层转发，仍需与注册绑定对应。此前按少数已遇到的消息选择处理者，无法覆盖完整入站集合。

新确认的分类依据：
- 0x350→089160：查询cvar后构造带cookie/name/status/value的响应并经通道发送。未知、命令名、受保护分别有状态1/2/3。属于协议应答路径，不能仅因为事件解析器不使用cvar而静默忽略。未来只响应真实持有的受支持值，不能伪造标准客户端配置。
- 0x2d8→0825e0：只查找已注册且标记FCVAR_REPLICATED的本地cvar，再解析网络值。需要区分会影响网络/游戏语义的配置与显示设置；不能直接将字符串作为任意本机命令执行。
- 0x328→082bb0：按行写控制台日志；目前未见协议应答或实体状态写入，可作为显示类候选，待注册类型核实。
- 0x360→060ec0：调用清表路径并清除四个已缓存表指针；属于状态变更。
- 0x408→060f00：更新HLTV replay状态与时间信息；状态切换时裁剪帧历史并通知游戏层。与Tick回退同一问题域，不能独立删除单调性检查后宣告恢复支持。
- 0x3d8→08b0d0：从消息写入服务器Steam身份；需核实与已认证远端的关系及是否允许变化。

这些是研究发现，尚未转为新增实现。

### 跨模块入口（待跟进消费者，不能据虚表名称即判等价）

client 的静态接口注册：0x1800cd380 注册 Source2Client002，factory0x180b854c0 返回对象0x18255f3e0；RTTI CSource2Client 主虚表0x181c630f0。GameClientExports001 factory0x180b854b0返回0x182230358。客户端游戏事件错误字符串的调用点落在0x1809aef13与0x1809f8b48；事件ID查找错误在0x180a1e513。

engine 调用游戏层所用的虚表槽位候选对应：0x60→client b75530（表回调），0x100→b702d0、0x108→b78c70、0x120→b6d700（实体处理阶段），0x520→b7a0d0、0x528→b7a0f0（HLTV回放），0x540→b70b10（引出另一接口）。仍需证明engine全局接口指针确实绑定该接口，之后才沿实现追踪。

engine 06a270 是转发到080480的thunk。080480把服务端StringCmd放入游戏自己的CCommandBuffer，并按受限标志执行。无头客户端没有游戏命令执行环境；设计时须从完整注册和实际发送方证明哪些命令影响必要网络状态，不能直接调用shell，也不能无证据地统一忽略。

engine 接口绑定进一步确认：静态接口对表0x1804da7e0保存字符串指针0x180588380（Source2Client002），紧邻目标指针为0x1806969d8，吻合上述游戏层调用所用全局。因此跨模块跟踪可从CSource2Client主虚表的对应槽位继续。

冻结原型的enum完整回放已完成：185932包、每侧185922实体回执、730.802秒，事件摘要与此前一致。仅归档验证结果，不继续实施Tick方案、不发布。

### 事件订阅必须从发送端与接收端一起闭合

协议定义同时有205（描述列表）、206（订阅位图）、207（事件内容）。CMsgSource1LegacyListenEvents包含playerslot和eventarraybits。client/server均存在相关注册类型；server还存在OnSource1LegacyGameEventListenBitsReceived的事件ID校验入口。

现原型驱动只发送初始化、基线、时钟/恢复等消息，未见206订阅发送。录像中包含事件，只能证明收到后的解码能力，无法证明在线源会把相同事件发给普通观众。下一步须沿服务器订阅位图处理、广播过滤和GOTV转发条件查清是否/何时需要订阅、如何随描述表变化更新，以及空位图和未订阅的真实行为。本项列为统一设计前必须闭合项；不立即补一个猜测的位图发送。

同manifest server.dll已取得，SHA256 09e8c04c5f44040155d04fa79a3f43491d542a386f45807ed77785729e5925a9。原始模块同样只在研究环境。

### 订阅机制已确认的两端事实

client 0x180a1eb50遍历注册的非local事件，挑选客户端监听类别1，按服务器分配的eventid设置16个uint32位图，附真实playerslot后交网络服务发送。未获服务器eventid的本地监听不置位，并给出unknown-by-server日志。

server 0x180c0b0f0校验playerslot范围0–63，先移除该槽位原有监听，再最多读取16个uint32位图；遍历0–511的置位项，找到描述后以监听类别2注册。缺失ID记录日志。server 0x180dcfb50在sign-on阶段写入事件描述列表。

接下来必须区分两个网络层：游戏服务器上的普通玩家连接，以及CHLTVClient所代表的GOTV观众连接。不能把game server的订阅要求直接套到GOTV转发端；需沿CHLTVClient::SendSnapshot和CHLTVServer广播路径验证事件集合、过滤条件与观众消息处理。当前没有据此新增206发送代码。

client 0x1809f8a90/0x1809aee70还显示游戏事件可按server_tick与本地播放时钟延后消费，再经CGameEventManager反序列化和分派。原型事件出口如何表达源时间、恢复代际和消费时间，将在统一设计中一并确定。

### 传输上下文与消息时间不能割裂

networksystem 0c3780在服务器发送方向mask bit1启用时，从net_Tick(4)或PacketEntities(55)取得正tick，填入可靠上下文；0c2230读取可靠帧的上下文后传入0c00b0。现驱动解出reliable_tick_hint，但交给ParserStream时只传body。这一层是否丢失必要的消息时间上下文需从0c00b0的元数据写入核实，不能只修复显式server_tick与外围Demo时钟不一致的断言。与engine047960的消息上下文校验一并研究。

传输上下文已追到networksystem 0c00b0：接收方向mask bit1启用时，可靠帧头提供初始tick；遍历消息，遇到正net_Tick或PacketEntities.server_tick即更新当前上下文，并写入每个消息对象+0x10。因此上下文是逐帧、逐消息演进的元数据。后续统一设计必须保留它及可靠性、顺序；把整个网络包统一套上最后一次net_Tick的Demo外壳会丢失这一区分。

client 0x180b844b0（Source2Client槽位0x400）检查事件监听dirty标志，读取并清除后调用0xa1eb50发送完整订阅位图。dirty读取函数0x9ea400明确是一次性读取/可清除，而非每帧无条件重发。它何时被置位及GOTV端是否消费206仍需继续闭合。

### CONNECTED 阶段不能只核对最后的 Signon ACK

重新从完整SetSignonState分支追踪：engine060310在CONNECTED=2分支，先为本地槽位构建并发送CNETMsg_SetConVar_t，再进入通用SignonState应答逻辑。wrapper虚表0x1805416d8与消息虚表0x180541578的RTTI均确认该类型，构建函数为104bb0。

GOTV端CHLTVClient在121b30处理SetConVar，更新userinfo，读取tv_relay区分普通观众与relay，并执行对应准入流程。CServerSideClientBase 0c9320处理CONNECTED应答时还依赖内部初始化标记。旧原型仅CONNECTED/-1应答的验证覆盖不全，必须补齐userinfo字段、时序与标记写入研究后，才能确定完整的普通观众初始化设计。仍不在此处追加猜测参数或执行在线尝试。

userinfo构建进一步确认：104bb0枚举本地标记bit9（userinfo）的注册cvar并序列化；0c90e0首批允许建立键集合，之后仅更新已存在且长度受限的键，最终置初始化标记+0x141。因而初始字段集合与以后更新权限相联系，不宜先发送空对象，再假设可以随时补任意字段。+0xbb8是另一独立标记，尚未混同为userinfo初始化完成。

系统性调用图已建立第一层工作清单：35个非stub入口，向下展开两层得到255个函数、1458条直接调用和691条间接调用记录（包含日志/分配等公共设施，不能视为同等业务分支）。4个未建立Ghidra函数的入口已用汇编核实为thunk或短叶函数。图用于逐项追踪/排除依赖，不作为“全部研究完成”的计数。

### 注册类型整体对照，而非按已见Demo挑消息

已从RTTI提取engine2/client/server的消息类型目录（含未解析的嵌套模板单列）。与现解析器215项registry静态比对，发现三个需要核实的对应差异：41的FlattenedSerializerWrapper、74实际绑定HltvReplay而旧registry为Broadcast_Command、75实际绑定HltvFixupOperatorTick而旧registry为HltvFixupOperatorStatus。这里记录的是绑定差异；41可能存在透明wrapper，75还需核对发送方向，不能仅凭名字差异判定在线接收故障。

74与已经反编译的engine060f00回放状态处理相互印证，是时钟/回退研究的一部分。统一设计应以固定构建的实际注册及序列化为准，避免把公开proto中的历史名称直接当作当前在线分派。

41的名字差异已排除为额外wire包装：engine169570序列化明确写字段1 serializers、2 symbols、3 fields、4 coord_size_params，077c30计算的CRC保存在对象+0x68缓存，没有进入这段wire序列化。该Wrapper可视为带缓存的同一protobuf外形；不据名称引入额外解包层。保留74/75的方向和实际分派核对。

### 统一类型表研究：Transform 走六分量浮点族

2026-10-19 14:19 UTC，同manifest networksystem 0e9820注册CTransform/CTransformWS为类别3、维数6；默认浮点族表274240的读取入口0d1520按字段描述+26高4位维数循环调用0cfc30。0e94c0从Transform提取前三个位置分量，并把四元数通过1b6320转换为三个角度分量；输出标记category3/count6。逆向写入0e9530/0e9580→0e6ba0把后三分量转换回四元数，位置取前三分量，scale使用固定常量。CTransformWS在0e95f0同样产生六分量，位置多经过0e6b80转换。

因此不能按内存中的position+quaternion直接读取七个浮点，也不能把类型名未知当成任意字节跳过。正式实现前仍要统一核对字段encoder选择、量化配置、WS位置转换和各类型维数；此处仅闭合默认浮点族六分量路径，未修改解析器。0cfc30含raw模式与量化边界/zero标记，沿现有量化codec整合而非另造Transform位流格式。

### CONNECTED 标记写入与 GOTV 捕获缓冲进一步闭合

engine0c4500在服务端signon状态切换至2时置+0xbb8；0ad5b0把已有客户端退回CONNECTED时也置该标记并发送SignonState。这证明它是CONNECTED状态迁移/应答相关标记，不能解释成SetConVar完成标记。userinfo+141与此独立。保留对完整应答分支的一致性审查。

CHLTVClientState与普通CNetworkGameClient的虚表差异已全列入hltv-vtable-differences.json，不能混用两种身份实现。其通用转发入口124d40根据消息可靠属性调用137450；137450在signon收集态写共享signon缓冲，运行态按可靠/不可靠/voice分别写入服务对象+608所指帧的1878/18a0/18e0区域。voice47单独保存对象；其他消息没有在此按每个观众的事件订阅位图过滤。124b70在帧完成时经1370b0复制到历史帧，再由已核对的122500发往观众。

此证据说明GOTV服务有共享捕获/转发层；仍需核对207从游戏模块注册进入该层的入口，以及源端事件筛选/包装条件。不能据共享缓冲就宣称所有事件一定在任意完美源开放，也不据game-server206的逻辑强制普通GOTV观众发送订阅。当前保持研究冻结。

137450的两个game模块回调已定位：engine接口注册表4da840对应Source2GameClients001/global6969f8；server CSource2GameClients虚表198a7c0，+150→deb310、+158→de1490。deb310判断少数消息是否标记可靠流区间；de1490按voice/少数用户消息返回0/1/2分类以选择既有包装配置。两者对207均走默认0，未读取观众订阅位图。这里闭合的是官方构建的捕获包装/区间条件，不包含源服务器私有插件或策略。不能把包装分支研究变成绕过源端限制。

### 原始类型全集已提取

0e9820的注册循环明确遍历32个0x80字节描述符；已逐项从初始化赋值及文件内字符串提取primitive-type-catalog.json，全部名称解析成功。类别覆盖signed/unsigned整数、float32聚合、float64、字符串、二进制块、bool。浮点聚合维数包含2/3/4/6/8；matrix3x4_t和matrix3x4a_t注册维数8，须以实际访问器/编码器解释，不能按内存12标量猜测。char数组/string的特化仍须通过字段构造规则识别，不能只靠此原始类型表决定所有字段。

普通接收35个非stub入口及下一层直接调用的缺失反编译共83个已批量导出，供后续逐项标注必要性；导出数量不作为语义审阅完成数量。实现仍保持冻结，三个冻结文件摘要再次一致。

矩阵访问器0e93b0/0e9400/0e9450确认八分量中间表达，经cf9e0/e6bf0转换为内存3x4矩阵；其具体几何分解仍列待解释，不按12浮点读取。float64类别默认解码dccb0调用cfa70读取单精度并cvtss2sd扩成double，汇编已核实，wire不能仅按类型名取64位。二进制块dcd80先读变长长度再读取对应字节；保持边界检查。上述均属于codec统一设计输入，尚无新实现。

### 从实际注册函数闭合 wire ID → 处理器

engine07baf0已按每次注册提取42条绑定，再用每个callback的机器指令核对virtual slot，均解析成功。engine-inbound-bindings.json保留消息ID、类型、callback、slot及实际handler。这里包含内部控制事件（0x40000000/1及-1）而非42种公开wire消息；不得直接把这些内部ID加入网络解析白名单。ID74实际绑定slot408→060f00，进一步确认Replay语义。未将仅因RTTI存在的75加入入站列表。

client CSource1LegacyGameEventGameSystem的初始化9aec00明确注册描述列表和事件消费回调9f8a80/9f8a90，服务器同类初始化bc7be0注册订阅回调c0b0f0；生命周期销毁会释放待消费事件队列。继续核对运行时消息注册global与205/207编号，避免只凭函数名串联。

client事件注册global已由汇编闭合：9b9240以ID0xcd(205)注册并写18254bbe8，9b9320以ID0xcf(207)注册并写18254bbf0；9aec00读取这两个global分别绑定9f8a80与9f8a90。因此普通客户端的描述表→事件消费并非推测。注册引用清单见client-event-registry-references.txt。事件源端生产/对HLTV的投递仍沿服务器事件管理器继续核对。

订阅发送时机进一步闭合：engine07fb00在Source2Client存在、当前连接存在且signon>3时调用客户端接口slot400；clientb844b0检查并清除事件监听dirty后，调用a1eb50发送206。该调用处未见ishltv排除。因此统一设计应镜像普通客户端的描述表/监听变化后订阅行为，使用本连接合法槽位和已下发eventid，不能预先硬编码事件编号，也不能靠中继身份替代。这个结论来自普通客户端调用时序；共享GOTV转发是否在具体源端按该位图裁剪仍是独立的源端行为边界。

205描述表接收9f9580先把所有现有事件的server eventid设为-1，再按名字匹配并覆盖收到的id和字段描述，最后置dirty+ec=1。结合b844b0→a1eb50，形成“收到描述表 → 原编号失效 → 按新编号重建订阅 → 发送206”的完整时序。统一设计必须为事件描述表维护代际，不能把旧eventid或旧字段数组留给重连/换图后的事件，也不能把重发描述表当成仅追加条目。

服务端FireEvent的正确入口是CGameEventManager slot38→bf8280；slot40→bf8510是另一个本地分派路径，不混同。bf8280仅在非dont-broadcast且事件非local时向类别2远端监听分派。类别2代理bc7df0序列化207，使用真实槽位的单比特recipient集合发给事件系统；engine2178b0/217580再送到对应客户端。此前“game-server订阅限制”由此闭合，仍与GOTV共享缓冲转发区分。

### Signon 回退与 Tick 回退是不同边界

engine07e800（实际状态校验）允许0–7；普通连接中进入小于3的状态不要求单调递增，而>=3需较当前状态前进（特殊通道/录像另有分支）。spawn count允许匹配或任一侧-1；其他错配拒绝。状态实际改变时通知client slot1c0。060310的CHANGELEVEL=7分支设置专属计数为-1、调整超时并进入换图/附加资源流程，随后仍通过统一Signon应答。

统一会话设计因此不能把“任何signon回退”视为错误，也不能把单纯net_Tick回退当作换图。新的CONNECTED/ServerInfo周期应以明确状态及server_count/表重建界定代际；重复应答与实际新周期分开，避免重复清表或把旧解析回执交给新周期。附加资源下载不属于普通赛事事件解析的隐式授权；遇确需附加内容的源保留明确兼容范围。

encoder-family-catalog.json已从真实静态表读取8个类别共20个编码器条目，含名称、编码/解码及配置初始化地址；类型表和编码器表分别对照，不把类型名直接当成wire宽度。选择器0779c0默认对QAngle用qangle，其余default，显式encoder覆盖；无法找到名称时进入类别0兜底。头部类型解析先处理容器/别名，再根据显式enum metadata替换有符号族。统一设计须将这几层顺序固定，而非为每个偶遇字段加特例。

### 自定义字段 serializer 与元数据

已定位INetworkMessages slot50→networksystem0e0c90（RegisterNetworkFieldSerializer），其参数明确包含名称、实例侧、wire类别与分量数。同名跨实例注册必须类别/分量相同。对client/server实际调用的扫描各解析20个自定义名称，类别/分量逐项一致；server另两处邻近命中已检查为另一对象的FreeEvent调用，非注册。调用窗口扫描仍保留覆盖边界，不把它单独作为所有模块的穷尽证明。

集合包括minusone、ClampHealth、cellx/y/z、posx/y/z、gameSceneNode、时间和旋转相关serializer等。0779c0在允许自定义字段组的路径读取ProtoFlattenedSerializerField_t.var_serializer_sym（字段12）并优先查注册组，继而确定wire类别和分量；没有显式匹配时才走类型/回调推导。当前原型classInfo.ts读取field_serializer_name_sym和var_encoder_sym，但未见var_serializer_sym传入字段构造；因此不能把“识别了protobuf字段”当成已使用自定义wire类型。此项纳入统一字段设计，未添加单点补丁。

077110明确给fake serializer置+211的0x40位，0779c0的自定义var_serializer查找并非仅存在于不可达分支。老回放的首份schema实读1592个field条目，含19种var_serializer名称（如cellx、minusone、ehandle、时间及颜色）；旧原型确实只为少数字段名手工特化。回放头版本为patch14178/build10896，当前固定模块为14191/build10924；因此既有全包同结果只能作为该旧输入的回归，不能当作当前构建全部字段语义的oracle。继续检查自定义值的转换/相对状态，避免仅改变读取整数有符号性就误称完成。

自定义值转换已有具体依据：client minusone getter22b180输出原int32+1，setter230700还原减1；因此规则属于serializer，不应仅绑定m_iClip1字段名。cellx getter a0e670输出ushort并标记signed整数族，setter a1e200先窄化为ushort，再按位置量化器cell位宽与g_nConfigMaxCoord组合绝对坐标；不是任意Tick delta。posx setter a1e3c0按量化范围夹取。gameSceneNode getter a0e940组合低位实体handle与上32位节点标识，使用unsigned64族；不能因原var_type名字而默认只读32位。以上函数已导出核对，仍只记录设计输入，未实现。

### 时间字段与健康字段的逻辑转换

2026-10-19 15:14 UTC，client animTimeSerializer getter22b0c0、simulationTimeSerializer getter22b1f0按int(seconds*64+0.5)生成unsigned族值；setter230670/230730按unsigned值乘1/64恢复秒。常量181ac6094/181ac6070/181ac6064从PE文件读取分别64、0.5、0.015625。funcRotatingSimulationTimeSerializer getter22b130额外检查对象标记bit10，命中时输出0；接收setter2306c0仍按1/64恢复秒。因此当前构建这些字段的时间单位是明确序列化契约，不应套成任意当前网络Tick差值。

ClampHealth getter22b100把小于1的值变为0，再标记signed整数族；接收setter2306b0写低32位，不另作同样夹取。发送端规范化与接收端恢复要分别记录，不能因为名字带Clamp就在接收器增加不同规则。angle_normalize_positive在发送访问器调用207d00规范化，接收230720直接保存解码float。20项getter/setter地址已从各注册汇编列为custom-accessor-candidates.json；其中已导出的函数逐一复核，候选地址数量不作为全部语义完成。

自定义ehandle访问器1815c0b40把原生handle转为14位索引+10位序号的wire值，invalid为0xffffff；1815c3820将wire invalid恢复0xffffffff，其他值拆14/10位，并结合当前实体系统恢复原生15位索引布局/较宽序号。headless实体关联应保留wire身份和生命周期，不直接照抄依赖游戏内存的原生handle恢复；现有parser的0x3fff索引mask与wire侧一致，仅此不构成bug。

StepSimulationFuncRotatingAngles接收230770及gameSceneNodeStepSimulationAngles接收a1e420直接保存三分量，前者发送侧另有角度规范化；Origin接收a1e440进入a0f1c0，仍须继续核对其重算职责。fish_pos_x/y/z发送为相对于对象原点的偏移；三个接收访问器b9e280/b9e2a0/b9e2c0的机器指令只从对象原点复制到字段，未直接使用wire参数。已核对汇编而非仅信反编译，下一步核对其他回调/调用模式后再决定逻辑值投影；该呈现字段保留raw float即可满足位流消费，当前不对鱼类动画作推断。

### 容器和多版本 serializer 的证据

0779c0按23e330表识别五个vector前缀：CNetworkUtlVectorBase、CUtlVectorEmbeddedNetworkVar、C_NetworkUtlVectorBase、C_UtlVectorEmbeddedNetworkVar、CUtlVector；随后处理固定数组后缀、类型别名、enum、嵌套serializer或原始类型。固定数组解析10fd60独立提取名称和长度；不能把vector长度、固定数组长度和嵌套指针存在位混为同一个value解码器。

079ff0以field_serializer_name_sym及field_serializer_version共同构造查找键；08d780比较名称后还比较版本。077240/079ff0对polymorphic_types同样读取各候选名称和版本。原型classInfo.ts只按名称建立map且未传递field_serializer_version/polymorphic_types，统一结构设计需要保留版本化引用与多态候选。旧fixture实际包含268个serializer，CBodyComponentBaseAnimGraph有版本0–3，CBodyComponentBaseModelEntity有0–5，CBodyComponentPoint有0–1，另有3个多态条目。此为真实输入结构证据，不凭此声称所有旧事件输出已错；需要逐引用核对。统计保存fixture-container-schema.json。

NEW阶段061460先安装/调用字符串表回调，然后05ff20，最后发送当前signon及server count的应答。060310在NEW分支直接转入061460并返回，不能把所有signon状态都套到同一“收到即ACK”的路径。05ff20构造ClientInfo；120fa0是服务器发送send tables的路径，不是该消息的直接接收函数，后续沿直接接收函数核对。

ClientInfo直接接收函数已由日志字符串xref定位为engine0c9390：保存send_table_crc/is_hltv，校验server_count；friends_id用于构造Steam身份但会与既有已认证身份核对，不匹配时保留已认证身份。统一实现发送真实SDK account ID，不从公开比赛选手ID猜测或替代。120fa0后续按缓存CRC决定复用还是发送完整表。

消息52从当前proto枚举核对为CSVCMsg_CmdKeyValues；engine089c80解析二进制KeyValues并投递Client::CmdKeyValues给游戏事件系统。它是公开wire消息，不是内部控制ID。消息78 EncryptedData的089df0按key_type选本地配置并进入235320；应继续识别其嵌套消息和缺少授权解密配置时的行为，不能按名称直接作为无关展示丢弃。消息76/UserCommands进入Source2Client slot5b8，PeerList60进入slot3f8，仍待游戏侧消费者分类。

EncryptedData235320在未携带payload或没有本地授权key配置时直接成功返回；已有配置才校验key长度、块对齐与有界payload，解出内嵌网络消息并继承原消息tick/来源/可靠元数据重新分派。无头设计不得把它当成可无条件解析的普通protobuf，也不猜key；普通未配置情形与官方一致跳过并保留覆盖计数，若目标事件只由受限封装提供则明确源端配置要求。已确认这不同于Steam/GNS传输层认证与加密。

UserCommands76消费者已定位clientb7cb80：按目标实体与controller取得user-command基线，处理完整/增量command，维护每controller命令编号与protobuf缓存；不是207游戏事件订阅或接收的前置调用。仍需沿后续读取者确认其对动画/预测及事件投影的边界，不能据本函数直接宣布整类可省略。PeerList60进入b7a3e0，维护合法Steam peer集合并通知游戏网络接口；与userinfo/player-controller实体归属表不同。

gameSceneNodeStepSimulationOrigin接收a1e440→a0f1c0保存三轴float，触发本地坐标派生更新与变更通知；wire仍为三分量float族。无头快照可以保留收到的三轴值，并通过自己明确的坐标合成层提供输出，不必模拟游戏对象通知系统。

### FULL推进与增量确认顺序

06a960先调用047960完成内部实体处理，成功才调用086220进行SPAWN→FULL与last_tick_recv更新；047960失败不会推进该确认。因此“收到一个非增量包即FULL”不符合当前构建。047960要求普通在线消息上下文tick>0且等于显式server_tick，delta_from必须低于当前tick，并要求spawn group创建序号不超出已接收值。缺失delta_from历史帧直接不应用该快照。full回退清帧，full同时清理双实体基线，然后应用完整状态。统一设计必须保持解析成功回执与协议状态推进的依赖。

06a960在当前last_tick_recv<1时忽略增量等待full；047960成功之后086220才更新该值。缺失增量并不允许从当前实体状态猜补。窗口达到128帧是官方诊断阈值，不把它直接解释成任意硬性协议上限。后续还需闭合ForceFullUpdate触发和分片收齐路径，才能定统一恢复预算。

完整帧分片04ca50按同tick的连续chunk序号收集；同tick乱序/重复序号会清理旧组，不将重复片追加；不同tick只有chunk0可替换现有组。收齐后拼接、解压、解析PacketEntities再04e8c0交付。ForceFullUpdate实际入口为主虚表slot100→07f1e0，清双基线并令last_tick_recv=-1；044d80仅FlushEntityPacket诊断，不能混为请求函数。普通FULL非Demo发送0642d0把last_tick_recv写入CNETMsg_Tick，构成-1重新请求完整状态的出站机制；出站时钟并不直接复制最近net_Tick。

04e8c0不是直接调用实体解析：它查找相同tick的既有队列项，且其中包含delta PacketEntities时才安装完整快照替代对象，复制tick和原消息上下文；未找到对应项则返回。完整分片收齐必须与原tick队列对齐，不能随到随立刻当作新一帧应用。061960在FULL普通在线连接被通道报告connection problem时调用07f1e0，snapshot-unlimited配置另有禁用分支；该配置不得被观察器擅自修改。

### Field path 编码表

networksystem当前构建272420保存40个opcode名/编号，2726b0是相应encode/decode函数对；PlusN对1c5220/1ccc00用读写机器指令核对方向。1d71a0的初始化常量已提取全部40项Huffman权重，与原型fieldPaths.ts逐项相同（field-path-weights.json）。这只闭合权重，不将之等同完整field-path语义；继续核对建树相同权重的排序和40项解码操作、路径边界、结束标志。不会因发现字段模型缺口而重写已验证一致的Huffman常量。

### 官方字段路径函数的隔离对照

2026-10-19 15:36 UTC，使用独立venv中的PyPI Unicorn2.1.4，仅把固定networksystem PE节映射到模拟内存，调用40个真实field-path decode函数；不加载DLL、不调用Windows/Steam接口、不连接网络、不启动游戏。每例受指令数与时间预算限制。对同样位输入，比较现原型doOp与官方函数的路径结果、实际消费位数、native overflow。

初始1823例中27差异来自PopN下溢；检查后发现研究模型以JS slice负索引误把非法负last归成有效路径，另有16例深度1的penultimate操作属于非法路径。已保留初始记录并修正研究用例的有效域判定，未改客户端。非法输入的native函数会置bitreader错误并停止，正式实现应保留相应路径边界，不把这些样例算作正常流差异。合法域最终结果见field-path-emulation.json；这项只验证当前选定操作/数据域，不替代Huffman整段、容器版本及在线状态验收。

### 更正：signed fixed8在wire decoder内已符号扩展

2026-10-19 15:38 UTC，隔离执行原生integer/bool/double解码函数后，signed fixed8的0x80/0xff分别得到-128/-1的64位表示。重新核对d01d0机器指令：调用1bf410读取8位有符号值，再movslq扩展；d04d0对fixed32同理。此前“fixed8 raw255，之后存储再窄化”的推断错误，已纠正DESIGN-GATES。冻结原型verify_enum_codecs.mjs仍把signed fixed8 ff期望为255，需在集中实施时同时纠正实现与判定；fixed32原型本已期望-1，不能把研究harness最初4项错误期望说成4项客户端bug。没有修改冻结文件。初始期望和修正后的独立原生观测均保留，避免把自洽测试当作官方语义。

### 容器读取顺序与聚合类型原生观测

06cc90明确先读pointer存在1位，仅存在且字段带polymorphic标志时，再读UBitVar类型选择值，并按1-based编号选择候选serializer。fake字段路径同样消费这些位，再跳过原生对象创建。06d9f0的fake数组长度路径读7-bit varuint。已构造隔离fake字段状态直接执行上述官方函数：6个指针/多态样例、6个数组长度样例，位数和候选选择均符合，记录container-codec-emulation.json。原型虽对m_pGameModeRules有字段名特化，仍缺少元数据驱动的统一多态模型，不能把特化当作通用支持。

对默认float族1/2/3/4/6/8维raw配置、指定8位0..1量化配置、UTF-8/null终止string及长度前缀binary，32个原生函数样例全部核对结果字节和消费位数。字符串/二进制输出使用模拟内存内预分配缓冲，不桥接系统allocator。此项验证默认维数及这些配置，不把一组量化配置扩大为全部flags覆盖。记录aggregate-codec-emulation.json，客户端仍冻结。

世界组控制：080b60对已加载/正在加载的同handle仅诊断并返回，不覆盖当前对象；083690只向尚未加载完成的已知manifest追加，未知或已完成组会诊断忽略。083a30先提升全局max creation sequence，再按handle查组并更新该组creation tick；未知组也可能提升全局序号，不能把全局max当作所有组均存在/已加载的证明。同步流程0809b0先保证父组，再等待当前组并097210激活。统一观察器需要分别保存组存在、manifest完整、父依赖和creation序号，且对重复/未知控制消息有明确处理，不能一律退出或伪造ready。

LoadCompleted消息实际发送已定位080760：仅当前通道存在且group handle非0时，构造仅含handle的13号消息，经可靠网络消息发送；换图后NULL通道只诊断，不向旧通道继续回报ready。05c550等待父组，05c9a0等待子组，05c5f0调组slot138；当前CNetworkClientSpawnGroup虚表53b8c0的slot138为05ac30，设置组状态8并通知网络世界管理器。完整调度05d770按前置任务结果0等待/1完成/2失败推进，失败释放组，不能用看见一个Load消息代替完成。无头实现的网络世界就绪条件需要明确替代这些呈现层工作，同时保留manifest/父子依赖和协议回报顺序。

Huffman建树规则进一步核对：1d7440把0权重提升为1，以创建序号递增标识叶与父；1d7da0和1d80a0都采用权重小优先、同权重创建序号大优先；1d7c40左分支写0、右分支写1。与原型构树次序一致。40个权重/操作名称、树排序和位方向已分别核对，不仅是常量相同。

量化配置本身也完成一次独立对照：0d1250直接消费schema bitcount/encodeflags/low/high并调用当前原生配置初始化，8组raw、rounddown、roundup、encode-zero、整数模式和16位宽范围的有效位数/有效flags/float32边界与原型getQuantalizedFloat一致。另对原生低/高/零哨兵组合26例比较解码结果与消费位数全部吻合。记录quantizer-native-init.json、quantizer-init-comparison.json和quantized-flags-emulation.json；这不是仅绕过配置初始化后人为填写参数的自洽验证。

### 扩展量化初始化矩阵发现的新差异

将相同配置初始化观测扩展为8种位宽×5种flags×4种范围（160组）后，不再把前8例吻合泛化为全覆盖。147组可直接执行，另13组进入官方Warning导入；核实IAT180205670对应纯诊断void Warning，后仅在模拟内存中替换为ret，继续观察全部160组，未桥接其它系统接口。初始未完成记录保留。

与冻结原型相比46组配置不一致，归因至少包括：整数精确编码的范围使用严格下一次幂和“位数不足时<”比较，原型使用ceil(log2)及<=；31位JS有符号shift造成dec_mul负值，而原生32位环绕后的分母为正；30位roundup存在float32边界/哨兵保留差异。部分31位整数配置会被原生警告提升到>31位，这些异常配置独立列出，不能全称正常比赛已出现的bug。对有效范围的差异纳入统一decoder设计，不立即逐个补丁。需追加实际schema出现分布及精确float32规则验证。

旧fixture的schema确有1个整数精确float配置：m_flWaterLevel，8位、encode_flags=-8（低位含整数模式）、high=1、low未显式指定。无31位字段。这里只证明同类结构存在于旧样本，不能把当前14191原生算法直接当作14178生产时的语义判定。RivalHub只读schema核对和本地严格evidence contract显示该导入链保存解析后的sourceFacts/摘要与demo SHA，不含原.dem或下载URL；公开回放链接为视频回放，因此本轮未取得新构建demo。未读取完整参赛者payload或修改生产数据。

量化差异进一步归并为完整算术规则，而非逐例补丁：从dd340/cff60/dcff0提取独立研究模型，明确float32每步舍入、32位有符号shift及减法环绕、整数范围严格下一次幂、位宽增长的<比较、倍率逐float ULP下调，以及量化判定的+0.5取整。研究模型的边界、有效flags、有效位数、解码倍率和编码倍率与全部160组原生初始化输出逐项完全一致（quantizer-research-model-comparison.json）。尤其31位不能简单把所有1<<bits改成2**bits：原生offset仍有signed shift语义，分母减法另有32位环绕。正式实现时按统一规则迁移；>31位派生异常配置单独处理，不用宽松猜测解码。

## 2026-10-19 16:10 UTC — native geometry decoder observations

Executed isolated fixed-manifest networksystem functions 0x1800d1930 (normal vector) and 0x1800d3d90 (presence-conditioned precise angles) using the same instruction-emulation boundary as the scalar observations. 352/352 cases matched literal independently calculated values, consumed bits and no-overflow outcome. Normal profiles cover 8/11 magnitude bits, all X/Y presence masks, all three signs and four magnitudes; precise-angle profiles cover 8/16/20 bits, all presence masks and four raw values. Normal reconstruction explicitly rounds intermediate arithmetic to float32 and clamps the reconstructed Z magnitude to zero when X²+Y² is at least one. Precise angles use profile scaling and subtract180 only for present components. This closes these sampled profile branches, not all coordinate/MP encoder branches or a live connection. No client source edits, OS calls, authentication or game launch.

Evidence: geometry-codec-emulation.json; tools/gotv-emulate-geometry.py. Main refs were re-read at16:10 UTC: Mizar5fa4c60d, RivalHubfd80bcd9, private observer0a870745 unchanged. RivalHub design PR1008 is independently being revised by its owner and is outside this work.

### UserCommands cache ownership follow-through (16:14 UTC)

Whole .text disassembly search for the concrete +0x5920/+0x5928 fields found the message handler's outlined blocks, two lazy allocation functions (944530/9446c0), and destructor966ea0. The allocator builds150 command records per slot and a separate baseline protobuf; destructor iterates64 slots. This further identifies the offsets as command cache ownership, but direct displacement search alone cannot prove absence of aliased readers. Event207 receive9f8a90 and deferred drain9aee70 independently deserialize through event manager slot60 then dispatchslot40, with optional source-tick gating. The deferred drain iterates backward; do not assert that native renderer dispatch is a stable forward queue. A headless ordered source-event projection must define its own documented ordering without inventing gameplay prediction. Remaining command consumers require pointer/alias tracing if output semantics depend on them.

### Remaining control-message classification (16:17 UTC)

PacketReliable61 engine08b010 invokes channel slot250 when not reliable, slot248 when its PacketReliable.tick marker is already covered, otherwise updates its own marker state and marks client flags. It is not merely an application event and needs channel-interface resolution before any discard policy. Internal bindings at068690/068750 carry disconnect reason/text into07f450 and presentation/session shutdown paths;089c20 changes selected local slot after checking the slot registry. Their registration ID0xffffffff is not a public wire ID. Keep this distinction in the unified dispatcher; two observer processes do not imply local split-screen slot setup.

PacketReliable boundary resolved16:20: CNetChan RTTI table2358a0 slot248=c0f80 adds unique filter object,250=c1010 removes it. c10b0 invokes filter before normal dispatcher, truthy result skips dispatch. CNetworkGameClient RTTI COL5a2038 offset8→vtable541058 first08b0e0 returns messageID!=61. Thus engine08b010 register/remove transitions gate all other application messages while boundary active. This is a necessary ordered control state, distinct from GNS reliability; preserve in unified implementation. SetPause085d10 writespaused+29d;ServerSteamID08b0d0 writes+220, notan authenticatedidentity replacement.

### Coordinate encoding cannot inherit default aggregate shape (16:22 UTC)

Direct native coord0d5fd0 observation initially applied a uniform scalar-per-dimension assumption across1/2/3/4/6/8, intentionally exposing incorrect assumptions in the harness (archived initial-assumptions evidence). Native rejects dimension2/4 without consumption. Dimension6 reads three ordinary coordinates then three presence bits and only present second-triple coordinates; it is not six identical scalars. After independently deriving that shape from the function,144 profile/dimension/sign/integer/fraction samples for dimensions1/3/6 match exact values and consumed bits. Profiles10+4 and14+5 covered. No parser changes. Dimension8 reaches additional matrix conversion and an unavailable simulated math import; this is an explicit remaining observation boundary, not a passed value test. Previously validated default float-family dimension counts do not establish coord-encoder wire shape.

### networksystem dimension8 coord wire boundary closed (17:04 UTC)

Stopped isolated native0d5fd0 exactly at matrix conversion entry1b65e0, rather than simulating its unavailable math import. Compared the two argument triples and consumed bits against independent literals.384 cases cover both10+4/14+5 profiles, all second-triple presence masks, integer/fraction flags, signs and different per-axis values; all match. Dimension8 wire shape is first three scalar coords, then three presence bits and conditional coords for the second triple. This closes wire consumption for these tested branches; it deliberately does not claim final eight-component matrix conversion. For unused fields the observer can consume this representation correctly without rendering math. Any consumer requesting a reconstructed matrix still needs the explicit conversion semantics. This is a narrower, useful module completion boundary rather than reversing unrelated rendering libraries.

## 17:40 UTC: game-client versus HLTV-viewer reply contract
Pinned s2sdk server-side interface order plus fixed engine2 primary RTTI vtables (CServerSideClient54d938, CHLTVClient55c540) gives a24-method inbound comparison in server-client-handler-comparison.json. Anchors verified against actual callbacks: LoadCompleted slotd8; ClientInfo slote0. Ordinary game-client ClientInfo wrapper0bc470 ignores base bool, whereas HLTV viewer1211b0 preserves0c9390 success/failure. Thus observer must satisfy the shared authenticated ClientInfo validation and cannot infer success from the game-client wrapper.
HLTV LoadCompleted121280 deduplicates the received handle into per-client loaded vector+178/+180. Game-client0c8f70 invokes0c8d20, which first verifies a nonzero handle exists in current game-server spawn groups. The HLTV override lacks that lookup because it represents streamed groups. Headless design still binds readiness to received/current-generation groups; no invented handles. Shared Tick0c8c10 updates channel statistics then passes last_tick_recv atmessage+50 to virtualUpdateAcknowledgedFramecountslot198; with sendjobrunning, defers that operation until completion. This corroborates distinct snapshot ACK rather than echoing netclock.

HLTV receiver evidence extends recovery contract:122180 tracks fullframeACK and rebuilds cached chunks if ACK overtakes pendingfullframe; common0cb460 accepts -1 resync and rejects regressed nonnegativeACK according to serverpolicy. Sharedsignon0c9320 requires matchingcurrentstate and servercount forstates>=3; ignoresstate7clientACK and invokes Reconnect onmismatch. HLTVstatecallback122f90 delegatescommon0c4a30 aftertimeout/fullyconnectednotifications. Do notmistake native callback completion for liveconnectionevidence.

## 17:53 UTC: PacketEntities legacy delta flag is not authoritative
A generated-protobuf parser cross-check removed an important ambiguity in earlier decompilation: engine047960's bit11 atwrapper+40 is field6(delta_from) presence, not packedlegacy_is_delta. Parser160d00 sets bit0800 forwiretag30 and writes+80; field3wiretag18 writesboolean+7c withpresence0100. Wrapper displacement30 also matchesupdated_entries andserver_tick. Thus currentordinarynetworkstate mustclassifydelta bydelta_frompresence. The frozenprototype useslegacy_is_delta andoldfixture canmaskthisbecausebotharepresent. Keepthis correction inunifiedimplementation contract; no piecemealcodechange.

Reliable-marker ownership audit: TRANSPORT-CONTRACT.md now separates client+2c1434 from transport counters and snapshot ACKs. World-only Clear preserves this marker; the explicit host changelevel transition transfers the channel across client-owner teardown/recreation. Fixed-hash vtable/instruction checks are reproducible with tools/verify-reliable-marker-ownership.py and reliable-marker-ownership.json. New owner construction starts the marker at0 without resetting retained channel sequences. Runtime implementation remains frozen.
