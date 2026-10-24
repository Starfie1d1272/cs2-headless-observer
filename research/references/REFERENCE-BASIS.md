# 现有研究基础与固定构建核对

本项目研究普通观众连接、快照与比赛事件获取。参考项目用于减少重复分析；协议行为以目标构建及对应输入证据交叉确认。原始游戏模块和反编译正文不随仓库分发。

## 可复用资料

| 来源与固定版本 | 用途 | 使用边界 |
| --- | --- | --- |
| [AlliedModders s2sdk/cs2](https://github.com/alliedmodders/s2sdk/tree/5864d8db8519e80a0d870c0e0474eddc8172fb4e) | 引擎、通道、序列化、schema、服务端接口及结构 | 社区恢复的接口；未知字段与推测注释保持其原有不确定性，逐项对照固定模块 |
| [demoinfocs](https://github.com/markus-wa/demoinfocs-golang/tree/ff41285f966e8af6a45bcc33d8f8c5c95175e8ef) | 实体、玩家、字段、事件、命令增量与广播解析 | CSTV+示例接HTTP广播，并非普通IP:port握手；不用其广播支持替代普通观众接入验证 |
| [Clarity](https://github.com/skadistats/clarity/tree/bd37eab0a572cd963dcfeaeaf9afb195f12c43aa) | 独立字段模型、版本化serializer、多态、量化与兼容修正 | 检查具体输入和版本，不按项目成熟度推定每个边界均符合当前构建 |
| [SteamTracking Protobufs](https://github.com/SteamTracking/Protobufs/tree/89b77382edac5f747bfc196c2edf8996a7fe92bc/csgo) | 消息编号与字段定义 | 不包含完整状态转换和调用时序 |
| [Valve GameNetworkingSockets](https://github.com/ValveSoftware/GameNetworkingSockets) | 官方可靠/不可靠传输、分片、连接接口 | 实体和CS2应用协议位于其上；Steam身份继续由合法SDK上下文提供 |
| [CounterStrikeSharp](https://github.com/roflmuffin/CounterStrikeSharp) / [MatchZy](https://github.com/shobhit-pathak/MatchZy) | 服务端事件、实体语义与赛事管理 | 插件和框架运行在Valve服务端二进制之上，不是完整游戏服务端源码 |

旧[hl2sdk/cs2](https://github.com/alliedmodders/hl2sdk/tree/cs2)已声明停止维护并指向s2sdk。参考代码仅作阅读和交叉核对；若后续直接引入实现，须保留适用许可证与来源。

## networksystem：接口命名与位流模型

s2sdk的INetChannel声明了InstallMessageFilter、UninstallMessageFilter及FilterMessage返回真时阻止后续分派。固定模块的通道槽位与已核对的PacketReliable过滤路径吻合，能直接命名这些接口，而无需继续把它们当作未知虚函数。

Clarity的SerializerId以名称及版本共同索引，符合固定模块的serializer查找。其多态解码先读存在位，再读UBitVar；声明的候选放在1..N，与固定模块构造候选编号相符。参考实现的额外容错不自动扩大原生有效输入域。

默认float族的维数不能直接套用其他encoder。已经对照的coord聚合格式包含条件存在位，具体证据见本目录research中的原生观测。参考代码用于定位规则，固定模块用于验证当前格式。

## client：事件获取与输入模拟的边界

demoinfocs的UserCommands处理可选择关闭、只解析按钮或完整解析；完整路径更新独立命令缓存，输出UserCmd与PlayerButtonsStateUpdate。其150项命令环与非标准protobuf wire type7重置标记为命令路径提供了可复用依据。

固定client的207事件描述、按tick等待、反序列化及分派路径独立于命令缓存。当前击杀、伤害、回合和位置输出不要求模拟玩家移动或播放动画；按钮/输入输出应作为独立能力处理，不能由按键推测击杀事实。

玩家位置可以由收到的cell/offset属性计算。demoinfocs采用512单位cell；固定client从偏移量化器的原始范围推导cell移位，512范围对应9，默认回退10不是实际schema恒定值。完整转换还需使用正确的最大坐标配置。缺失属性不输出伪造的零坐标。

## engine2：快照、身份与生命周期

参考CClientFrame/CClientFrameManager明确区分快照、传输/非传输/PVS位图和按tick保存的历史。服务端结构也区分已确认tick、可靠增量tick、字符串表确认、基线更新tick及强制等待tick；不能合并成一个“最近tick”。

demoinfocs区分实体序号替换与普通删除，并区分逐字段更新时的中间状态和更新完成后的状态。这些原则适用于观察器的原子快照发布及恢复后的身份隔离；仍与固定模块的实际全量/增量处理顺序核对。

## schemasystem：已核对的接口关系

固定SchemaSystem_001的注册调用使用工厂00d950，返回静态对象076710；CSchemaSystem主虚表058598。对照IAppSystem的11个前置方法，GlobalTypeScope、FindTypeScopeForModule、FindClassByScopedName和FindEnumByScopedName分别对应011340、011350、011550、011690。原生查找以“!”区分模块作用域与全局作用域，类/枚举分派与参考头文件相符。

这确认这些接口映射，不把整个SDK结构布局或整个schemasystem模块直接标为已验证。观察器使用网络schema时，不需要实例化完整游戏对象系统。

## 参考修正的证据边界

[Clarity PR354](https://github.com/skadistats/clarity/pull/354)修复了qangle_precise且bitcount32的96位消费；原报告说明真实传送带角度全部为零，未观察非零值。固定原生precise decoder直接使用config32也消费96位，但非零IEEE字节输入的数值并不等同该参考的raw-float解释。因此须核对完整选择路径与构建差异，不能只凭全零样例采用通用数值结论。

量化算法也不能直接复制历史近似：当前固定模块的float32舍入、32位算术与倍率调整已有独立原生对照。现有库提供结构和问题线索，实际采用的规则需保持当前构建证据。
