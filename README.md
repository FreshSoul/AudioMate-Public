# AudioMate

AudioMate 是一款面向游戏音频工作流的桌面 AI 助手，核心围绕 Audiokinetic Wwise 展开。它把自然语言规划、WAAPI 操作、本地知识库、可复用 Skills、可执行 Plugins、MCP 工具以及可选的 REAPER 自动化连接在一起。

这个仓库是开源桌面应用本体。扩展分发采用本地优先模式：通过文件夹、压缩包或版本化的 Plugin/Skill 包共享，不依赖托管市场服务。

## 核心能力

- 通过 WAAPI 查询、检查和修改 Wwise 工程。
- 分析源音频的响度、时长、文件结构和常见质量风险。
- 使用 Ask Mode 做只读分析，使用 Agent Mode 执行经过确认的工程或文件改动。
- 从文本、Markdown、PDF、Word、Excel、PowerPoint 和 CSV 构建项目知识库。
- 将可复用流程封装为本地 Skills。
- 通过 Python Plugins 注册可调用工具，扩展 Agent 能力。
- 通过 MCP 连接外部系统。
- 使用随包 REAPER Control Plugin 执行 DAW 侧播放控制、轨道、MIDI、渲染和工程操作。

## 仓库结构

```text
main.py                         桌面应用入口
src/gui/                        PyQt6 用户界面
src/services/                   运行时服务和集成
src/tools/                      Agent 工具注册表和内置工具
src/utils/                      存储、沙箱、解析和应用路径工具
src/waapi/                      WAAPI 客户端和载荷校验
src/llm/                        LLM Provider 和 WAAPI 参考检索
plugins/reaper-control-plugin/  随包示例/生产插件
docs/                           用户和开发文档
scripts/                        维护与文档脚本
runtime/reaper-python/          本地生成的 REAPER Python 运行时（不提交）
```

LLM prompt 与 WAAPI 知识库的来源、边界和维护规则见
[`docs/llm-prompt-and-waapi-knowledge.md`](docs/llm-prompt-and-waapi-knowledge.md)。
开源版不随仓库分发第三方 WAAPI 官方文档正文；精确 API 参数以用户本机 Wwise schema 和官方文档为准。

## 快速开始

1. 在 Windows 上安装 Python 3.10+。
2. 创建并启用虚拟环境。
3. 安装依赖：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

4. 启动 Wwise，并在默认本地端口启用 WAAPI。
5. 运行 AudioMate：

```powershell
python main.py
```

6. 在 Settings 中配置 OpenAI-compatible 的 `Base URL` 和 `API Key`。

可用时，密钥会写入系统 keyring。没有 keyring 后端时，AudioMate 会退回到本地明文文件，并在平台支持时限制为当前用户可读写。

## Skills

Skills 是描述可复用 Agent 行为的本地文件夹。最小 Skill 只需要 `SKILL.md`；可选元数据可以放在 `skill.json` 中。

适合用 Skill 承载：

- QA 检查清单。
- 命名和路由规范。
- 评审/报告模板。
- 项目内反复使用的标准流程。

可以从 Settings 或 Extension Center 导入 Skills。共享 Skill 时不要包含密钥、内部 URL 或未发布项目资料。

## Plugins

Plugins 是本地 Python 扩展。一个插件目录必须包含 `plugin.json` 和 Python 入口文件，通常是 `plugin.py`。

适合用 Plugin 承载：

- REAPER 或其他 DAW 自动化。
- 批量渲染或文件处理流程。
- 内部管线集成。
- 自定义只读检查工具。

Plugins 会执行本地 Python 代码，因此只安装你信任的插件。格式说明见 [Plugin 开发格式](docs/plugin-development-format.md)。

## 开发

运行语法和测试检查：

```powershell
python -m compileall -q main.py src scripts plugins
python -m pytest -q
python -m ruff check .
```

构建发布产物：

```powershell
python build.py
```

`build.py` 会在打包前检查 `runtime/reaper-python/`。如果该目录不存在，会调用
`scripts/prepare_reaper_runtime.py` 下载官方 Python embeddable package，并安装
`python-reapy` 到本地 runtime。该目录是构建产物，不进入源码仓库；发布二进制时需随包
提供对应第三方许可说明。

## 许可证

AudioMate 源码以 GPL-3.0-only 发布，见 [LICENSE](LICENSE)。第三方依赖、Wwise / REAPER
集成边界和 REAPER Python runtime 说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 更新

开源仓库不会硬编码发布仓库。如果你在自己的 fork 或发行版中启用 GitHub Release 检查，请设置：

```powershell
$env:AUDIOMATE_UPDATE_REPOSITORY = "owner/repo"
```

发布资产应遵循更新器期望的命名：`AudioMate-vX.Y.Z-win64.zip`。

## 安全说明

- 运行 Agent Mode 修改前，先审阅生成计划。
- 不要把 API Key 放进 Skills、Plugins、截图或 issue。
- 将 Plugins 视为可执行代码。
- 能用只读 Plugin 工具时优先使用只读工具，并清楚记录写操作行为。
- 不要提交本地运行数据，例如 `settings.json`、`chats/`、`knowledge/`、`logs/`、`memory/` 或 `reports/`。
