# 验证

验证分为本地开发检查、跨平台 CI 门禁、Windows 制品组装自检与在线实机核对四层。

## 1. 本地与跨平台 CI 检查

在 `rust/` 目录下运行（由 [`.github/workflows/observer-rust.yml`](../.github/workflows/observer-rust.yml) 在 `ubuntu-latest` 与 `windows-2025` 上自动执行）：

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release
```

测试覆盖：
- **9 个单元测试**：线格式编解码与可靠序（`wire::channel`）、合成通道全量回放与 `weapon_fire` 身份投影（`parser::core`）、ICE 密码加密与内存零化（`native::password`）。
- **集成测试**（`rust/tests/mock_port.rs` 与 `rust/tests/managed_cli.rs`）：基于 `MockPort` 覆盖完整 E2E 生命周期（Auth3 → Signon → FULL → ACK=100 → 事件输出 → ID 51/Signon 世界重置 → 实体恢复 → 1038 排空）、Auth2 握手、`stdin` EOF 停止、首次连接超时快速失败 vs 断线重连、`HealthV3`/`ReportV3` 契约及 CLI 边界退出码。

## 2. Windows 制品编译与自检

[`.github/workflows/observer-research.yml`](../.github/workflows/observer-research.yml) 在 `windows-2025` 上执行：
1. 构建并测试 Rust Release 二进制（`cs2-headless-observer.exe`）；
2. 拉取固定摘要的 Proton `steamworks_sdk_165` 头文件并用 `tools/build_native.py` 编译 `cs2_observer.dll`（校验 ABI 4 全部导出符号）；
3. 组装 `dist/observer` 后运行 `cs2-headless-observer.exe replay --input examples/synthetic-channel.json --host-version 14191 --output ...` 完成离线自检并生成 `manifest.json`（`cs2-headless-observer-package/6`）。

## 3. 在线与实机验证

离线 CI 与 `MockPort` 不替代真实 Steam / GOTV 在线验证。授权 GOTV 实机连接、最新 CS2 build 兼容与长期性能基准持续在 Issue [#1](https://github.com/Starfie1d1272/cs2-headless-observer/issues/1) 与 [#52](https://github.com/Starfie1d1272/cs2-headless-observer/issues/52) 中跟进。
