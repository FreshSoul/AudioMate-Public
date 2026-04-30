<img width="1254" height="1254" alt="AudioMate" src="https://github.com/user-attachments/assets/1030fde8-5d59-42a2-8bfc-4f073e7725a7" />

# AudioMate

当前版本：`1.0.1`

AudioMate 是面向游戏音频项目的 Wwise AI 助手桌面应用。它也支持个人知识库、Skill、MCP 工具扩展、网页访问和本地文件读取，让团队规范、外部系统和常用流程都能进入同一个对话工作流。

## 核心能力

- 用自然语言查询、分析和操作 Wwise 工程对象。
- 分析当前选中对象或工程源文件的响度、频段、路由增益和风险项。
- 上传项目规范、音频设计文档、表格、PDF、Word、Excel、PPT 等资料作为知识库。
- 通过 Skill 固化团队工作流、检查清单、任务规则和 Agent 行为。
- 通过 MCP 接入外部系统；支持多个 MCP 配置同时启用，并按优先级顺序调用工具。
- 读取网页、飞书/Lark 文档等外部内容，结合 Wwise 工程上下文回答问题。
- 在 Ask Mode 中保持只读，在 Agent Mode 中执行需要修改工程或文件的任务。


## 使用前准备

### 准备 Wwise

1. 打开你的 Wwise 工程。
2. 确认 Wwise 已启用 WAAPI，并允许本机连接。
3. 默认 WAAPI 端口为 `8080`。

如果 AudioMate 显示无法连接，通常是 Wwise 未启动、WAAPI 未开启，或本机端口被防火墙、安全软件、代理工具拦截。

### 准备模型密钥

AudioMate 使用兼容 OpenAI 接口的模型服务。首次使用前需要在应用内保存：

- `Base URL`：模型服务地址。
- `API Key`：访问密钥。

打开 `Settings` > `令牌密钥`，填写后点击 `保存密钥`。不要把真实密钥发给他人，也不要写入公开文档、截图或 Skill 内容。

## 启动 AudioMate

### 使用发布包

如果你拿到的是发布包，进入发布目录后双击 `AudioMate.exe` 即可启动。

### 使用安装包
如果你拿到的是安装包，双击安装按照流程进行安装即可


## 主界面说明

<img width="1152" height="882" alt="对话" src="https://github.com/user-attachments/assets/1e0ecaad-2ef7-462b-94ae-1a80098c556e" />

### 左侧 Workspace

- `New Chat`：开始新对话。
- 历史列表：切换之前的对话记录。
- `Knowledge`：管理个人知识库。
- `定时任务`：定期执行AudioMate任务。
- `Settings`：配置账户、密钥、Skill、MCP 等。
- 左上角菜单按钮：折叠或展开侧边栏。

### 顶部状态栏

- `Wwise` 状态：显示当前是否连接到 Wwise。
- `Connect`：连接或断开 Wwise。
- `Mode`：切换 `Ask Mode` 和 `Agent Mode`。
- `Theme`：切换浅色或深色主题。
- 反馈入口：打开反馈二维码，并可打开本地日志目录。

### 底部输入区

- 文本框：输入你想让 AudioMate 完成的任务。
- 模型选择器：选择本轮使用的模型。
- 知识库选择器：选择要参考的个人知识库。
- Skill 选择器：选择 `Auto Skill` 自动匹配，或固定加载某个已启用 Skill。
- 语音按钮：调用 Windows 语音输入能力。
- 发送按钮：提交当前消息。

输入框支持拖入或粘贴图片、文件路径和本地文件。AudioMate 会在对话中把这些内容作为上下文使用。

## 两种工作模式

### Ask Mode

Ask Mode 适合查询、解释、分析和生成建议。它允许自动执行只读操作，但会阻止写入 Wwise 工程或本地文件的操作。

适合的问题：

- “帮我列出当前选中对象，并总结开发规律。”
- “分析当前选中音频的响度，评价频段，告诉我哪些可能过响。”
- “解释这个 Sound SFX 的路由和关键属性。”

### Agent Mode

Agent Mode 适合需要改动项目数据的任务。它可以执行更完整的自动化流程。涉及写入、覆盖文件或修改 Wwise 工程时，请先检查确认界面中的操作内容。

适合的问题：

- “把当前选中 Sound 经完整路由后的响度统一控制到 -18 LUFS-I 附近。”
- “为这些 Footstep 随机化 Pitch，范围控制在 -50 到 50 cents。”
- “根据这份表格批量整理对象备注和命名。”

建议先在 Ask Mode 中让 AudioMate 解释计划，再切到 Agent Mode 执行实际修改。

## 典型使用流程

### 连接 Wwise 并提问

1. 打开 Wwise 工程。
2. 启动 AudioMate。
3. 点击顶部 `Connect`。
4. 在 Wwise 中选中你要处理的对象。
5. 在 AudioMate 输入任务，例如：

```text
分析当前选中对象下所有源文件的响度，并按风险从高到低列出结果。
```

### 使用知识库

<img width="1152" height="882" alt="知识库" src="https://github.com/user-attachments/assets/c843f266-5ca7-48cb-bf56-7cee1986ce0e" />

1. 点击左侧 `Knowledge`。
2. 点击 `新建知识库`，输入名称。
3. 点击 `上传文档`，选择 `TXT`、`MD`、`PDF`、`Word`、`Excel`、`PPT` 等文件。
4. 回到聊天页，在底部知识库选择器中选择该知识库。
5. 提问时说明你希望参考资料，例如：

```text
参考项目音频规范，检查当前选中对象的命名和响度是否符合要求。
```

<img width="1152" height="882" alt="设置" src="https://github.com/user-attachments/assets/245dd5bb-e01d-4f52-a77b-be479d83563a" />

### 使用 Skill

Skill 用来定义 Agent 的专门能力和行为。适合把团队常用流程、检查清单或自动化规则打包成可复用能力。

1. 打开 `Settings`。
2. 在 `Skill（技能）` 区域点击 `新增 Skill`。
3. 选择本地 Skill 目录。
4. 启用导入后的 Skill。
5. 回到聊天页，在 Skill 选择器中保持 `Auto Skill`，或手动指定某个 Skill。

Skill 可以来自本地目录，也可以来自 Skill Hub。通过浏览器中的 Skill Hub 点击“一键 AudioMate”时，系统会通过 `audiomate://` 协议把 Skill 发送到当前 AudioMate 窗口。若 AudioMate 是被冷启动打开的，需要回到浏览器再点击一次导入按钮。

### 使用 MCP

MCP 配置用于连接外部工具或团队系统。当前版本支持多个 MCP 配置同时保存，并通过滑块自由启用或关闭。

1. 打开 `Settings`。
2. 在 `MCP 配置` 中点击 `新建配置`。
3. 填写配置名称。
4. 粘贴 MCP JSON 配置。
5. 点击 `保存配置`。新保存的配置默认启用。
6. 使用配置列表中的滑块启用或停用某个 MCP。
7. 使用上移、下移按钮调整优先级；启用配置会按列表顺序参与工具发现和调用。

当多个启用 MCP 暴露同名工具时，AudioMate 默认使用优先级更高的配置。内部工具调用也支持通过 `config_name` 精确指定某个 MCP 配置。

示例结构：

```json
{
  "transport": "streamable_http",
  "url": "http://127.0.0.1:8000/mcp",
  "headers": {}
}
```

也支持 `mcpServers` 包装形式，例如：

```json
{
  "mcpServers": {
    "paper-lark-mcp": {
      "url": "https://example.com/mcp",
      "headers": {
        "AUTH_TYPE": "UAT",
        "AUTH_TOKEN": "your-token"
      }
    }
  }
}
```

历史配置如果没有 `enabled` 字段，升级后会默认关闭，避免旧配置在用户不知情的情况下自动接入外部系统。

## 数据与安全建议

- 修改 Wwise 项目前，建议先保存工程或使用版本管理。
- 对写操作保持确认习惯，尤其是批量修改、导入、删除、覆盖文件等任务。
- Ask Mode 默认限制写操作，适合探索、检查和生成计划。
- 不要在聊天、知识库、Skill 或 MCP 配置中放入不该暴露的密钥、账号密码或内部凭证。
- 本地文件授权后，AudioMate 才能读取相关文件内容；大文件可能会被截断处理。
- MCP 会把外部工具接入对话流程，只启用你信任的配置，并定期清理不再使用的服务。
- 反馈问题时可以附上截图和日志，但提交前请确认日志中没有敏感信息。

## 常见问题

### 无法连接 Wwise

- 确认 Wwise 正在运行。
- 确认 Wwise 的 WAAPI 已启用。
- 确认本机 `127.0.0.1:8080` 未被防火墙或其他程序阻断。
- 重新点击 `Connect`，必要时重启 Wwise 和 AudioMate。

### 模型没有响应或提示鉴权失败

- 打开 `Settings` > `令牌密钥`，检查 `Base URL` 和 `API Key`。
- 确认密钥仍有效，且模型服务支持当前选择的模型。
- 切换到另一个模型再试。

### 知识库没有被参考

- 确认底部知识库选择器已选中目标知识库。
- 确认文档已上传到该知识库。
- 如果问题非常具体，可以在提问中明确“参考当前知识库”。

### MCP 工具没有生效

- 打开 `Settings` > `MCP 配置`，确认对应配置的滑块已启用。
- 确认启用配置排在期望的优先级顺序。
- 确认 MCP 服务地址、命令、鉴权头或环境变量有效。
- 如果多个 MCP 有同名工具，优先级靠前的配置会先被调用。

### Agent Mode 没有执行修改

- 确认当前模式是 `Agent Mode`。
- 确认 Wwise 已连接。
- 查看是否有确认卡片、权限提示或错误信息需要处理。
- 如果任务描述含糊，可先让 AudioMate 生成计划，再要求执行。

### 如何查看日志

- 打开主界面反馈入口。
- 点击 `打开日志目录`。
- 日志默认写入项目或应用数据目录下的 `logs/audiomate.log`。

## 更新与反馈

在 `Settings` 中可以查看账户、检查更新、打开发布页。主界面提供反馈入口；遇到连接、模型、知识库、Skill、MCP 或自动化执行问题时，可以附上问题描述、必要截图和日志文件。
