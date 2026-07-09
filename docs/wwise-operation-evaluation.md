# AudioMate Wwise 操作正确率与复杂系统评测

本文档用于说明如何评测 AudioMate 对 Wwise 工程的操作是否正确、稳定，以及它搭建复杂声音系统时的实现程度。

这里的“正确率”不只指代码是否能执行成功，还包括：是否理解用户意图、是否选择正确 WAAPI 调用、是否只修改目标对象、是否能复用已有结构、是否搭出了可继续制作的 Wwise 系统。

## 1. 评测分层

建议把评测拆成三层：

| 层级 | 目标 | 典型问题 | 推荐方法 |
|---|---|---|---|
| L1：模型行为正确率 | 判断 AudioMate 是否会选对工具和 API | 是否生成 `python_waapi`，是否使用正确 URI，是否避开不存在的 API | `golden_tasks` 多轮评测 |
| L2：真实工程操作正确率 | 判断 Wwise 工程是否真的被正确修改 | 对象是否创建在正确位置，属性和引用是否写对，Ask Mode 是否无写入 | 测试工程 + WAAPI post-condition |
| L3：复杂系统实现程度 | 判断搭建结果是否像一个可用系统，而不是一堆对象 | HDR / NPC / 环境音 / 武器 / UI 系统是否完整、可扩展、可接入游戏 | 系统验收矩阵 + 自动查询 + 人工复核 |

## 2. L1：模型行为正确率

项目已经包含 golden task 评测入口：

```powershell
python scripts/run_golden_tasks.py --system-prompt full --runs 3 --threshold 0.8 --report reports\golden-full.json
```

重点看这些指标：

- `tool_match`：是否用了正确执行路径，例如 `python_waapi` 或结构化 WAAPI 工具。
- `signal_recall`：是否包含期望 API、属性、helper 或路径策略。
- `forbidden_avoidance`：是否避开不存在、高风险或项目禁止的 API。
- `pass_rate`：整体通过率。
- 多轮方差：同一任务跑 3 到 5 次，观察是否稳定。

建议把复杂系统也加入 `golden_tasks.json`，但 L1 只检查“计划和代码意图”，不要把它当成最终系统验收。

## 3. L2：真实工程操作正确率

真实 Wwise 操作要用沙盒工程验证，不要在生产工程上做回归测试。

推荐流程：

1. 准备一个专门测试用 Wwise 工程。
2. 每次测试前复制一份干净工程。
3. 打开 Wwise 并启用 WAAPI。
4. 让 AudioMate 执行任务。
5. 执行后用 WAAPI 查询工程状态。
6. 对比任务定义里的 post-condition。
7. 记录新增、修改、删除对象的 diff。

单步操作的 post-condition 示例：

```json
{
  "id": "create_combat_actor_mixer",
  "query": "在 Default Work Unit 下创建 Combat Actor-Mixer",
  "postcondition": {
    "path_exists": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Combat",
    "type": "ActorMixer"
  },
  "forbidden_changes": [
    "delete_object",
    "rename_unrelated_object"
  ]
}
```

应该重点统计：

- 任务成功率：post-condition 全部满足的比例。
- 误写率：不该写时发生写入的比例，尤其 Ask Mode。
- 越权率：修改了用户没有选中、没有指定、没有确认的对象。
- 幂等性：重复执行是否造成重复对象、重复 Event、重复绑定。
- 自我修正率：WAAPI 参数错误、对象不存在、连接中断时，是否能修正或安全停止。
- 版本兼容率：不同 Wwise 版本下路径、schema、对象类型差异是否被正确处理。

## 4. L3：复杂系统实现程度

复杂系统不能只看“对象有没有创建”，而要看它是否形成了可继续制作、可接入游戏、可扩展、可维护的 Wwise 设计。

建议采用 100 分制：

| 维度 | 分值 | 评测内容 |
|---|---:|---|
| 结构完整度 | 20 | 是否创建合理的 Actor-Mixer / Container / Event / Bus 层级；是否覆盖核心模块 |
| 控制入口完整度 | 20 | 是否有必要的 RTPC、State、Switch、Game Parameter、Event 命名和绑定关系 |
| 运行时接入准备 | 15 | 是否能清楚说明游戏侧需要传什么参数、何时 PostEvent、何时 SetState/SetSwitch/SetRTPC |
| 路由与混音安全 | 15 | 是否路由到正确 Bus；是否设置基础 Volume、Priority、Virtual Voice、Ducking 或发送关系 |
| 可扩展性 | 10 | 是否能继续添加新角色、新武器、新区域、新 UI 类型，而不用重构整套结构 |
| 幂等与安全 | 10 | 是否复用已有对象、不覆盖、不删除、不制造重复结构 |
| 可观测与验收 | 10 | 是否输出清晰报告、对象清单、未完成项、人工试听清单和后续制作建议 |

推荐等级：

| 等级 | 分数 | 含义 |
|---|---:|---|
| A | 90-100 | 可作为团队模板沉淀成 Skill |
| B | 75-89 | 可用于项目第一版骨架，需要少量人工补齐 |
| C | 60-74 | 有核心结构，但控制入口或路由不完整 |
| D | 40-59 | 只创建了零散对象，还不像一个系统 |
| F | 0-39 | 误解需求、误写工程或缺少关键安全边界 |

## 5. 各类系统的验收重点

### HDR / 动态混音

必须检查：

- 是否区分高优先级、普通优先级和背景层。
- 关键声音是否有 Priority / Virtual Voice 策略。
- 是否设计战斗强度、距离、镜头关注度等 RTPC。
- UI、武器、爆炸、环境床是否进入合理 Bus。
- 是否给出“哪些声音应该压低、哪些声音不能被压低”的规则。

### NPC 声音系统

必须检查：

- 是否按 NPC 类型、行为模块和素材用途分层。
- Footstep / Foley / Voice / Damage / Death / Ability 是否有清楚入口。
- Surface、Alert、Faction、Distance 等 Switch / State / RTPC 是否齐全。
- Event 命名是否能直接被程序侧理解。
- 新增 NPC 类型时是否只需扩展分支，不需要改旧结构。

### 环境音系统

必须检查：

- 是否支持区域、天气、昼夜、室内外、随机点声源。
- 循环床、随机声、远景声、瞬态点声是否分层。
- Weather / Area / TimeOfDay / Intensity 等参数是否明确。
- Ambience Bus、AuxBus、混响发送是否有基础设计。
- 是否能说明游戏侧区域切换和天气切换需要传什么。

### 武器系统

必须检查：

- Fire、Tail、Mechanical、Reload、DryFire、Equip、Impact 是否分层。
- 第一人称、第三人称、远距离尾音是否区分。
- WeaponType、FireMode、Surface、AmmoState、IndoorOutdoor、Distance 是否有控制入口。
- 武器主声、尾音、机械层、命中层是否路由到正确 Bus。
- 是否能继续添加新枪型和新材质，而不破坏旧事件。

### UI 声音系统

必须检查：

- Navigation、Confirm、Cancel、Popup、Inventory、Reward、Warning、System 是否覆盖。
- UI Bus 是否独立，是否有足够优先级。
- UIContext、MenuLayer、Rarity、FocusLevel 等控制入口是否合理。
- 战斗中 UI 是否不会被环境或武器完全盖住。
- 命名是否适合 UI 程序直接调用。

## 6. 自动化评测建议

复杂系统评测可以由两部分组成：

1. **自动查询**：用 WAAPI 查询对象图、引用、属性、Event、Bus 路由、RTPC/State/Switch 列表。
2. **人工复核**：检查系统意图、听感、玩法接入和团队规范。

自动报告至少应包含：

- 本次任务的用户需求。
- AudioMate 生成的计划。
- 实际 WAAPI 写入列表。
- 新增对象、复用对象、修改对象。
- 满足的验收项。
- 缺失的验收项。
- 可能误写或重复的对象。
- 建议人工试听的 Event 列表。

复杂系统的最终结论不建议只写“通过/失败”，而应写成：

```text
NPC 声音系统实现程度：82/100，等级 B
- 结构完整度：18/20
- 控制入口完整度：17/20
- 运行时接入准备：12/15
- 路由与混音安全：11/15
- 可扩展性：9/10
- 幂等与安全：8/10
- 可观测与验收：7/10
主要缺口：缺少 Faction Switch，Voice 子系统没有 Alert State 绑定说明。
```

## 7. 建议

可以先提供：

- `golden_tasks`：覆盖常见单步 WAAPI 行为和复杂系统规划。
- `live regression` 文档：说明如何连接测试 Wwise 工程进行真实验收。
- `system acceptance checklist`：HDR / NPC / 环境音 / 武器 / UI 的评分矩阵。
- 示例报告：只使用虚构项目和虚构对象名，不提交真实商业项目结构。

不要把真实项目的 Wwise 工程、内部命名规范、生产素材路径、客户需求文档或未授权官方文档正文提交到公开仓库。
