# 完美 GOTV 最小 Windows 实测（#216）

本轮目标仅为：**正常客户端对照 → 官方无画面接收 → 比赛进行中持续写出 → 现有解析器持续输出**。这是待执行方案，不是 Windows 或完美 GOTV 已通过的报告。主会话安排 Windows 操作；云端没有连接用户电脑。辅助提示、自动校准和漂移不作为本轮门槛；后续提示的领先量默认采用可修改的 **120 秒配置假设**，不是实测值，也不修改源端 `tv_delay`。

## 组件和可确认的依据

- 接收候选：Valve CS2 自带 `game\bin\win64\cs2.exe` 的 dedicated 模式，无需另造一个 GOTV 解码客户端。Steam 已安装完整 CS2 时先复用它，不先重复安装整套服务器。实际安装必须同时存在 `game\csgo\bin\win64\server.dll`；缺失时通过 Steam 校验安装。
- [当前 depot 镜像](https://github.com/SteamTracking/GameTracking-CS2/blob/5ab573fa8afb5b8db98869d79ed79399fca6e747/manifests/manifest_2347771.txt)确实包含这两个文件；[Valve 随游戏分发的启动脚本镜像](https://github.com/SteamTracking/GameTracking-CS2/blob/5ab573fa8afb5b8db98869d79ed79399fca6e747/game/cs2.sh)明确识别 `-dedicated`。这是官方组件的提取镜像，不是公开引擎源码，不能证明 Windows relay 功能。
- [Steam 官方商店](https://store.steampowered.com/app/730/CounterStrike_2/)列出 Windows 10、8 GB RAM、85 GB 可用空间，属于完整游戏要求，不是测得的无画面进程资源占用。全新安装按至少 85 GB 加录制余量准备；已有安装无需再预留一份完整游戏。当前公共内容和 Windows depot 解压体积约 72.8 GB，更新暂存和 Demo 另计，不能继续用旧的“60 GB 足够”作保证。
- [当前命令提取](https://github.com/SteamTracking/GameTracking-CS2/blob/5ab573fa8afb5b8db98869d79ed79399fca6e747/DumpSource2/commands.txt)有 `help`、`find`、`sys_info`、`condump`、`tv_relay`、`tv_status`、`tv_record`、`tv_stoprecord`，**没有公布 tv_relay 的完整参数语法**。下文先查询当前运行时，不凭 CS:GO 老教程填参数。
- [当前变量提取](https://github.com/SteamTracking/GameTracking-CS2/blob/5ab573fa8afb5b8db98869d79ed79399fca6e747/DumpSource2/convars.txt)将普通 viewer 密码与 relay 密码分开，并描述由 GC/外部协调的 relay secret。普通 `connect IP:port` 可用不等于允许 relay。不要把 `tv_relaypassword` 猜作出站认证参数、复制 viewer 密码过去或关闭 secret 校验。
- 完美公开首页及其当前公开 JS 没有提供本轮可验证的 relay 参数/授权文档。没有获得供应方“允许中继”的确认，也没有把一般 GOTV 地址当成 HTTP CSTV 的 sync/start/full/delta 源。

## 1. 先做正常客户端对照

在用户提供的同一场测试赛、同一网络、同一有效时间窗，使用正常 Steam/完美启动方式打开 CS2；在游戏控制台执行**完美实际提供的完整观战命令**。地址和口令只在私有会话保留，不写入 PR。

记录 UTC、客户端版本、地图、是否能看到持续推进的比赛。连接失败保存原始错误；此时先处理地址有效期、版本、密码、网络或平台要求，不能归因为 dedicated 不支持。成功后记录结果并退出这个对照客户端，再做 dedicated 测试，避免并发实例、端口和 Steam 会话干扰。正常客户端成功仅证明 viewer 路径。

## 2. 启动官方 dedicated 并取运行时帮助

PowerShell：将路径改为 Steam“浏览本地文件”打开的目录。以下命令不连接比赛、不启动地图、不设置源端配置。不要新增 GSLT 或登录凭据。

```powershell
$Cs2Root = 'D:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive'
$Game = Join-Path $Cs2Root 'game'
$Exe = Join-Path $Game 'bin\win64\cs2.exe'
$ServerDll = Join-Path $Game 'csgo\bin\win64\server.dll'
if (!(Test-Path $Exe) -or !(Test-Path $ServerDll)) { throw '安装不完整：先 Steam 校验文件' }
$Run = Join-Path $env:USERPROFILE ('mizar-observer-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $Run -ErrorAction Stop | Out-Null
Get-Content (Join-Path $Game 'csgo\steam.inf') | Set-Content (Join-Path $Run 'steam.inf.txt')
(Get-Date).ToUniversalTime().ToString('o') | Set-Content (Join-Path $Run 'started-utc.txt')
$Native = Start-Process -FilePath $Exe -WorkingDirectory $Game -ArgumentList '-dedicated' -PassThru
$Native.Id | Set-Content (Join-Path $Run 'native-pid.txt')
```

在该进程控制台逐行执行：

```text
sys_info
help tv_relay
help tv_record
help tv_status
help condump
find tv_relay
condump
```

若没有控制台或启动即退出，保存 Windows 错误/退出码，先归入启动环境问题；不要用 `+map` 或添加无依据启动参数掩盖。`help` 可能只返回一句描述，不能假定必有参数列表。只在尚未接入比赛的空闲实例中执行无参数的 `tv_relay`、`tv_record` 查询 usage；若仍没有语法，保存输出交主会话核对当前组件/平台文档，**这一小步暂停，不猜参数**。

`condump` 的已知行为是写 `condumpXX.log`。不假定固定序号或不存在的 `con_logfile` 参数；执行后在游戏目录定位实际新文件，并复制到私有运行目录：

```powershell
Get-ChildItem $Game -Recurse -File -Filter 'condump*.log' |
  Sort-Object LastWriteTimeUtc -Descending |
  Select-Object -First 5 FullName, Length, LastWriteTimeUtc
# 选择本次控制台实际产生的文件，再 Copy-Item -LiteralPath '实际路径' -Destination $Run
```

控制台 dump 可能含地址/口令，原件保持私有，公开附件先脱敏。`Start-Transcript` 不保证记录独立游戏控制台，因此不把它当作游戏日志。

## 3. 一次授权接入，再尝试连续录制

由主会话结合上一步原始 usage 和提供方授权，形成**一条**实际连接命令。只有当前运行时明确显示 `tv_relay <address>` 时，才按此语法填入提供方给出的准确 endpoint；如果要求其他参数，按当前帮助/供应方说明处理，不套用此示例。需要 relay secret 或专门中继资格时由提供方确认，不以 viewer 成功或密码尝试替代。

执行后保存完整连接响应，再执行 `tv_status`、`condump`。只有 “connecting”/UDP 可达/收到 challenge 都不算连接成功；需要实际 sign-on、正确比赛地图及后续数据。失败分类见末表。

连接成功后，按 `tv_record` 当前 usage 开始录制；若它确认 `tv_record <filename>`，使用唯一文件基名，例如 `mizar_probe_20261017_01`（不包含目录和扩展名）。记录开始 UTC。通过以下命令找到实际 Demo 路径，不假定录制目录：

```powershell
Get-ChildItem $Game -Recurse -File -Filter 'mizar_probe_*.dem' |
  Sort-Object LastWriteTimeUtc -Descending |
  Select-Object -First 5 FullName, Length, LastWriteTimeUtc
```

在**不执行 tv_stoprecord、不退出接收器、比赛仍进行中**的情况下，第二个 PowerShell 采集至少 3 分钟大小变化，并同时运行下一节解析器。样本保存在 `$Run\growth.csv`。`$Demo` 必须是刚找到的真实路径：

```powershell
$Demo = 'D:\实际路径\mizar_probe_20261017_01.dem'
$NativePid = [int](Get-Content (Join-Path $Run 'native-pid.txt'))
1..19 | ForEach-Object {
  $f = Get-Item -LiteralPath $Demo -ErrorAction Stop
  [pscustomobject]@{
    utc = (Get-Date).ToUniversalTime().ToString('o')
    bytes = $f.Length
    modifiedUtc = $f.LastWriteTimeUtc.ToString('o')
    nativeAlive = [bool](Get-Process -Id $NativePid -ErrorAction SilentlyContinue)
  } | Export-Csv -Path (Join-Path $Run 'growth.csv') -Append -NoTypeInformation
  if ($_ -lt 19) { Start-Sleep -Seconds 10 }
}
```

窗口间变量不共享：在第二个窗口重新设置 `$Run`、`$Demo`，以上代码从运行目录恢复 PID；也可以直接在启动窗口执行采样、第三个窗口解析。文件暂时不长只能记录“该观察窗无输出”，不能仅凭 3 分钟超时宣布组件不支持；应覆盖提供方确认的缓冲/延迟和实际比赛事件。

## 4. 用 #408 的接收器增量解析

在单独 PowerShell 的 Mizar 仓库根目录，使用 Node 24、清单指定 pnpm 12.9.1，检出 [#408 固定验证提交](https://github.com/Starfie1d1272/Mizar/tree/993a3fedeff4dd033d7799c96c5effd232f54492)。不要覆盖有本地修改的工作副本：

```powershell
pnpm install --frozen-lockfile
pnpm --filter '@mizar/telemetry-cstv...' --fail-if-no-match run build
# 重新填入与上面相同的实际路径；Demo 已存在后再启动 receive。
$Demo = 'D:\实际路径\mizar_probe_20261017_01.dem'
$Run = 'C:\Users\实际用户\mizar-observer-实际时间'
pnpm --filter '@mizar/companion' exec tsx research/observer/cli.ts receive --input "$Demo" --follow --match 'pw-test-01' --execution 'map-01' --seconds 600 --output "$Run\capture.jsonl"
pnpm --filter '@mizar/companion' exec tsx research/observer/report.ts "$Run\capture.jsonl" | Set-Content "$Run\parser-report.json"
```

输出路径必须是新文件。若 Windows 文件共享导致读取失败，保留 OS 错误与原始文件，不将其误判成协议错误。`live:true` 只说明读到了解析器启动后追加的字节并跨过了初始 tick，不自动证明 live 比赛、中继权限或领先量。必须与 `growth.csv`、native 控制台、比赛仍进行的记录共同判断。

至少看到多个递增 tick 的 sample，且已知实际发生的击杀解析到 kill；第一条新事件应早于独立记录的 stoprecord / 比赛结束时间。完整静态 Demo 能解析、录制结束后才输出、单次文件大小增加，均不能代替持续出口证据。当前报告中的 relay/Windows INCONCLUSIVE 字段需要人工附证据判定，不会自动变 PASS。

取完进行中证据后才记录 UTC、执行 `tv_stoprecord`、`condump`，最后 `quit`。换图/重连另开唯一 Demo 和新 `--execution`/输出文件，先停止旧解析器；这样不会把旧地图积压误作新地图事件。首次真实链路通过后，再分别测试暂停、断流重连、换图恢复；不要在一次测试中同时改变多个变量。

## 失败分类和回传

| 观察                                                        | 分类与下一步                                                                                 |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 普通客户端也失败；或 dedicated 缺 DLL/版本不符/启动即退     | 配置、安装或环境问题；先修这个层次，不能据此判协议不支持                                     |
| viewer 成功，relay 明确返回权限、secret、password、禁止中继 | 平台中继授权问题；保留原文，由供应方确认该 endpoint 的 relay 许可。不要修改认证开关          |
| 超时、无连接响应、只有 challenge                            | 网络/协议/权限尚不能区分，INCONCLUSIVE；不能直接记“组件不支持”                               |
| 当前官方组件明确无命令，或在已确认配置/许可下明确拒绝此能力 | 组件能力候选失败；先复核版本、帮助和提供方说明，才评估最小 GOTV 客户端协议研究               |
| sign-on 成功但不长文件                                      | 连续出口未验证；区分录制命令错误、延迟/缓冲、组件限制；保留 status、录制响应、大小轨迹       |
| 文件持续增长但 receive 报错                                 | 输出格式/文件共享/解析兼容问题；保留首个错误及可授权最小 Demo，不能归入 GOTV 连接失败        |
| 比赛中多次增长且对应新事件持续解析                          | 接收—出口—解析在这次构建/这场源上通过；不推导任意平台支持、真实提前量或 Windows 产品集成通过 |

回传私有目录及一页结论：构建版本；viewer 对照；runtime help/准确命令（口令脱敏）；relay 授权依据；sign-on/录制响应；growth.csv；capture.jsonl/parser-report.json；首个新事件 UTC；stoprecord/比赛结束 UTC；是否换图/断流；失败原文。只记录已观察的结果，未跑项写 NOT_RUN。不要把提前数据接入正式 HUD/公开数据输出。

## 云端本轮实际情况

官方 SteamCMD 已下载并核验；本云环境 x86_64 上直接执行私有 32 位 ELF loader 返回 `Exec format error`，尚未运行到 SteamCMD 自更新或登录。私有提取 Debian 32 位运行库没有解决此环境的执行限制。当前约 31.3 GB 可用，低于完整 CS2 所需；没有下载游戏大包或连接任何 GOTV。此结果不能否定 Windows dedicated relay。此前完整 Demo 与受控增长输入、DAK 对照已通过，证据仍见 [README](README.md)；没有真实比赛持续出口证据。
