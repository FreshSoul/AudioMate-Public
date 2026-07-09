# Reaper Control Plugin

通过 ReaScript Python bridge，让 AudioMate 控制 Cockos REAPER。

这个插件会注册一组本地工具，用来检查和修改当前 REAPER 工程：播放状态、轨道、媒体 item、take、FX、marker、region、MIDI 事件、envelope、路由、渲染设置，以及部分低层 ReaScript API 调用。

## 环境要求

- AudioMate 已启用本地插件支持。
- 同一台机器上已安装 Cockos REAPER。
- REAPER Python bridge 可用，通常由 `reapy` 提供。
- 打包版本中，REAPER Python runtime 通常由 `scripts/prepare_reaper_runtime.py` 在构建时生成，并随发布包放在 `runtime/reaper-python`、`resources/reaper-python`，或由 `AUDIOMATE_REAPER_PYTHON_DIR` 指定。

## 安装

1. 打开 AudioMate。
2. 打开 Extension Center 或插件管理页面。
3. 导入本目录：`plugins/reaper-control-plugin`。
4. 确认插件状态为 `registered`。
5. 用下面的调用验证 bridge：

```python
call_plugin_tool("plugin.reaper-control.check-connection", {})
```

## 配置 REAPER

推荐使用 AudioMate 内置的 REAPER 配置流程。它会在写入配置前检查 REAPER 资源目录、`reaper.ini`、Python runtime、`reapy` 和 bootstrap 脚本。

手动配置流程：

1. 将 `python-reapy` 安装到 REAPER 将要加载的 Python runtime 中。
2. 在 REAPER Preferences 中启用 ReaScript Python，并指向匹配的 Python 目录和 `pythonXX.dll`。
3. 运行一次 ReaScript bootstrap：

```python
import reapy

reapy.config.enable_dist_api()
```

4. 重启 REAPER，并调用 `plugin.reaper-control.check-connection`。

AudioMate 会把 manifest 中的工具名规范化为短横线命名，所以 `check_connection` 会注册为 `plugin.reaper-control.check-connection`。

REAPER 会把 `pythonlibdll` 加载进自身进程，因此冻结后的 AudioMate Python runtime 不能替代独立的可嵌入 CPython runtime。

## 工具概览

只读工具：

- `check-connection`
- `project-info`
- `list-tracks`
- `markers-regions`
- `media-sources`

会修改工程或状态的工具：

- `transport`
- `set-track`
- `execute-action`
- `render`
- `write-midi`
- `create-track`
- `media-items`
- `takes`
- `track-fx`
- `project-markers`
- `project-settings`
- `ext-state`
- `track-routing`
- `envelopes`
- `midi-events`
- `reaper-session`
- `call-api`

调用示例：

```python
call_plugin_tool("plugin.reaper-control.transport", {"action": "play"})
call_plugin_tool("plugin.reaper-control.project-info", {"include_tracks": True})
call_plugin_tool("plugin.reaper-control.list-tracks", {})
call_plugin_tool("plugin.reaper-control.set-track", {"index": 0, "mute": True})
call_plugin_tool("plugin.reaper-control.execute-action", {"command_id": 40026})
call_plugin_tool("plugin.reaper-control.render", {"mode": "recent"})
call_plugin_tool("plugin.reaper-control.write-midi", {"notes": "C4 E4 G4 C5"})
```

## 安全说明

很多工具都可以修改当前 REAPER 工程。检查工程时优先使用只读工具；调用 `set-track`、`media-items`、`project-settings`、`render` 或 `call-api` 等写操作前，请先保存或备份工程。

`call-api` 能力很强。优先使用上面已经封装好的类型化工具；只有在需要调用尚未封装的 ReaScript 函数时，再使用 `call-api`。
