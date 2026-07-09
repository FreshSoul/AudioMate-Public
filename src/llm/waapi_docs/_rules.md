# WAAPI 关键规则

> 公开维护说明：
> 本文件是 AudioMate 人工维护的 WAAPI 高优先级规则摘要，会被稳定注入 LLM system prompt。
> 内容只包含通用 API 使用边界、可复用实践建议和根据公开接口名称整理的防错规则。
> 不要在这里粘贴 Audiokinetic 官方文档正文、SDK CHM 片段、客户资料、密钥、内网 URL 或个人路径。

## 开源版知识边界

- 本仓库不再分发从 Audiokinetic Public Library、Wwise Help 或 SDK 文档同步/摘录的正文。
- 具体参数、返回结构和版本差异以用户本机 Wwise 的 `ak.wwise.waapi.getSchema`、`ak.wwise.waapi.getFunctions`、`ak.wwise.waapi.getTopics` 以及 Audiokinetic 官方文档为准。
- 如果规则和实时 schema 冲突，优先相信实时 schema。
- 如果 API 形状不确定，先查询 schema，不要凭经验补字段。

## 基础交互边界

1. `ak.wwise.core.*` 主要面向 Authoring/project/object/import/query 操作。
2. `ak.wwise.ui.*` 主要面向 UI 状态、选择、视图、命令和编辑器交互。
3. `ak.soundengine.*` 主要面向 runtime/game-object/event/RTPC/state/switch 控制。
4. 不要把 `ak.soundengine.*` 当作工程对象修改 API。
5. Topic subscription 用于接收变化通知；不要用无限轮询模拟订阅。

## 读写安全

1. 常见读取类 API：`ak.wwise.core.object.get`、`ak.wwise.core.object.getPropertyAndReferenceNames`、`ak.wwise.waapi.getSchema`、`ak.wwise.waapi.getFunctions`、`ak.wwise.waapi.getTopics`、`ak.wwise.core.ping`、`ak.wwise.debug.validateCall`。
2. 常见写入/状态改变类 API：`ak.wwise.core.object.create`、`ak.wwise.core.object.set`、`ak.wwise.core.object.setProperty`、`ak.wwise.core.object.delete`、`ak.wwise.ui.commands.execute`、`ak.soundengine.postEvent`、`ak.soundengine.setRTPCValue`、`ak.soundengine.setState`、`ak.soundengine.setSwitch`。
3. Ask Mode 下不要生成写入工程、写入文件、运行 shell 或修改 runtime 状态的代码。
4. Agent Mode 下执行写入前，先读目标对象并说明计划；写入后重新读取验证。
5. 不要手动调用 `ak.wwise.core.undo.beginGroup` / `ak.wwise.core.undo.endGroup`；AudioMate 的执行管线负责 undo 分组。

## Schema-first 规则

1. 对不确定的 URI、参数、options 或返回字段，先调用 `ak.wwise.waapi.getSchema`。
2. 对可用函数/Topic 不确定时，先调用 `ak.wwise.waapi.getFunctions` 或 `ak.wwise.waapi.getTopics`。
3. 调试调用形状时，可以使用 `ak.wwise.debug.validateCall`。
4. 生成代码时不要发明看起来合理但未经验证的 URI。
5. 不要使用已知幻觉 URI：`ak.wwise.core.object.addStateGroup`、`ak.wwise.core.object.setStatePropValue`、`ak.wwise.core.object.setRTPCBinding`。

## Object 查询规则

1. `ak.wwise.core.object.get` 的 `from` 和 `transform` 放在 args 对象中。
2. `return`、`platform`、`language` 放在 options 对象中。
3. 调用形状使用 `waapi_client.call(uri, args, options)`。
4. 不要把 `options` 嵌套进 `args`。
5. `transform` 步骤按顺序执行；优先使用 `select`、`where`、`range` 这类清晰步骤。
6. 返回字段只请求当前任务需要的最小集合。
7. 对源文件路径，优先查询 AudioFileSource 子对象并请求 `originalFilePath`；不要写 `@originalFilePath`。

## 路径和对象引用

1. 不要猜绝对路径、GUID、Short ID 或工程根层级。
2. 使用当前选中对象、名称查询或类型查询解析真实对象，再复用返回的 id/path。
3. 新版 Wwise 中总线、容器、层级命名可能与旧教程不同；先查询项目实际对象。
4. 对 `type:name` 这样的引用，先确认对象存在；不存在时创建或告知用户。
5. 创建 Attenuation、Event、Sound、Bus、AuxBus 等对象时，先确认合法父层级。

## 属性和引用名

1. 不确定任何 `@PropertyName` 或引用名时，必须先调用 `ak.wwise.core.object.getPropertyAndReferenceNames`。
2. 适用范围包括 `object.set`、`setProperty`、`setReference`、RTPC 的 `@PropertyName`，以及任何带 `@` 前缀的字段。
3. 如果查询结果不包含目标属性/引用名，不要用猜测名称继续写入。
4. 不要猜 `classId`、插件 ID 或内部对象类型编号。
5. 对 Output Bus、Attenuation、Effect 等对象引用，优先使用 `ak.wwise.core.object.setReference` 或经 schema 验证的对象结构。

## 常见建模规则

1. `ak.wwise.core.object.create` 用于创建新对象；它有 `parent`。
2. `ak.wwise.core.object.set` 用于修改已有对象；不要给它传错误的 `parent`。
3. `onNameConflict`、`listMode`、`platform` 等顶层控制字段不要放进 `children`。
4. `WorkUnit` 和 `Folder` 是组织容器，不要对它们设置音频属性。
5. `Sound` 通常是叶节点，不要把子对象挂在 Sound 下。
6. Bus / AuxBus 的路由主要由总线层级父子关系决定；不要把普通对象的 Output Bus 规则套到 Bus 对象本身。
7. Attenuation 距离规则通常通过曲线点控制；不确定字段时查询 schema。
8. Event Action 创建和 Target 引用必须使用 schema 验证后的结构。

## RTPC 与 State

1. State Group 关联对象时，优先查询当前 schema 中的正式 API 和字段。
2. 不要把 `stateGroup`、`state`、`property`、`value` 等猜测字段拼成不存在的调用。
3. 写 RTPC 前先确认目标对象属性名和 Game Parameter 对象。
4. RTPC 曲线、ControlInput、PropertyName 的结构必须由实时 schema 或已验证项目模式确认。

## 失败恢复

1. 如果 WAAPI 返回 unknown argument / unknown field，先查 schema，再修正调用形状。
2. 如果返回 object unknown，先查询或创建对象，不要继续写猜测路径。
3. 如果 WAAPI 暂不可用，先 `ak.wwise.core.ping` 或提示用户处理 Wwise 模态窗口/连接状态。
4. 如果本地离线知识不足，提示用户查看官方文档或允许运行时读取官方页面；不要在仓库中补入官方正文。
