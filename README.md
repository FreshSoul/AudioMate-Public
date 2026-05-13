<img width="1254" height="1254" alt="AudioMate" src="https://github.com/user-attachments/assets/1030fde8-5d59-42a2-8bfc-4f073e7725a7" />

# AudioMate

当前版本：`1.1.0`

AudioMate 是面向游戏音频项目的 Wwise AI 助手桌面应用。它也支持个人知识库、Skill、Plugin、MCP 工具扩展、网页访问和本地文件读取，让团队规范、外部系统、DAW 和常用流程都能进入同一个对话工作流。

## 核心能力

- 用自然语言查询、分析和操作 Wwise 工程对象。
- 分析当前选中对象或工程源文件的响度、频段、路由增益和风险项。
- 上传项目规范、音频设计文档、表格、PDF、Word、Excel、PPT 等资料作为知识库。
- 通过 Skill 固化团队工作流、检查清单、任务规则和 Agent 行为。
- 通过 Plugin 把 REAPER、内部工具、渲染脚本、资产系统等外部能力注册成 Agent 可调用工具。
- 通过 AudioMate Market 浏览、搜索并一键安装 Skill 和 Plugin，把团队经验和自动化能力快速带到本机。
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
- `Market` / 拼图按钮：打开 AudioMate Market，安装 Skill 和 Plugin。
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

### 使用 AudioMate Market

AudioMate Market 是桌面端内置的扩展中心。你可以在同一个页面搜索 `插件` 和 `技能`，看到远程 Hub 上已经发布的能力，并用 `+` 一键安装到本机。已安装的条目会显示为 `✓`，避免重复导入。

Market 适合这些场景：

- 想快速获得一套成熟的 Wwise 检查流程，而不是从空白提示词开始写。
- 想把 REAPER、批量渲染、音频编辑、内部资产系统等能力交给 Agent 调用。
- 想让团队成员使用同一套经过验证的 Skill 和 Plugin，减少口口相传和手动配置。
- 想在新机器上快速恢复常用工作流，打开市场、搜索、点击安装即可。

使用步骤：

1. 点击聊天页右侧的拼图按钮，或从左侧入口打开 `Market`。
2. 在顶部切换 `插件` 或 `技能`。
3. 使用搜索框按名称、描述或分类查找目标能力。
4. 点击卡片右侧 `+` 安装；远程 Plugin 安装前会提示来源和 Plugin ID，请确认来源可信。
5. 安装完成后，Skill 会出现在聊天页 Skill 选择器和 Settings 的 Skill 列表中；Plugin 会出现在 Settings 的 Plugin 列表中，并自动注册可调用 Tool。

如果市场暂时无法连接，AudioMate 会优先显示上次成功加载的缓存内容，并提供刷新入口。默认 Hub 地址为 `https://audiomate.art`，团队也可以在配置中使用自己的 Hub。

### 使用 Skill

Skill 用来定义 Agent 的专门能力和行为。适合把团队常用流程、检查清单或自动化规则打包成可复用能力。

1. 打开 `Settings`。
2. 在 `Skill（技能）` 区域点击 `新增 Skill`。
3. 选择本地 Skill 目录。
4. 启用导入后的 Skill。
5. 回到聊天页，在 Skill 选择器中保持 `Auto Skill`，或手动指定某个 Skill。

Skill 可以来自本地目录，也可以来自 Market / Skill Hub。通过浏览器中的 Skill Hub 点击“一键 AudioMate”时，系统会通过 `audiomate://install-skill` 协议把 Skill 发送到当前 AudioMate 窗口。若 AudioMate 是被冷启动打开的，需要回到浏览器再点击一次导入按钮。

好用的 Skill 往往不只是提示词，而是把“谁来做、按什么步骤检查、输出什么格式、什么操作必须先确认”写清楚。团队可以把一次成功的 QA、响度检查、命名审核或交付报告流程沉淀成 Skill，下一次直接复用。

### 使用 Plugin

Plugin 是 AudioMate 的可执行扩展。和 Skill 偏向“工作方法”不同，Plugin 会把本地 Python 插件加载到 AudioMate 中，并注册成 Agent 可以调用的 Tool。它适合连接外部软件、自动化脚本、内部服务或团队工具链。

Plugin 能带来的价值：

- 让 AudioMate 不只会“分析和建议”，还可以调用团队已有工具完成实际步骤。
- 把复杂脚本封装成自然语言可用的能力，用户不用记参数和命令。
- 让 Agent 同时理解 Wwise 上下文、知识库资料和外部工具返回结果，适合跨软件排查。
- 通过 `read_only` 标记区分只读工具和写入工具，方便在 Ask Mode 与 Agent Mode 中保持边界。

本地导入 Plugin：

1. 打开 `Settings`。
2. 进入 `Plugin（插件）`。
3. 点击 `＋ 新增 Plugin`，选择包含 `plugin.json` 的插件目录。
4. 导入后确认状态为 `registered`，并检查 Tool 数量。
5. 需要临时停用时，关闭该 Plugin 的开关；修改插件文件后可点击重载。

从 Market 安装 Plugin：

1. 打开 `Market`，切换到 `插件`。
2. 搜索目标 Plugin。
3. 点击 `+`，确认来源可信后安装。
4. 安装成功后，Plugin 会自动启用并注册 Tool。

Agent 在需要时会看到当前已启用的 Plugin Tool，并可以在生成代码中通过 `call_plugin_tool("plugin.<plugin-id>.<tool-name>", {...})` 调用。普通用户通常不需要手写这段代码，只要用自然语言描述目标即可，例如：

```text
检查 REAPER 是否已连接，然后列出当前工程轨道，并把选中轨道的音量调整到 -6 dB。
```

远程 Plugin 本质上会在本机加载 Python 代码。只从可信 Hub 或可信团队成员处安装；不要安装来源不明、要求敏感权限或说明不清楚的插件。

### REAPER Control Plugin

市场内置的 Reaper Control Plugin 可以把 AudioMate 连接到 Cockos REAPER，让 Agent 在 Wwise 工作流之外继续处理 DAW 里的工程、轨道和渲染任务。

它可以帮助你：

- 检查 REAPER bridge 连接状态，读取工程路径、播放状态、tempo、拍号和轨道信息。
- 控制播放、暂停、停止、录音、循环和光标位置。
- 列出和修改轨道名称、音量、声像、静音、独奏、录音准备、颜色和选中状态。
- 管理 media item、take、MIDI、FX、marker、region、track routing、envelope 和 automation item。
- 执行 REAPER Action，按当前或指定渲染设置触发渲染。
- 读取和设置工程设置、渲染目录、渲染命名、metadata、ExtState，并保存工程。

首次配置建议使用 Market 中的 `配置` 按钮：

1. 打开 `Market`，找到 `Reaper Control`。
2. 点击卡片上的 `配置`。
3. AudioMate 会检测 REAPER 资源目录、`reaper.ini`、随包 Python runtime、`reapy` 和 bootstrap 脚本。
4. 确认后，AudioMate 会备份 `reaper.ini`，写入推荐 Python 配置，并安装 `Scripts/AudioMate/audiomate_reapy_bootstrap.py`。
5. 重启 REAPER。
6. 在 REAPER 的 Action List 中运行 `AudioMate/audiomate_reapy_bootstrap.py` 一次。
7. 回到 AudioMate，让 Agent 检查 REAPER 连接状态。

示例提问：

```text
连接 REAPER，读取当前工程轨道列表，帮我找出静音轨道、独奏轨道和带 FX 的轨道。
```

```text
把 REAPER 当前选中轨道命名为 Dialogue Preview，音量设为 -6 dB，然后按当前渲染设置执行一次渲染。
```

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
- 不要在聊天、知识库、Skill、Plugin 或 MCP 配置中放入不该暴露的密钥、账号密码或内部凭证。
- 本地文件授权后，AudioMate 才能读取相关文件内容；大文件可能会被截断处理。
- Plugin 会在本机加载代码并可能连接外部软件；只安装可信来源，并在安装远程 Plugin 前检查确认弹窗中的 Hub 和 Plugin ID。
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

### Market 无法加载

- 确认网络可以访问当前 Hub，默认地址为 `https://audiomate.art`。
- 点击 Market 中的 `刷新` 重试。
- 如果提示正在显示缓存内容，说明上次成功加载的目录仍可浏览，但新的安装可能需要等网络恢复。
- 团队自建 Hub 时，确认配置的 Hub 地址可以返回 `/api/bootstrap`。

### Plugin 没有生效

- 打开 `Settings` > `Plugin（插件）`，确认插件开关已启用。
- 查看状态是否为 `registered`；如果是 `failed`，查看错误信息，常见原因是缺少 `plugin.json`、入口文件不存在或入口路径非法。
- 修改 Plugin 文件后，点击重载按钮让 AudioMate 重新注册 Tool。
- 远程安装失败时，确认 Hub 可访问，且 Plugin 包没有缺少 `plugin.json` 或 `plugin.py`。

### REAPER Control 无法连接

- 确认 REAPER 已启动。
- 确认已在 Market 的 Reaper Control 卡片中完成 `配置`。
- 重启 REAPER 后，在 Action List 中运行过 `AudioMate/audiomate_reapy_bootstrap.py`。
- 再让 AudioMate 调用 REAPER 连接检查；如果仍失败，检查 REAPER Python / reapy bridge 配置。

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

在 `Settings` 中可以查看账户、检查更新、打开发布页。主界面提供反馈入口；遇到连接、模型、知识库、Market、Skill、Plugin、MCP 或自动化执行问题时，可以附上问题描述、必要截图和日志文件。
