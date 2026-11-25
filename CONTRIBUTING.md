# 开发与贡献

先阅读 [AGENTS.md](AGENTS.md)、[构建指南](docs/build.md)与[验证说明](docs/verification.md)，在现有模块边界内进行可复现的修改。

## 源码组织

- `rust/`：单 Crate 核心实现（`wire`、`parser`、`native`、`session`）与单元/集成测试（`rust/tests/mock_port.rs`）。
- `native/`：C++ Steamworks API 原生桥（ABI 4）及 `tools/build_native.py`。
- `tests/native/` 与 `tests/fixtures/`：原生 ABI 测试与离线合成通道/密码对照 fixture。
- `examples/` 与 `schemas/`：Managed v2 消费者示例与 JSON Schema。
- `research/` 与 `archive/`：协议研究证据与历史版本归档（`v3.0.1` tag 可追溯旧 Python/TS 源码）。

## 提交前检查

协议或输出契约变更需同步更新对应文档与 Schema。提交前在 `rust/` 目录运行：

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

公开示例与测试仅使用合成输入；授权源地址、口令、票据与真实比赛捕获均保留在本机。
