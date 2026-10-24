# 应用托管接口

观察器以独立子进程接入，适用于任何能管理本机子进程的应用。集成无需把解析器嵌入应用，也没有 HTTP 服务或端口发现要求。

## 启动

从本地已安装便携包获取路径，启动包内 runtime/python/python.exe，参数为：

```text
client/driver.py --managed
  --native <absolute-client/cs2_observer.dll>
  --steam-api <absolute-CS2/game/bin/win64/steam_api64.dll>
  --node <absolute-runtime/node.exe>
  --parser-worker <absolute-client/parser_worker.mjs>
  --source-role ahead --source-id <new-UUID>
  --host-version 14192 --seconds 14400 --output <new-local-directory>
```

使用绝对路径、shell=false、Windows 隐藏子窗口；进程环境选择 SteamAppId=730，Steam 仍验证真实合法账号上下文。
source-role 为 ahead 或 delayed，source-id 为 UUID；每个新连接尝试使用新身份和新输出目录。

启动后向 stdin 写一行 UTF-8 JSON，精确包含 endpoint、password 两个字段，末尾换行。地址是数字 IP:port，可用方括号包 IPv6。配置行至多 4096 字节。不要把连接配置放进 argv、日志或版本控制。

写完该行后保持 stdin 开放；EOF 是停止信号，额外输入也会请求停止。不要用 write-and-close 的一次性管道来维持长时间观战。

## 输出

stdout 只有逐行 JSON 事件，不含最终报告；单行上限 64 KiB。stderr 可含原生日志及最终报告，不能直接转发到公共日志或当作纯 JSON 流。report.json 位于指定输出目录。
托管模式不落盘 events.jsonl 或 channel.frames。消费者必须持续读取 stdout，处理 EOF、非法记录、来源代际和有界缓存。

按 kind 区分 cursor、实际游戏事件和 discontinuity。保留 source/channel/world、eventServerTick、committedTick、players、pawns 与 identityResolved 的原始含义。
row.tick 在部分原始事件中可能为 0；不要据此覆盖非零 eventServerTick。消费归一化需由适配器显式选择和验证。

仅完整快照回执和有效来源检查建立就绪；discontinuity、EOF、错误或来源替换立即撤销旧提示。未知选手保持未知。实际字段以 client/ordered_parser_bridge.py 和协议契约为准。

## 停止与重试

先停止事件交付、关闭 stdin，等待旧进程释放 SDK 句柄及解析器退出；仅在超时后终止本应用拥有的子进程。退出码含义见[使用说明](usage.md)。
观察器单次运行不重连。消费者决定哪些失败可重试；不能对正常 1038、明确拒绝或清理失败无限循环。

## 运行要求与契约

Windows x64；Node.js 24.0.0 或更高，具备 WebAssembly、ReadableStream 和 structuredClone。独立包自带运行时；external-node 包接受 --node，省略时使用 PATH。不要求任何特定消费应用，不核对外部 Node 的小版本或文件哈希。

托管 JSON 契约标识为 cs2-observer-managed-json/1，由包清单声明，不新增 stdout 头记录。内部有序 IPC3 与它是不同版本轴。1.x 保持已公开字段的含义、未知值、来源代际、EOF停止和退出语义；消费者应忽略新增未知字段，以便兼容扩展。实际支持事件受源覆盖限制。

`kind` 为事件分派键。cursor 发布已提交tick；discontinuity撤销该来源就绪；游戏事件保留原始fields与eventServerTick。Steam64使用字符串，未知身份为空或未解析，players证明与pawns证明独立。所有事件均按输出顺序消费；退出/断点后不沿用旧来源证明。

包清单给出python、driver、native和worker相对路径。消费者提供合法Steam上下文、授权连接、输出目录和生命周期；既有应用的接入示例见[集成示例](integrations/mizar.md)。
