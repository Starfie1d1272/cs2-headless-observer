# 主会话接续检查点（2026-10-18，用户要求立即停工）

分支 `research/ordinary-gotv-observer`，Draft PR https://github.com/Starfie1d1272/Mizar/pull/410 。起点 `02e0f3cdbd0c500884e2a2297ebe1a6ffe18837b`。本文和代码一起保存为新的 WIP commit；未合并/发布。没有连接真实 GOTV、运行 Steam 用户认证或操作用户电脑。

## 源码和最后一次原子改动

新增 driver.py、sdk.py、replay.py、test_driver.py、test_live.py、test_sdk.py、native/abi_fixture.cpp。
驱动实际调用 NativePort → Steam SDK 桥 → 首发 q → 验证 challenge 的远端 ID/context → 请求票据并等待 SDK 状态 ready → 密码变换/connect → 接收/保存 channel frame → live 消费器。输入源/普通密码用 getpass 隐藏提示；票据只有内存接口；不发未实现的 NEW/SPAWN ACK。
channel.frames 私有样本不含握手数据；replay.py 可以重放净通道样本。SDK 宿主按实际 flags 5/8 发包。

最后一个已完成但**尚未验证**的原子 patch：加入 observer_boot_failure / observer_init_result 两个 C ABI 导出、NativeStartError、DLL 搜索目录、driver 阶段历史和初始化失败码；同时 ABI fixture 增加对应导出。当前 sdk.py 会要求这两个新导出。

## 实际完成的验证（不扩大到最后补丁）

- phase5-python-tests.txt：26 项 Python 测试通过，含 5 项 live、4 项驱动合成集成；这是新增 SDK ABI 测试前的完整运行。
- phase5-abi-tests.txt：随后单独 1 项实际 ctypes/C++ ABI 测试通过，覆盖 64 位句柄、字节含 NUL、send flags、票据内存接口、receive、close。fixture 没有 SDK/网络，也不产生可用票据。
- 最后诊断补丁后没有再跑测试。用户要求停工后未开新测试。
- verify_live.py 固定真实 Demo 原始网络消息体，185932 个 packet；weapon_fire 4402、player_death 224；以 Demo 文件帧 tick/原始 weapon 与 demoparser2 oracle 对照完全一致；AWP 原名 weapon_awp，48 次。已实现投影通过。
- round_start/end 各 0，目标 oracle 各 30：cs2parser 2.7.2 的 GameEvents._checkSyntheticRoundEvents 由 CCSGameRules 的 m_nRoundStartCount/m_nRoundEndCount 派生，当前 live 无实体重建。报告明确 full_event_coverage=false，验证器退出 2（部分覆盖），不能说全部通过。
- 时间字段独立保留：此 fixture 的 net_Tick 比 Demo 帧 tick 大 1378；event.server_tick 与 net_Tick 相同 4478 次、大 1 共 148 次。没有把偏移套进 live 输出。对照报告在 evidence/live-oracle-phase5.json。

## 首发 challenge 已核实

engine2 同前固定 SHA。0x180057620 初始化连接对象 +0x98=0；0x180057370 在 GNS Connected、普通 signon CHALLENGE 时格式化 connect0x%08X，V_snprintf 写 ffffffff / 71 / context，并连 NUL 一起 SendMessageToConnection(flags=5)。因此 initial_challenge_request() 的首次子集是 ffffffff71 + connect0x00000000 + NUL。服务器 0x1800a70c0 的 0x71 分派到 0x1800ac400，已在前轮确认。未实施重试调度或 reservation 变体。

REA 6.5.0/Ghidra 12.1.4 此轮原始结果仅留 /workspace/gotv-research/rea/phase5-engine/；evidence/phase5-static-index.json 保留参数、hash 和 evidence_id。close_binary 成功，exec session 49104 已 EOF 结束。完整反编译和私有 assembly 不提交/上传。

## Windows DLL 已真实交叉链接，但需要重建后才能配当前源码运行

已取得官方 mstorsjo/llvm-mingw 20261006（clang 23.1.3），任务内工具路径：
/workspace/gotv-research/tools/mingw/llvm-mingw-20261006-ucrt-ubuntu-22.04-x86_64/bin/
下载 provenance 在 tools/mingw/provenance.json。84MB 工具及各组件许可证留任务内。

通过同一固定 Valve app/depot/manifest **匿名内容下载**取得 game/bin/win64/steam_api64.dll（317080 bytes），没有用户认证。首次工具因为 HOME 只读失败，配置 XDG_DATA_HOME 为任务内目录后成功。原始 Valve DLL 不进仓库/Library。

实际链接产物 /workspace/gotv-research/mizar_observer_sdk.dll，约 517KiB，PE x64；/workspace/gotv-research/windows-pe-phase5.txt 记录 imports/exports。只依赖 steam_api64.dll 和 Windows UCRT/系统 DLL，没有额外 LLVM runtime DLL。该产物在最后 boot 诊断补丁**之前**链接，缺少新增的两个导出，**不可直接和当前 sdk.py 混用**。Library WIP 附件只为保存产物，清楚标为旧 ABI，主会话应重建。

链接曾暴露编译检查未发现的问题：Valve Proton 的 1.65 headers 禁用了部分 C++ inline helper 定义，造成 ParseString/GetSteamID64/Release 未定义；已切换真实 SteamAPI flat exports。flat header 引用 steam/steam_api.h，需要两个 include 根。任务内 phase5-sdk-include/steam 是指向 upstream/sdk165 的 symlink，未修改第三方 headers。

最后成功链接命令（对当前新补丁重跑即可）：

```bash
source /workspace/.onboarding/activate.sh
/workspace/gotv-research/tools/mingw/llvm-mingw-20261006-ucrt-ubuntu-22.04-x86_64/bin/x86_64-w64-mingw32-clang++ \
  -std=c++20 -shared -O2 -static-libstdc++ -static-libgcc -Wall -Wextra -Werror \
  -isystem /workspace/gotv-research/phase5-sdk-include \
  -isystem /workspace/gotv-research/upstream/sdk165 \
  apps/companion/research/ordinary-gotv/native/sdk_host.cpp \
  /workspace/gotv-research/libsteam_api64.a -o /workspace/gotv-research/mizar_observer_sdk.dll
```

libsteam_api64.a 是用 llvm-readobj --coff-exports 导出实际 Valve DLL 名称后生成 steam_api64.def，再 llvm-dlltool -m i386:x86-64 -d ... -l ... 创建的 import lib。没有把第三方代码或 DLL 链进自己的 DLL。跨编译/PE 静态验证不等于 Windows 已实际加载/Steam 认证通过。

## 实际未完成项和下一步

1. 重建最后诊断补丁；运行有变化的 Python/ABI/原生验证；补 CLI 失败报告/清理测试、native failure 码、依赖加载诊断。driver.report 当前含安全 stage 历史；还没有一页 Windows 启动文档或 run_windows.ps1。
2. Windows 本地完整依赖：64 位 Python 3.11+、本构建 DLL、用户本机合法 steam_api64.dll、同一 OS 用户下已登录并拥有 CS2 的官方 Steam 客户端。源码 CLI 参数已支持 --steam-api，本地依赖目录由 os.add_dll_directory 提供。
3. SteamAPI_InitEx 必须知道 AppID。官方 https://partner.steamgames.com/doc/sdk/api 的 Initialization 文档要求 Steam 启动上下文或开发用 steam_appid.txt，且必须有对应账户许可。**尚未提供上下文 launcher**；不能声称当前双击/命令即可认证。可以让用户本地按文档配置 App 730 开发上下文，不能用匿名服务端或换 AppID 替代。当前代码不创建 appid 文件、不登录、SDK init 失败返回安全数值。
4. 完整 NEW/SPAWN 尚缺 serializer field decoder、string table 解码和回调、instancebaseline、session manifest/spawn group 和实体 full snapshot；ClientInfo 的 send_table_crc 来源仍未完成。driver 在收到 NEW 后保存样本并退出 incomplete；因此还没有持续在线事件验收。
5. 本轮额外静态证据：engine2 0x1800680e0 ProcessClassInfo，create_on_client=false 走 0x180085ad0；true 在 CRC 匹配缓存（本地 +0x234）时解析缓存，否则依赖本地 server API，不能假报缓存匹配。0x180060ae0 查 genericprecache/instancebaseline/userinfo/server_query_info，instancebaseline 安装回调 0x18006bf40。这些是可继续限定研究的具体入口，不应盲试假 CRC/假 ACK。
6. 还未更新 PR 正文、最终 CI、正式 Library 取证包；上一正式 Library 仍 version 1（3019fba）。新 WIP 附件另存，不冒充最终客户端。

CI：本轮检查点提交尚无已查询 run ID；不等待 CI。最后基线全绿 run 为 39072247268（3019fba），不能沿用到本轮。所有本轮验证/REA执行均已结束，无后台源连接。
