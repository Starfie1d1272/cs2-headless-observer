# 第四轮接续状态（2026-10-18，未完成）

用户要求切换到 Sol 后停止本轮。此检查点保留未完成集成，不是验收提交；上一已复审基线为 `3019fba557a08b4ac746e791aa2144a457bb3442`。没有连接真实源、Steam 用户登录或游戏运行。

## 当前改动

- `native/sdk_host.cpp`：实际 SDK C ABI 宿主，尝试合法 SteamAPI_InitEx，要求 App 730 / BLoggedOn，创建现有 SteamBridge；单进程单会话；提供 pump、状态、可信远端身份、票据内存借用、发送、接收与关闭。没有 CLI、票据日志、appid 文件、虚假身份或认证替代。已用官方 SDK 1.65 头文件编译成对象，**未链接、未运行、未做本轮回归**。
- `native/steam_bridge.hpp`：增加经当前连接信息校验的 remote_steam_id。
- `channel.py`：增加按精确 bit_count 拼接多条消息、显式字段的非可靠通道编码；优化非对齐字节提取。新行为尚无定向单元测试。
- `wire.py`：fields 可接受显式预算，上限 4 MiB，旧默认仍 65535。
- `live.py`：直接消费 Source 2 net messages 的初稿；ServerInfo、serializer 引用检查、class 信息、字符串表存在性与事件描述符/事件；实体、字符串表数据、基线和初始化仍未实现。ClientInfo 只有编码函数，驱动不得提供假 CRC 调用它。所有初始化阻塞保持关闭。
- `verify_live.py`：从固定真实公开 Demo 提取原有 Packet body 送进 live 消费器；没有制造 GNS 流。系统 libsnappy 解压文件帧。

## 已完成的实际执行

```bash
source /workspace/.onboarding/activate.sh
g++ -std=c++20 -Wall -Wextra -Werror -fPIC \
  -isystem /workspace/gotv-research/upstream/sdk165 \
  -c apps/companion/research/ordinary-gotv/native/sdk_host.cpp \
  -o /workspace/gotv-research/sdk-host-phase4.o
python3 apps/companion/research/ordinary-gotv/verify_live.py \
  --fixture /workspace/gotv-research/fixtures/demo.dem \
  --output /workspace/gotv-research/live-oracle-phase4-fast.json
```

编译退出 0。离线验证退出 **1**，原始结果在 `evidence/live-oracle-phase4-wip.json`：185932 个 packet、weapon_fire 4402、player_death 224；round_start/end 未产生，AWP 计数 0，因此 **counts_match=false**，不能说全部通过。事件 tick 均来自 event.server_tick，未借用 Demo tick 或 reliable hint。

待核对：CS2 的 round 事件可能走独立消息或实体派生；武器原名可能带前缀，当前 verifier 只数 `awp`；不要未经读取就假定原因。实际描述符包含 type=9，初稿保留非负 int32 type，仅解读 type=1 的 weapon，尚需测试未知类型/缺字段行为。旧慢速重复验证进程（exec session 94321）也已自行结束，退出 1、结果与快速运行一致；尝试终止时进程已不存在。快速运行 session 28954 已结束。无验证命令留在后台。

## 本轮静态发现与保存位置

REA/Ghidra 使用上一轮固定工具与模块 hash。私有结果分别为 `/workspace/gotv-research/rea/phase4-engine/`、`phase4-network/`，源码查询参数/hash/evidence_id 已存 `evidence/phase4-wip-index.json`。两次 REA close_binary 已成功，交互 session 39894、11397 均 EOF 结束。完整反编译结果不进仓库。

- engine2 `0x1800a70c0` 按内层类型 `0x71` 分派，读取字符串后调用 `0x1800ac400`；后者构造 `ffffffff / 41` 的 auth challenge，challenge 数写 0，携带 context；通过 SDK SendMessageToConnection flags=5 发出。这证明服务器此路径的触发消息类型，但**客户端首发 q 的完整格式、context 来源及重发时机尚未核实**。不得假设等待服务器自动发 challenge。
- 客户端后续入口仍是已确认 `057cb0 → 0578e0 → 055a10`。可下一步查 engine2 `0x180539d98`（Connecting to）xrefs，或客户端连接对象周边；此查询尚未执行。
- networksystem `0x1800bc610` Setup 写 `param_1[0x11b5]=1`（out sequence 8da8=1、in sequence 8dac=0），`[0x11b6]=0`（8db0/8db4=0）；接收解压缓存申请 0x138800。不是 Source 1 ACK 位图。
- `0x1800be510` flush 在队列复制后将 8dbc 移到 reliable hint 8dc0 并清零，再调用 Transmit `0x1800be6e0`；`0x1800bf650` 仅加锁直接调用 Transmit。尚未得到调用者发送周期、hint 实际语义和回绕完整约束。
- Transmit 非可靠头的三项 u16 来自 incoming history：0xfffd 缺失、0xfffe 特殊状态、0xffff 标志位或时间×10；不能写固定占位值冒充 ACK 历史。
- 本轮读取 `0x180060310` 再确认 NEW 调用字符串表回调/ClientInfo，SPAWN 含延后分支。尚未解出完整就绪条件。

公开 schema 已按 GameTracking-CS2 `5ab573fa8afb5b8db98869d79ed79399fca6e747` 下载 `Protobufs/gameevents.proto` 与 `demo.proto` 到任务私有 upstream。首次误用 SteamDatabase/Protobufs 路径收到 404，随后固定正确来源成功；不是来源替换或推断协议。官方 Steamworks 文档 API/ISteamUser 本轮重新核对。

## Sol 下一步

1. 从这个 WIP 继续，不重复已复审 3019fba 的整套检查。先核实客户端首次 `0x71` challenge 请求格式/flags/context，再编写 Python ctypes SDK adapter 和实际会话驱动（目前尚不存在 driver.py）。票据只在内存受控接口使用。
2. 把 Setup 的初始序号落实到有测试的通道状态，继续确认发送调度/回绕；不靠固定历史字段凑包。
3. 修复并完善 live oracle 的未通过项目，查清独立 round 消息、武器名字，添加证据支持的解码及定向测试。
4. 继续 serializer/表/基线/manifest 初始化；没有这些实现不能发 NEW/SPAWN ready。
5. 本轮变更尚未 lint/单元测试/CI 验收；完成后更新设计、命令、PR 正文、证据包和 Library。Library 当前仍是上一轮 version 1（3019fba），没有用本 WIP 覆盖。

Draft PR #410 保持 Draft；不合并、不发布、不接入生产。真实认证/平台密码互操作/完整持续收流仍须用户授权本地环境。
