# 架构

4.0.0 起，观察器收敛为单一 Rust Crate（`cs2-headless-observer.exe`）配合 C++ Steamworks 原生桥（`cs2_observer.dll`，ABI 4），在同一进程内完成传输、解码与托管监督，彻底移除子进程解析 worker 与内部 IPC：

```text
消费应用（Mizar 等）
  ⇄ stdin / stdout / stderr (cs2-observer-managed-json/3, cs2-observer-health/3)
  └─ session::Supervisor ──▶ session::ObserverDriver
                               ├─ native::NativePort (FFI ABI 4 ──▶ cs2_observer.dll)
                               ├─ wire::Channel / Handshake (LZ4 / Snappy / LZSS / Protobuf)
                               └─ parser::ObserverCore (Schema / StringTable / Entities / Projection)
```

## 四大核心模块与所有权

- **`wire`**：位流（`BitReader`）、块解压（LZ4/Snappy/Valve LZSS）、无 `protoc` 的极简 Protobuf 结构、GOTV 帧通道（`channel.rs`）与 Auth2/Auth3 握手（`handshake.rs`）；对 `svc_UserCmds=76` 仅保留 framing、长度校验与可靠计数，跳过内部 payload 解码。
- **`parser`**：`ObserverCore` 统一持有 Schema、类基线缓存、`StringTables`、`EntityTable`（原地更新与位集成员状态）及事件投影（`weapon_fire` / `player_death` 身份证明与 `roundClock` 快照）。世界重置（Signon 2/7 与 `svc_ClearAllStringTables=51`）统一撤销旧就绪与身份。
- **`native`**：一次性缓存 ABI 4 函数指针（`NativeFns`），管理 Steam 认证句柄、GNS 批量收发与 `SecretBytes` 密码零化清理（`ice1_encrypt`）。
- **`session`**：
  - `ObserverDriver` 管理单次连接状态机（Signon 2..=7、`WorldSyncState` 恢复、100 ms ACK 节拍与正常 1038 排空）。
  - `Supervisor` 拥有 `channel` / `world` / `sequence` 与故障退避重连，并将解析耗时（`decodeUs` / `decodeMaxUs`）仅作健康观测上报，不设 2 秒硬杀。
  - `AsyncStdoutSink`（有界队列 512，退出排空上限 2 秒）与 `AsyncStderrLogger`（有界队列 64，退出上限 200 ms）保证退出不无限阻塞，终态写入 `report.json`（`cs2-observer-report/3`）。

公开进程接口见[托管接口](managed-interface.md)，协议依据见[协议契约](protocol/README.md)，构建与分发见[构建指南](build.md)。
