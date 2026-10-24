# 研究知识与证据

本目录保存按技术主题复用的结论、固定构建资料与验证来源。

| 入口 | 内容 |
| --- | --- |
| [知识库](knowledge/README.md) | 88 条结论、80 个来源与摘要 |
| `data/` | 固定模块摘要、合成向量与机器证据 |
| `evidence/` | 按日期保留的解析、编译与回归结果 |
| `references/` | 参考项目来源、模块覆盖及复用依据 |
| `tools/` | 固定输入的原生研究与复现工具 |

当前运行条件见[兼容性](../docs/compatibility.md)，阶段记录见[归档](../archive/README.md)。

## 复现

默认仓库验证只读保留向量，组件结果写入 `work/`。原生函数模拟使用独立环境：Python 3.12、capstone 5.0.6、unicorn 2.1.4，以及合法取得且摘要匹配的游戏模块。工作区布局和操作见[研究配方](tools/TYPE-PROFILE-REPRODUCTION.md)。

`python research/knowledge/validate.py .` 校验索引、来源存在性和字节身份。每条技术结论以其直接证据和适用范围为依据；在线认证与比赛互操作按对应会话记录验证。
