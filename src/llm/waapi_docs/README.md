# WAAPI 文档数据说明

本目录只保留 AudioMate 自维护的 WAAPI 规则和空检索索引，不分发 Audiokinetic 官方文档正文。

- `_rules.md`：人工维护的高优先级规则。内容应是通用实践、防错边界和 schema-first 引导。
- `_index.json`：开源版默认为空数组，避免把第三方文档片段打包进仓库。
- `_embeddings.json`：运行时生成的本地 embedding 缓存，已在 `.gitignore` 中忽略，不应提交。

维护要求：

- 不要提交从 Audiokinetic Public Library、Wwise Help、SDK CHM 或其他第三方文档复制/同步的正文。
- 可以保留少量事实性 API 名称和我们自己的使用规则，但不要复制官方段落、表格、示例或 schema 描述。
- 需要精确参数时，运行时优先使用用户本机 Wwise 的 `ak.wwise.waapi.getSchema` 查询。
- 如果团队获得了额外授权，可在私有发行版中单独维护文档索引；不要把授权外内容合并到 public 分支。
