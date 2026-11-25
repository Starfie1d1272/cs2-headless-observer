# 组件分发

4.0.0 起，Windows x64 统一分发单一精简发行包，不再区分 `standalone` 与 `external-node`，也不再依赖 Python 或 Node.js 运行时：

```text
cs2-headless-observer.exe
cs2_observer.dll
examples/、schemas/、licenses/
manifest.json
```

## 清单与入口

`manifest.json`（schema `cs2-headless-observer-package/6`）记录组件版本、源码提交、平台、原生 ABI（`4`）、托管 JSON 契约（`cs2-observer-managed-json/3`）、已验证 host 版本与所有分发文件的 SHA-256 摘要：

- `entrypoints.executable`：`cs2-headless-observer.exe`
- `entrypoints.native`：`cs2_observer.dll`

对应完整源码通过 GitHub Release tag 与源码归档提供（历史 v3.x 源码可通过 `v3.0.1` tag 追溯）。

## 托管启动与生命周期

- 宿主应用按 `manifest.json` 定位 `entrypoints.executable` 与 `entrypoints.native`，直接启动 `cs2-headless-observer.exe --managed --native <dll> --steam-api <steam_api64.dll> --host-version <ver> --output <dir>`。
- 托管应用将 `--output` 目录安排在安装目录之外（且每次启动前确保该目录尚不存在）。
- `--managed` 仅支持 `cs2-observer-managed-json/3`，内置 `Supervisor` 与连接级恢复。
- 通过 `stdin` 写入单行配置 JSON（`endpoint` / `password`）并保持 `stdin` 开放；关闭 `stdin`（EOF）请求安全停止并等待进程退出后读取 `report.json`。

## 应用安装与升级

应用可随安装包直接分发 `cs2-headless-observer.exe` 与 `cs2_observer.dll`。升级时建议安装到新版本目录：校验文件 SHA-256、运行 `cs2-headless-observer.exe replay --input examples/synthetic-channel.json --host-version 14191 --output <tmp>` 完成离线自检、等待当前会话完全退出后再切换版本。
