# 第三轮：普通密码变换与原生 SDK 边界

这批将此前“密码算法未实现”缩小为“**静态算法已实现、确定性验证通过，真实源互操作未验证**”。没有读取真实观战密码、生成 Steam 票据、启动游戏或接入任何源。

## 密码调用路径与边界

目标仍为 engine2 SHA-256 `6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21`。原始查询 hash、参数和 evidence_id 在 [password-evidence-index.json](evidence/password-evidence-index.json)，重放配方在 [password-queries.json](evidence/password-queries.json)。

`0x180055a10` 的普通密码分支先将 96 字节缓冲清零，再调用 `_V_strncpy(..., 0x60)`。密码为空时不填 encrypted_password。非空时：

1. `0x1803753d0(..., 1)` 创建 16 轮、8 字节 key 的 ICE level 1，**不是 8 轮 Thin-ICE**。
2. key 是两个 little-endian uint32：`challenge XOR 0x5ef8ce12`，`challenge XOR 0xaa98e42c`。
3. `0x180375e80` 将 key 按 big-endian 16-bit 字读取、逆序放置，构建两组 8 轮 schedule。第二组由 `0x180375d00` 处理；反汇编确认调用点 `0x180376299` 的 R9 指向 `0x1804a81b0`，纠正伪代码省略参数的显示。
4. `0x180375690` 对 12 个独立的 8 字节块加密，完整输出 96 字节；没有 CBC IV，也没有把密码明文放入 protobuf。
5. `0x180375870` 的 S-box 生成逻辑、四组模数/XOR、P-box、key rotation 均与公开 ICE 定义对应。`verify_password.py --engine2` 实际读取固定二进制的四张常量表并逐值核对，不依赖函数名字猜算法。

独立参考是 Valve [Source SDK 的 IceKey.cpp](https://github.com/ValveSoftware/source-sdk-2013/blob/be57e3d01ac7d7aa6a2cacbfef187c0b46616db0/src/mathlib/IceKey.cpp) 与 [头文件](https://github.com/ValveSoftware/source-sdk-2013/blob/be57e3d01ac7d7aa6a2cacbfef187c0b46616db0/src/public/mathlib/IceKey.H)，文件注明来自 Matthew Kwan 1996 年公开领域实现。**旧 Source 1 代码只用作密码原语 oracle，不作为 Source 2 网络协议证明。** 对应关系另由当前 Source 2 helper 和常量建立。

公开 [V_strncpy 实现](https://github.com/ValveSoftware/source-sdk-2013/blob/be57e3d01ac7d7aa6a2cacbfef187c0b46616db0/src/tier1/strtools.cpp#L857) 强制末字节 NUL。当前 engine2 对该符号的调用和预算可见，但本轮没有另下载/逆向当前 tier0 的实现。原型保守只接受 **0..95 个不含 NUL 的 bytes**；超长直接拒绝，不声称模拟任意截断和字符编码。非 ASCII 文本怎样变为本机密码 bytes 仍待真实客户端核对。

`password.py` 只有内存函数，无接收密码的 CLI、文件读取或日志。调用方将 `transform_password(known_password_bytes, actual_challenge)` 的结果交给 `connect_payload(encrypted_password=...)`。空密码返回 None 只适用于确实无密码的授权源。实现不破解密码、不替代用户票据或 GNS 加密；Python 不保证清除所有敏感副本。

## 独立验证

[password-oracle.json](evidence/password-oracle.json) 保存 256 组独立 C++ ICE 对照及 3 组完整密码变换 known-answer，输入全部是公开合成字节。挑战值覆盖 0、uint32 最大值、普通值；密码覆盖 95 字节边界。额外单元测试拒绝 NUL、超长、隐式字符串编码、非法 challenge。本批 Python 合计 14 项通过。

```bash
# ICE_SOURCE 中放上述固定链接的 IceKey.cpp 和 IceKey.H；脚本先校验两文件 SHA。
python apps/companion/research/ordinary-gotv/verify_password.py \
  --ice-source /workspace/gotv-research/upstream \
  --engine2 /workspace/gotv-research/cs2/game/bin/win64/engine2.dll \
  --output /private/new-password-verification.json
python -m unittest discover -s apps/companion/research/ordinary-gotv -p 'test_*.py' -v
```

验证器用 g++ 编译原始公开 ICE 源码，仅提供不影响算法的空 memdbgon 兼容头；不运行游戏 DLL。它不接受真实密码，只内部生成合成用例。原始源码、游戏文件和编译产物都不入库。

## 可编译的合法 SDK/GNS 适配层

`native/steam_bridge.hpp` 已针对 Valve 官方 [Proton SDK 1.65](https://github.com/ValveSoftware/Proton/tree/bc896217ffcd67f892f952b010f898fe7bd0f0a1/lsteamclient/steamworks_sdk_165) 头文件实际编译。精确 header hash、命令和 exit=0 见 [native-sdk-compile.json](evidence/native-sdk-compile.json)。这不是伪造 vtable，也不加载游戏进程或读取登录资料。

宿主必须先合法取得并初始化对应 App 730 的 `ISteamUser`、`ISteamUtils`、`ISteamNetworkingSockets`，在同一线程提供本次授权端点；这些前置能力**没有在云端验证**。适配层不创建 steam_appid.txt、不切换 App 身份、不自动登录、不设置放宽认证/加密的选项，也不销毁宿主全局 SDK。

- `Session` 先检查 AppID/BLoggedOn，调用 InitAuthentication 并等待 Current，再以默认 SDK 安全设置 ConnectByIPAddress。这些本地检查不等于 App 授权或源接受。
- GNS Connected 后重新 GetConnectionInfo；拒绝 Unauthenticated/Unencrypted，以及无认证 SteamID 的连接。本批只支持这类目标身份，不声称覆盖 IP-only/SDR/FakeIP 的全部情况。
- Source 2 调用方验证实际 challenge 后才显式 request_ticket；绑定的是当前认证 GNS remote identity，不能把 challenge 自报身份直接当可信身份。
- GetAuthSessionTicketResponse_t 必须匹配 handle 且 EResultOK 才能读取 uint64 SteamID 前缀加真实 ticket。失败、30 秒准备超时、远端断开或析构都会取消票据、关闭连接、清空自有缓冲；晚到/错误 handle 回调忽略。ready 不是 sign-on FULL，后续协议超时尚由调用方负责。
- `pump` 使用 SteamAPI_RunCallbacks，宿主以高于 10 Hz 调用，并保持单线程；不混用 ManualDispatch。`receive` 交付完整 GNS message，RAII 保证消费者抛异常也 Release。`send` 不构造 Source 2 状态应答，也不自动发送票据。

官方接口契约：[GetAuthSessionTicket](https://partner.steamgames.com/doc/api/ISteamUser#GetAuthSessionTicket)、[GNS authentication](https://partner.steamgames.com/doc/api/ISteamNetworkingSockets#InitAuthentication)、[连接与释放](https://partner.steamgames.com/doc/api/ISteamNetworkingSockets#CloseConnection)。GNS 对可靠传输/重组的责任不消除 Source 2 自身的消息封装与初始化。

```bash
g++ -std=c++20 -Wall -Wextra -Werror \
  -isystem /workspace/gotv-research/upstream/sdk165 \
  -c apps/companion/research/ordinary-gotv/native/compile_sdk.cpp \
  -o /workspace/gotv-research/native-sdk-check.o
g++ -std=c++20 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -fno-omit-frame-pointer -g \
  apps/companion/research/ordinary-gotv/native/session_test.cpp \
  -o /workspace/gotv-research/native-session-test
/workspace/gotv-research/native-session-test
```

8 个生命周期用例通过 ASan/UBSan，见 [原始输出](evidence/native-session-tests.txt)。它们使用合成 Port，验证错回调、失败、超时、断开、析构及缓冲失效；不构成 SDK 运行证明。当前未链接官方运行库、未实际取得用户票据/证书、未验证 App 730 接入资格，也没有把 C++ 传输适配与 Python Source 2 状态机接成可用客户端。SDK 运行库和用户身份获取留给合法本地宿主完成。
