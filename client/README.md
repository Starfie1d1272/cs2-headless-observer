# 普通观众 GOTV 研究原型

本分支提供 Windows 便携式普通观众研究客户端：SDK 连接、握手、无画面初始化、增量事件解析与诊断输出已串联。离线录像和合成传输已有验证；原生桥为 ABI 2，解析进程协议为 2；便携包需同时携带当前驱动与解析进程，完美在线互操作留待集中实测。程序报告分别记录协议状态、解析进度和验证来源。

独立私有研究仓库；不接入生产 HUD 或自动编排。`follow.ts` 复用了 #408 的增长文件读取实现，解码器通过 `viewer-research.ts` 暴露标量事件。新增的纯内存握手组件与逐地址证据见 [HANDSHAKE-EVIDENCE.md](HANDSHAKE-EVIDENCE.md)。协议设计见 [DESIGN.md](DESIGN.md)，用户本机步骤见 [WINDOWS-TEST.md](WINDOWS-TEST.md)，原始结果和取证来源见 [EVIDENCE.md](EVIDENCE.md)。

第三轮核心进展见 [密码与 SDK 证据](PASSWORD-EVIDENCE.md) 和 [通道证据](CHANNEL-EVIDENCE.md)：已实现密码变换的保守 bytes 子集、GNS 内层 tag 1..4/LZ4/UBitVar，SDK 桥接编译及生命周期测试通过。SDK、握手和通道已接入同一驱动；连接响应后发送 CONNECTED 应答，请求 ServerInfo。NEW 已连接 ClientInfo、完整 schema 和解析进程；PRESPAWN/SPAWN 按实际解析检查点与父子世界组推进，见 [初始化对照](INITIALIZATION-EVIDENCE.md)。

## 网络包到实体解析器

`parser_stream.py` 将已解封的 Source 2 消息接到既有 `cs2parser` 公共 `DemoReader` 流接口：复用实体、字符串表、基线和回合派生逻辑。普通包保持原始字节及事件刷新边界；完整 serializer/class 数据转换为解析器输入头。收到缓存标记而没有完整 schema 时明确报错。转换输出是本地适配格式。

固定公开 Demo 的 185932 个原始 packet 实测恢复 4402 次开火、224 次击杀和各 30 次回合开始/结束；事件顺序、武器、玩家/攻击者 Steam64 和游戏规则状态摘要与直接解析完全一致，见 `evidence/parser-stream-offline.json`。此次以 Demo 自带真实 schema 初始化，跳过 49 个文件 checkpoint；另以同一录像的真实 schema 和 8 个世界组、合成状态消息验证了初始化驱动。在线接收仍待实测。时钟映射单独验证，流结束保持 `incomplete`。

## 云端运行

需要仓库指定的 Node/pnpm、Python 3.11+。从仓库根目录运行；云环境存在 `/workspace/.onboarding/activate.sh` 时先加载该脚本。

```bash
pnpm install --frozen-lockfile
pnpm exec tsx client/decode.ts \
  --input /absolute/path/authorized.dem --output /absolute/path/new-run \
  --follow --seconds 300 --offset 120
```

省略 `--follow` 解析已完成文件。输出目录必须不存在。`events.jsonl` 包含 cursor、weapon_fire、player_death、round_start、round_end；`report.json` 记录读取字节、事件数、CPU/内存和证据状态。Steam64 是字符串，未知身份/地图/热身/时间间隔为空。武器名保留源字符串，未建立统一命名表。每次执行生成新 `streamInstance`，每个 tick 和事件输出前检查连续性，与每秒 cursor 节流分离；文件替换、已消费尾部重写、截断及地图/server_count 改变需要新实例；不会自动重接或拼接旧事件。

`--seconds` 默认 300、上限 14400；`--offset` 默认 120、范围 0..3600。偏移只写入元数据，不将接收时间或 tick 冒充画面时间；`displayTime=null`。文件最多 8 GiB，输出队列最多 8 MiB；读取块 64 KiB，临时 EOF 每 50 ms 等待增长，输出通过下一次读取形成背压。跟随模式超时或 Ctrl+C 属于不完整停止，必须看报告；退出 0 也不代表在线成功。缺失文件、非法格式、源边界或解析失败退出非零，报告保留可区分的 category/reason/stage；已知错误使用固定安全原因，未知异常明确标记原文因可能含源数据而省略。事件写入失败后不重试可能已部分写入的批次；源清理、最终刷新、关闭及报告写入各自受保护。首因与后续 finalizationFailures 分开，eventsWriteFailed 表示事件文件可能不完整；counts 是解析产生数，不保证已持久化。报告也写不下时，stdout/stderr 的脱敏 JSON 明确 reportWritten=false、首因及 write-report 错误，退出非零；同盘满不保证 report.json 可用。文件尾部 4 KiB 的变化检测不是全文件防篡改承诺。

## 离线协议探针

```bash
python client/wire.py pcap \
  --input /private/viewer.pcap --server "$GOTV_ENDPOINT" \
  --output /private/new-wire-report.jsonl
python client/wire.py signon \
  --input /private/already-decoded-signon.bin --output /private/new-signon.jsonl
python client/wire.py c2s-connect \
  --input /private/already-decoded-connect.bin --output /private/new-connect.jsonl
```

工具不发包、不登录、不解密。PCAP 模式只识别外层 GNS 候选包、方向、时间、长度、证书/crypt 字段长度和断开码；不会把外层包还原成游戏事件。`signon` / `c2s-connect` 输入必须是已合法取得、已去除封装的**单个 protobuf 消息**，不是原始 UDP，更不是从加密包自动提取。它们检查字段结构，不能认证来源。

支持经典 PCAP、Ethernet/VLAN、Linux cooked v1、raw IPv4 UDP；pcapng 需本机 `editcap -F pcap input.pcapng output.pcap`。不支持 IPv6、IP 分片、SDR 专用封装、TCP 或压缩抓包；遇到不支持不能宣称没有游戏流。最多 64 个本地端点 flow；复用同一 UDP 五元组时也可能属于新连接，flow 不等于会话。输出不含端点、玩家名、challenge、票据、密码、证书内容或 debug 原文；仅写新文件（POSIX 权限 0600，Windows 仍由目录 ACL 控制）。原始文件留在本机，报告仍应检查再分享。

## 可重复验证

公开 fixture 不放进仓库；从 [cs2parser test-fixtures/v2](https://github.com/osztenkurden/cs2parser/releases/tag/test-fixtures/v2) 下载 `demo.dem`，确认 SHA-256 为 `143eb78444727c7a8afa29d807272076d14044fc9d7c233035d0b9a176e70f60`。

```bash
python -m unittest discover -s client -p 'test_*.py' -v
python client/verify.py \
  --fixture /absolute/path/demo.dem --output /absolute/path/new-verification
pnpm typecheck
pnpm test:events
```

`verify.py` 是 Linux 云端验证器：真实公开录像被人为分段写入，先保留后续数据，确认第一批事件已输出，再继续写入；比较完整/增量结果，检查停止、截断、空文件和非法文件。**这只是文件持续读取，不是完美持续收数。** `test_wire.py` 的包全部合成，专门验证脱敏、格式边界及避免误判，不能充当任何服务器的流量。

可选独立 oracle：在隔离 Python 环境安装 `demoparser2==0.42.0`，按 [EVIDENCE.md](EVIDENCE.md) 导出四种事件，再给 `verify.py` 加 `--oracle-dir`。此依赖仅用于独立对照，不作为客户端运行依赖。

## Windows CI 测试包

`Observer Research Package` 工作流手动触发后构建 Windows x64 原生桥、单文件解析器和便携 Python/Node 运行环境，并上传七天有效的测试制品。下载后解压运行 `Start.cmd`；仅使用本机 CS2 的 Steam API，填写当前授权测试源。包内 `manifest.json` 保存精确提交与文件摘要。构建完成和脚本启动检查分别记录，实际普通观众连接与持续事件输出由新测试赛验证。

## 普通观众实体状态

研究包在固定 `cs2parser` 2.7.2 源码上应用 `cs2parser-online.patch`，只启用独立的 `ordinaryViewer` 路径；生产依赖锁定不变。处理双实体基线、备用类基线、PVS 更新、非传输实体集合与缺帧恢复。回执在解析完成且本地检查点确认后发送；缺少依赖帧时暂停派生事件、请求完整状态，再恢复输出。

`build_parser.mjs <固定提交的干净源码目录> <输出文件>` 应用补丁并构建。便携包携带修改源码与 MPL-2.0 许可证。`verify_online_entities.mjs <补丁后源码目录>` 通过 `node --import tsx` 执行，覆盖实际二进制实体消息中的基线切换、实体重入、PVS 和恢复顺序。

当前支持服务器选择的 auth=2 / auth=3，来源、SDK 门禁与验证范围见 [认证分支对照](AUTH-PROTOCOL-EVIDENCE.md)。

