# LLM Prompt 与 WAAPI 知识说明

本文档说明 AudioMate 开源版中哪些文件会影响 LLM 行为、哪些文件属于 WAAPI 知识数据，以及维护时应遵守的边界。

## Prompt 来源

运行时系统提示词由以下模块分层组装：

- `src/gui/controllers/turn_pipeline.py`：按 Ask Mode / Agent Mode 生成主提示词，并注入当前连接状态、执行后总结规则和输出协议。
- `src/engine/prompt_blocks.py`：把提示词切分为 `static`、`session`、`turn` 三层，用于 Provider 缓存和诊断。
- `src/engine/prompt_assembler.py`：按当前设置、Skill、Plugin、MCP、用户知识库和副 Agent 状态生成动态提示块。
- `src/engine/prompt_guidance.py`：生成结构化工具、MCP 和文档读取工具的提示说明。
- `src/utils/skill_store.py` 与 `src/services/plugin_runtime.py`：把用户导入的本地 Skill / Plugin 转换为可注入的能力说明。

这些提示词是应用运行逻辑的一部分，不包含私有凭证。维护时不要写入 API Key、账号、内网 URL、未发布项目资料或个人路径。

## WAAPI 知识来源

当前开源版 WAAPI 知识分为两类：

- `src/llm/waapi_docs/_rules.md`：人工维护的高优先级 WAAPI 安全规则和常见坑位，会稳定注入系统提示词。
- `src/llm/waapi_docs/_index.json`：开源版默认为空数组，避免在仓库中分发第三方官方文档正文。

开源版不提交从 Audiokinetic Public Library、Wwise Help 或 SDK CHM 同步/摘录的 API 参考正文。需要精确参数、返回结构或版本差异时，运行时优先使用用户本机 Wwise 的 `ak.wwise.waapi.getSchema`、`ak.wwise.waapi.getFunctions` 和 `ak.wwise.waapi.getTopics`。`src/llm/waapi_docs/_embeddings.json` 是本地运行时缓存，不应提交。

## 维护规则

- 不要把官方文档正文、用户项目、内部规范、测试密钥或实际工作路径写入 WAAPI 文档。
- 可维护少量事实性 API 名称和自有防错规则，但不要复制第三方段落、表格、示例或 schema 描述。
- 修改 `_rules.md` 后应运行 WAAPI 检索和 prompt 相关测试。
- 修改 prompt 组装逻辑后至少运行：

```powershell
python -m compileall -q main.py src scripts plugins
python -m pytest -q src/test/test_provider_events.py src/test/test_prompt_guidance_context.py src/test/test_golden_tasks_and_blocks.py
python -m ruff check .
```

## 开源发布检查

发布前至少检查：

- 使用通用敏感词和团队自己的私有词表扫描 `src/`、`docs/`、`README.md`、`SECURITY.md` 和打包脚本。
- 覆盖 API Key、访问令牌、账号名、个人路径、内网 URL、私有产品名、未发布客户/项目代号和本地运行数据路径。
- 确认 `.claude/`、`skills/`、`reports/`、`.env*` 和 `src/llm/waapi_docs/_embeddings.json` 没有进入 Git 索引。
