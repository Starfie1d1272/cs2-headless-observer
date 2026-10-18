# 执行证据与工具来源

本次云端日期为 2026-10-17 UTC（用户实测报告为 2026-10-18 北京时间）。没有本次 Windows 执行，也没有连接真实 GOTV 源。用户报告不是云端复测结果。

## 已执行结果

[offline-verification.json](evidence/offline-verification.json) 是 `verify.py` 的原始结构化报告；[wire-tests.txt](evidence/wire-tests.txt) 是合成协议边界测试的原始输出。环境和源版本见 [provenance.json](evidence/provenance.json)。完整读取/增长读取为同一公开真实录像，不是网络采集。

| 检查           | 实际结果                                                                                               |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| 完整 Demo 读取 | 329,136,562 字节；7,592 行；cursor 2,906，weapon_fire 4,402，player_death 224，round_start/end 各 30   |
| 人为增长 Demo  | 从 16 MiB 开始；后续内容尚未写入时已有事件；最终所有事件字段与完整读取一致                             |
| 独立 oracle    | demoparser2 0.42.0 四种事件数量和 tick 全相同；开火/击杀武器字段也全相同                               |
| 武器覆盖       | weapon_awp 开火 48 次；没有 taser，不宣称 taser 已验证                                                 |
| 停止与源边界   | SIGTERM 得到 cancelled，pnpm wrapper -15；源截断 exit 1；空文件、非法 magic 均 exit 1                  |
| PCAP/protobuf  | 5 个合成边界测试通过；sign-on 2 不升级 FULL；ConnectOK+候选数据仍 INCONCLUSIVE；票据/密码/debug 不导出 |
| 静态检查       | TypeScript、ESLint、architecture 通过，架构违规 0；具体命令见 README                                   |
| 在线与画面     | 自有普通观众握手、真实持续接收、Windows、画面对应及无渲染运行均未通过/未运行                           |

完整读取该次 22.98 秒、CPU 19.17 秒、peak RSS 222,972 KiB；增长读取 7.83 秒、CPU 7.96 秒、215,632 KiB。共享云机上存在其他静态分析工作、缓存差异，这不是可比较的产品性能基准，更不是持续在线 CPU/GPU 指标。此前单次完整读取约 7.21 秒也不被当作性能承诺。

`appendedEvents` 是依据初始字节数和初始 tick 的离线观察启发式，有预读误差，不是实时接入判定。事件行的墙钟是解析时刻，不是原赛事发生时间。公开样本事件行不提交仓库，避免无必要分发 Steam64；报告只保留计数。

第一次 wire 测试错误地用小于长度上限的合法 protobuf 作为超长失败输入，因此一项断言失败。修正 fixture 为 65,536 字节后通过，没有放宽解析器校验；原失败输出保留在 [wire-tests-first.txt](evidence/wire-tests-first.txt)。

执行过的命令（真实 fixture 位于云研究目录，不含用户凭据）：

```bash
gh release download test-fixtures/v2 --repo osztenkurden/cs2parser \
  --pattern demo.dem --dir /workspace/gotv-research/fixtures
pnpm --filter @mizar/telemetry-cstv... --fail-if-no-match run build
python apps/companion/research/ordinary-gotv/verify.py \
  --fixture /workspace/gotv-research/fixtures/demo.dem \
  --output /workspace/gotv-research/verification \
  --oracle-dir /workspace/gotv-research/fixtures
```

独立 oracle 实际使用云环境已有隔离 Python 的 `demoparser2==0.42.0`；从仓库以外运行：

```python
from demoparser2 import DemoParser
p = DemoParser('/workspace/gotv-research/fixtures/demo.dem')
for name, frame in p.parse_events(['weapon_fire', 'player_death', 'round_start', 'round_end']):
    frame.to_json('/workspace/gotv-research/fixtures/oracle-' + name + '.json', orient='records')
```

## REA：已配置且实际分析，不只是安装

使用用户指定的 [morluto/rea](https://github.com/morluto/rea)，npm `rea-agents@6.5.0`，MIT。官方源码阅读快照 `f1edf0da0c6c897e68664a6ab2637f8f33368bf8`，npm 发布包完整性固定在 provenance；源码快照与包版本分别记录，不假定二者逐字节相同。

仅安装于 `/workspace/gotv-research/rea`；没有重写全局 agent/MCP 配置、没有重启会话、没有购买 IDA/Hopper，也没有上传二进制、PCAP、日志或用户凭据到第三方分析服务。`--ignore-scripts --omit=optional` 不安装可选动态插桩能力。实际调用本地 CLI 和一次临时 stdio MCP 进程；Ghidra 默认分析结束后才查询，完成后导出本地证据并关闭临时数据库。

```bash
npm install --prefix /workspace/gotv-research/rea --save-exact \
  --ignore-scripts --omit=optional --no-audit --no-fund rea-agents@6.5.0
/workspace/gotv-research/rea/node_modules/.bin/rea \
  analyze-javascript-application \
  /workspace/Mizar/packages/telemetry-cstv/node_modules/cs2parser --json
/workspace/gotv-research/rea/node_modules/.bin/rea inspect-with-objdump \
  /workspace/gotv-research/cs2/game/bin/win64/engine2.dll file_headers --json
```

真实 JS 分析：相关文件 7 个、文本 1,206,750 字节、成功解析 JS 6 个、AST 节点 170,521、findings 571、parse failures 0。分析器报告模块覆盖不足，不能将模块数 0 解读为不存在网络能力；文件/HTTP 能力判断另外核对了源码。此结果不证明在线握手。

原生分析使用官方 [Ghidra 12.1.4](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build)（Apache-2.0）及官方 [Eclipse Temurin JDK 21.0.12.1+1](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1)（GPLv2 + Classpath exception）。最初只有 JRE，REA doctor 明确不能启动 Ghidra；安装完整 JDK 到任务目录后可运行。[rea-health.json](evidence/rea-health.json) 的限定 ghidra scope 为 healthy；整体 environment_healthy 为 false 是其他未安装的可选 provider，不是此次分析失败，也不需要安装它们。JDK 下载 SHA-256 与官方发布校验文件核对；所有本地归档 hash 在 provenance，其他归档 hash 是本地测得，不冒称独立签名验证。

以下环境变量只作用于当前命令/任务进程；可复现单函数 CLI（该单次 CLI 是等价入口，本次实取证通过下表的 stdio MCP 操作完成）：

```bash
GHIDRA_INSTALL_DIR=/workspace/gotv-research/tools/ghidra_12.1.4_PUBLIC \
JAVA_HOME=/workspace/gotv-research/tools/jdk/jdk-21.0.12.1+1 \
REA_GHIDRA_STARTUP_TIMEOUT_MS=600000 \
/workspace/gotv-research/rea/node_modules/.bin/rea decompile \
  /workspace/gotv-research/cs2/game/bin/win64/engine2.dll \
  0x180055a10 --provider ghidra --format json
```

## 官方二进制静态证据

只用官方 [SteamRE DepotDownloader 3.4.0](https://github.com/SteamRE/DepotDownloader/releases/tag/DepotDownloader_3.4.0)（GPL-2.0）从 Valve 内容服务器匿名下载 app 730 / depot 2347771 的三个文件作静态分析；没有运行游戏。manifest `8766757721818354077`，日期 2026-10-15。匿名**内容下载**不能作为用户游戏认证证据。请求的 steam.inf 不在该 depot，未取得；因此不能仅凭日期声称和用户本机文件完全相同，后续按 hash 比对。

```bash
# files.txt 只列以下三个路径；最初另请求 steam.inf，但该 depot 无此文件。
# game/bin/win64/engine2.dll
# game/bin/win64/networksystem.dll
# game/bin/win64/cs2.exe
/workspace/gotv-research/tools/depot/DepotDownloader \
  -app 730 -depot 2347771 \
  -filelist /workspace/gotv-research/tools/depot/files.txt \
  -dir /workspace/gotv-research/cs2 -validate
```

本次研究仅下载未固定 manifest 的当时公开版本；将来相同命令可能取得新版，必须重新核对 hash，不能沿用下列地址。没有把 Valve 文件、完整反编译文本或工具依赖提交仓库。

`engine2.dll` SHA-256：`6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21`，PE x86-64，image base `0x180000000`。其他文件大小/hash 见 provenance。调用 `open_binary(provider_id=ghidra)` → `search_strings` → `xrefs` → `resolve_containing_procedure` → `procedure_pseudo_code` 得到：

| 函数地址                      | 观察及边界                                                                                                                                                |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0x180055a10`                 | 发送 C2S_CONNECT 路径；Steam 未登录警告、auth 分支、challenge 相关密码缓冲变换、连接消息序列化。尚未验证算法/外围 transport framing；没有据此制作认证请求 |
| `0x180057cb0`                 | S2C_CHALLENGE 处理；状态条件和 auth 分支，包含服务端身份/安全信息读取。不能替代普通源抓包验证                                                             |
| `0x18007e9a0`                 | SteamInternal_ContextInit、用户票据日志与失败路径；静态反编译存在间接调用/不可达代码警告，不能据伪代码完全重建票据结构                                    |
| `0x180036950` / `0x180036d00` | record / 相关包装的本地客户端、回放和资格检查；证明有约束，不证明普通观众可录制；不采用隐藏包装绕过                                                       |

`Plat_EnableHeadlessMode` 只找到导入字符串，未建立可供普通观众使用的启动路线。PDB 引用为 engine2.pdb，GUID `fcc665e0-6e57-43ea-872e-19951a118605`，age hex `11`，Ghidra 报告 load state unknown。默认分析存在 stack/unresolved 等告警，伪代码不是源代码或完整协议规范。

原始查询 JSON、临时 stdio 驱动、stderr 与导出的 18 条证据（178,843 字节）仅保留在本云任务 `/workspace/gotv-research/rea/`。provenance 收录关键查询的 evidence_id、参数、原始文件 SHA-256 和本地路径，可核对取证链；完整本地 bundle 的 `unknowns:0` 是工具导出字段，**不表示 GOTV 未知项为零**。仓库只保留必要定位和结果，不重分发完整反编译文本。

## 协议来源固定点

- GameTracking-CS2 `5ab573fa8afb5b8db98869d79ed79399fca6e747`：`Protobufs/connectionless_netmessages.proto`、`networkbasetypes.proto`、`netmessages.proto`、`network_connection.proto`、`steamnetworkingsockets_messages_udp.proto`；另核对 `DumpSource2/commands.txt` / `convars.txt`。后者的 record 标为 cheat，fps_max 可查；不能从命令存在推出当前观战权限。
- Valve GameNetworkingSockets `d534c19aa760df3fb75fd20db13ba1932b8a5463`：`src/steamnetworkingsockets/clientlib/steamnetworkingsockets_udp.h/.cpp`，控制包 32..37，32/36 padding 至少 512、uint8 tag + uint16 LE body length，其余控制包单字节 tag + protobuf。探针仅按这些公开结构判候选，不校验证书、不解密。
- Source 1、Source 2、Demo 文件、HTTP CSTV+、GNS 与 Steam 账号身份的能力边界见 DESIGN；没有将任何一个替代另一个。

下一步需要的是 WINDOWS-TEST 中的最少真实证据，不是更多外围框架。若 record 正常出口失败且缺少合法游戏内层诊断，普通客户端握手仍是未完成的核心阻塞。

## 第二轮补充

逐 tick 连续性已与 cursor 节流分离，输出事件前再次校验；失败报告区分源截断/替换、输入格式、时钟与 I/O。审阅给出的 6400 → 6463 → 6432 反例已覆盖；[回归输出](evidence/continuity-regression.txt) 与 [真实录像重跑](evidence/offline-verification-phase2.json) 保留实际结果。第二轮握手组件、二进制精确身份、源码与调用路径见 [HANDSHAKE-EVIDENCE.md](HANDSHAKE-EVIDENCE.md)。

首轮 CI static 因 rea-health.json 未按仓库格式化失败；已修复并执行全仓 format/lint 与架构检查。修复提交 5c8b71a6c4324a7b7507d7dbe42f3d680df29d32 的全部 GitHub 检查通过，这不等于 Windows 游戏观战测试通过。

## 第三轮：写盘失败回归

审阅复现了 events ENOSPC 后 finally 重写同一队列、二次异常跳过 close/report。现改为写前移出批次、失败后不再重试；清理/关闭/报告独立保护，不覆盖首因。报告写盘失败时仍向 stderr 输出固定分类与 errno，明确 reportWritten=false，不含原异常文本或路径。

[定向原始输出](evidence/write-failure-regression.txt)：新增 5 项原 CLI 的故障注入测试，覆盖 pull/最终刷新失败、cancel/close/report 同时失败、解析首因加最终写入失败、仅报告失败；加既有回归共 9 项通过。合成句柄只验证错误控制流，不是实际磁盘耗尽或在线证据。

## 第三轮：协议核心增量

写盘修复提交 `032c1526e693e3367f2c46faaa1e7513ed851295` 的 GitHub 检查全部通过；[第三次真实 Demo 回归](evidence/offline-verification-phase3.json) 仍为 7592 行等价，正常取消保留 cancelled。

密码 helper/常量、SDK 编译和生命周期证据见 [PASSWORD-EVIDENCE.md](PASSWORD-EVIDENCE.md)；网络通道头部、GNS 分层与 LZ4/UBitVar 证据见 [CHANNEL-EVIDENCE.md](CHANNEL-EVIDENCE.md)。这些文件提供精确版本、可重放查询和实际 oracle 结果；尚无真实普通观众会话。
