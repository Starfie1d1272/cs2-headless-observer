# 无头接收与私有观察辅助研究（#216）

准备连接完美 GOTV 时，优先按 [Windows 最小实测流程](WINDOWS-TEST.md)完成客户端对照、运行时参数核对、比赛中录制和解析；不先做时间校准。

这是可运行研究工具，不是 Mizar 已支持的实时观战功能。入口不由 Companion 启动，不监听网络，不向 Program、HUD、OBS、RivalHub 或公开雷达发送数据。当前正式 `ObserverAssistProjection` 仍为 unavailable。

```text
授权接收进程写入增长中的完整 Demo → receive → 私有 JSONL
正式画面的同源、经验证时钟参考      → receive → 私有 JSONL
                                两路 → assist → 单条临近提示 JSONL
```

`receive` 的输入是文件，不能传 `connect IP:port` 或 HTTP URL。HTTP CSTV 的 sync/start/full/delta 路线已有 `@mizar/telemetry-cstv` 与 `cstv:probe`，本工具不重复实现 HTTP reader，也不将普通 GOTV 端口转换成广播 URL。

## 已有成果与路线判断

已核对 [Issue #216](https://github.com/Starfie1d1272/Mizar/issues/216)、历史 #27/#54 的 CSTV 接入、现有源游标和 Program/Lookahead 边界。开工时开放 PR #246、#367、#392、#397、#398、#400、#403–#406 没有此接收器实现；这些分支未修改。

首轮 `mizar-lookahead-spike.zip` 和 `cs2-lookahead-feasibility-zh.md` 的 Library 记录已找到（2026-10-06，37,266 / 15,319 字节），但云端 materialization 返回 401，未取得原始字节或核验旧 evidence。因此没有复制其未读源码，也不将旧 54 项测试算作本轮结果。其输入校验/A2S/打印实验计划不在本轮重复开发范围。

本轮复用仓库已锁定的 cs2parser 2.7.2（MPL-2.0），纯解析绑定由 `telemetry-cstv` 的独立 `./research` 导出拥有；Node 文件/进程工具归 Companion 研究目录。DAK 已将解析委托给 cs2df/demoparser2：复用其冻结环境中的 demoparser2 0.42.0 作独立对照，没有重写 Demo 解码器或改 DAK。实际样例有合法 userid=0，现有生产 normalizer 要求正整数；研究结构直接复制解析器提供的 Steam64，不改变生产契约，不把槽位猜成身份。缺身份的击杀可诊断但不能提示。

2026-10-17 的上游核对：

| 证据                                                                                                                                                                                          | 支持的结论                                 | 不支持的结论                                                          |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | --------------------------------------------------------------------- |
| [GameTracking 命令快照](https://github.com/SteamTracking/GameTracking-CS2/blob/5ab573fa8afb5b8db98869d79ed79399fca6e747/DumpSource2/commands.txt)仍有 tv_relay/tv_retry/tv_record             | 值得首先实验原生 dedicated relay           | 未执行二进制，不证明 sign-on 或 relay 录制可用                        |
| [同快照变量](https://github.com/SteamTracking/GameTracking-CS2/blob/5ab573fa8afb5b8db98869d79ed79399fca6e747/DumpSource2/convars.txt)区分 tv_password、tv_relaypassword、tv_relay_secret_code | 普通观战许可不自动具有中继许可             | 不能尝试猜密码、绕过认证或推断赛事方配置                              |
| [cs2parser 当前源码与文档](https://github.com/osztenkurden/cs2parser/tree/0c6c22e95251dfd6432d470ee3bbd3be2d61173d/docs)提供 Demo 流和 HTTP 广播读取                                          | 文件出口或提供方明确提供 HTTP 广播时可复用 | 不含任意 GOTV UDP sign-on 客户端                                      |
| [CS2 容器维护者要求](https://github.com/joedwards32/CS2#system-requirements)至少 60GB 磁盘                                                                                                    | 云环境应先核对容量                         | 本轮约 30GB 可用、无 CS2/SteamCMD，未下载或运行游戏；不构成路线 No-Go |
| [demoinfocs 上游](https://github.com/markus-wa/demoinfocs-golang)支持 Demo/CSTV+                                                                                                              | 可作为不同语言的解析备选                   | 不能因此认定它是普通 GOTV 地址转换器                                  |

Valve Developer Wiki 的 [CS2 dedicated 页面](https://developer.valvesoftware.com/wiki/Counter-Strike_2/Dedicated_Servers)本轮返回 403，raw 入口也不可读；cs2parser 文档引用的旧 Valve relay.js 镜像路径返回 404。没有把无法读取的官方文档或历史 CS:GO 说明当作当前 CS2 运行证据。GameTracking 是提取镜像，不是 Valve 完整引擎源码。

**当前结论是条件性继续，原生路线 INCONCLUSIVE。** 若真实 relay 身份被拒绝，先由提供方明确授权/协议；若可接入但无连续出口，优先请求提供方的 HTTP CSTV 或服务端增长 Demo 出口。本接收器已验证后者的消费侧。供应方授权的服务器导出插件是另一种需要单独接口与权限评估的选择；HLAE+图形 CS2 不满足本轮无画面接收目标。不因当前缺源重写完整 GOTV 协议。

## 安装与离线复跑

在仓库根目录执行；云环境先 source `/workspace/.onboarding/activate.sh`。使用根清单的 Node/pnpm，保持锁文件。

```sh
pnpm install --frozen-lockfile
pnpm --filter @mizar/telemetry-cstv... --fail-if-no-match run build
pnpm exec tsc -p apps/companion/research/observer/tsconfig.json
pnpm exec vitest run apps/companion/research/observer/observer.test.ts

mkdir -p /tmp/observer-input
gh release download test-fixtures/v2 --repo osztenkurden/cs2parser \
  --pattern demo.dem --dir /tmp/observer-input
sha256sum /tmp/observer-input/demo.dem
# 必须是 143eb78444727c7a8afa29d807272076d14044fc9d7c233035d0b9a176e70f60

# 邻接 cs2-demo-format 仓库先按其 uv.lock 冻结准备环境；本轮已有该环境。
../cs2-demo-format/python/.venv/bin/python \
  apps/companion/research/observer/dak-oracle.py \
  /tmp/observer-input/demo.dem /tmp/observer-input/dak-kills.json

pnpm --filter @mizar/companion exec tsx research/observer/verify-demo.ts \
  /tmp/observer-input/demo.dem /tmp/observer-input/dak-kills.json /tmp/observer-input/demo-report.json
pnpm --filter @mizar/companion exec tsx research/observer/verify-cli.ts \
  /tmp/observer-input/demo.dem /tmp/observer-input/cli-report.json
```

所有输出要求新文件，不覆盖已有采集。原始 Demo 和逐事件输出留在 Git 外；报告只保留摘要。本轮真实结果见 [evidence](evidence/)。真实输入验证不是默认 CI 下载任务；测试无素材时不会输出跳过后的 PASS。

## 测试赛：先验证原生接入与录制出口

以下步骤由操作者在有足够磁盘且已安装当前 CS2 的**云端接收主机**执行。本轮未操作比赛、未获取新凭据、未启动用户 Mac/Windows。

1. 向提供方取得明确授权的早源地址、中继身份条件、预期延迟及比赛标识。另记录正式节目源的授权方式。只有普通观战密码时先确认 relay 资格，不将它自动当作 relay 密码。
2. 记录安装清单/build 与运行日志。启动接收器，不加 `+map` 创建比赛：

   ```sh
   export CS2_ROOT=/srv/cs2
   test -x "$CS2_ROOT/game/cs2.sh"
   "$CS2_ROOT/game/cs2.sh" -dedicated -console -condebug
   ```

   在该进程控制台依次执行 `version`、`help tv_relay`、`help tv_record`、`tv_status`。保存实际输出；启动失败/命令不可用分别记录，不能用本文件推定当前 build 支持。

3. 按实际 help 和提供方认证说明连接。无密码且获准的候选命令为 `tv_relay <提供方给出的原始地址>`；有认证要求时按其当前明确方法输入，不把密码放启动参数或公开报告。执行 `tv_status` 保存真正接入后的状态；connecting、A2S 响应、进程存活均不算接入通过。
4. 只有接入成功后执行 `tv_record observer_early_001`，记录开始 UTC，找到实际创建的 `.dem`。确认路径和文件存在，不自行创建、截断或覆盖引擎的录制文件。在另一终端执行：

   ```sh
   export EARLY_DEM=/srv/cs2/game/csgo/observer_early_001.dem
   test -f "$EARLY_DEM"
   pnpm --filter @mizar/companion exec tsx research/observer/cli.ts receive \
     --input "$EARLY_DEM" --match test-match-001 --execution map-run-001 \
     --follow --seconds 14400 --output /tmp/early-001.jsonl
   ```

5. 保持录制运行，在另一个终端 `tail -f /tmp/early-001.jsonl` 查看事件。记录第一条 `live:true` 击杀时刻与文件增长区间，再由操作者安排测试赛暂停、恢复、短断线和换图。只有**录制未结束且比赛未结束前**已多次输出匹配的事件，才支持连续出口通过；单个 recording 日志或赛后完整 Demo 不够。
6. 按当前引擎命令由操作者结束录制（候选 `tv_stoprecord`），保存其 UTC 和控制台输出；再停止本工具（Ctrl+C）。同图重开、换场或换图用新的 `--execution` 和新录制文件，重启两路采集与 assist。不要把多份 Demo 拼接在同一文件里。

文件替换/截断会结束旧解析器，有限次数重建 generation，从新初始化重读；已有前缀标记 `live:false`，不供提示。暂停字节输入会发出 input-idle；恢复后重新收集匹配锚点。已完成文件等待可检测的替换/缩短，不反复补播整份录像。每个 receiver 启动有独立 UUID，进程重启不沿用旧 generation 身份。

## 正式画面对齐与私有提示

GSI 没有本轮已证明可与 Demo 相减的同域 tick。**只有早源时可以完成接入/提取验证，不能得到可信倒计时。** 第二条被称为 program 的 Demo/数据流仍须通过同一事件的画面帧或可验证游标证明它对应实际播出，而不是另一个任意延迟的流。

在测试赛中，操作者提供正式画面的经验证时钟参考文件，按上述 receive 命令另开进程，使用相同 match/execution、新输出 `/tmp/program-001.jsonl`。保留至少三个跨越五秒以上、可唯一匹配的击杀画面证据，并记录参考流与画面的误差/延迟。未确认时先不传 `--display-evidence`，输出将保持 `program-display-unverified`。

```sh
pnpm --filter @mizar/companion exec tsx research/observer/cli.ts assist \
  --early /tmp/early-001.jsonl --program /tmp/program-001.jsonl \
  --horizon 10 --output /tmp/assist-001.jsonl
# 人工完成画面对应验证后，重新启动到新输出文件，并加：
# --display-evidence 'local-video-001:已核对的帧号/时间区间'
```

`--display-evidence` 是操作者提供的证据引用，不是程序自动验证结果；不能为拿到提示而随便填写。工具不捕获实际画面，也不自动将 GSI 变成 tick。参考流与实际屏幕关系未证明时，双时间轴仅为源间研究结果。

对齐用同一回合/双方 Steam64/武器的唯一事件配对，至少三点拟合时钟偏移和斜率；重复或缺身份不算锚点。输出拟合残差、漂移 ppm、当前有效领先量与单条临近击杀。`--horizon` 可选 0–30 秒内正数；回合剩余时间、固定赛事延迟和接收墙钟都不充当源时钟。提前量是两路**已观测游标**间的量，接收/刷盘延迟须另用独立时间证据测量。

暂停/暂停状态未知、catchup、失联、源身份或地图执行变化、tick 回退、异常 Program 播放速率、过大拟合漂移都会清空提示与锚点。恢复不补播旧提示；新锚点建立后仅接受新事件。默认 1.5 秒新鲜度、120 秒锚点有效期、最多五分钟匹配历史；真实出口刷盘周期可能使其频繁拒绝，需要先量测再评估阈值。每 100ms 发布撤下状态，即使输入彻底静默也不保留旧提示。

## 采集报告与已知限制

```sh
pnpm --filter @mizar/companion exec tsx research/observer/report.ts /tmp/early-001.jsonl \
  > /tmp/session-report-001.json
```

此报告自动统计代际、击杀、完整身份、新字节事件区间及错误。请补充下列独立证据再判定，不直接公开含地址/凭据的控制台与原始采集：

| 关卡             | 当前默认结论 | 测试赛必须附的证据                                                             |
| ---------------- | ------------ | ------------------------------------------------------------------------------ |
| Relay 接入       | INCONCLUSIVE | 当前 build、提供方 relay 许可、sign-on 完成、tv_status 与断线原因              |
| 比赛进行中输出   | INCONCLUSIVE | 录制开始/结束 UTC、持续文件增长、结束前多条事件与同场录像对应                  |
| 真实领先量与漂移 | INCONCLUSIVE | 同场/执行绑定、正式画面对应、配对事件、残差、长时漂移、暂停/断线前后表现       |
| Windows 集成     | INCONCLUSIVE | 用户自行测试的 Program CS2+OBS+接收器 CPU/RSS/磁盘、帧率、共享读和录制刷盘表现 |

本轮不包含产品 UI 或 Windows 安装包。当前输出是私有研究 JSONL；人机使用体验和真实 OBS 捕获非泄漏验收仍待实机。原型没有生产输出通道，但这不等于 Windows 的全屏捕获安全已验收。

输入按 64KiB 需求读取，文件上限 8GiB，输出上限 256MiB，运行上限四小时、重建最多 32 次；超限明确失败，不无限累积。匹配/候选队列有数量及时间限制。第三方解析器的所有内部内存没有硬上限保证，报告中的 RSS 是本轮样例观测，不能冒充长时 Windows 资源结论。

轮询检查文件身份、长度和已消费尾部 4KiB，不能保证发现轮询间发生且尾部完全相同的原地重写，也不验证整个旧前缀未变化。原生录制末尾会更新的头部 trailer offset 不参与尾部比较；生产者应使用独立文件/原子替换，不原地拼接。源记录的 `live:true` 只证明读取了启动后追加的字节，不证明这些字节相对比赛墙钟有多新。无相关外部证据时不宣称比赛中输出或真实领先量通过。
