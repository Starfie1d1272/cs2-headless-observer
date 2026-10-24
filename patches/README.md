# 固定解析器补丁

上游：osztenkurden/cs2parser 2.7.2，提交 deced963b86d3ec26b28a225824130fdf9fe3167。
cs2parser-online.patch 只保留必须修改上游文件的接缝；本项目新增解析实现以正常 TypeScript 源码维护在 parser/src/，不再藏在大补丁中。

tools/build_parser.mjs 核对提交和干净状态、应用补丁、复制 parser/src/ 覆盖层、使用锁定工具链检查上游类型并构建 client/parser_worker.mjs 的单文件产物。
上游 ordinaryViewerProtocol=2 是能力标记；worker 的外部有序 IPC 协议为 3。两者不冲突。

构建使用一次性干净 checkout；已打补丁的源码不重复套补丁。第三方许可与修改源码说明见[来源声明](../THIRD_PARTY_NOTICES.md)。
