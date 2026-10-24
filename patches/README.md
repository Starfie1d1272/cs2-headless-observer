# 解析器源码与上游补丁

上游为 osztenkurden/cs2parser 2.7.2，固定提交 `deced963b86d3ec26b28a225824130fdf9fe3167`。

`cs2parser-online.patch` 保存上游文件的接缝修改；`parser/src/` 保存本项目维护的 TypeScript 解析模块。构建工具在一次性干净 checkout 中依次应用补丁、复制解析模块、执行类型检查并生成单文件 worker。

`tools/build_parser.mjs` 校验上游提交与工作树状态。每轮构建使用新的干净目录；包内对应源码提供已完成修改的解析器快照。

接口与许可见[构建](../docs/build.md)、[第三方来源](../THIRD_PARTY_NOTICES.md)。
