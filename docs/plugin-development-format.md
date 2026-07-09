# AudioMate Plugin 开发格式规范

本文档定义 AudioMate Plugin 的目录结构、`plugin.json` manifest 格式、Python 入口约定、工具函数返回格式和发布检查清单。给其他开发者开发插件时，可以直接把这份规范作为交付标准。

## 目录结构

每个 Plugin 必须是一个独立目录，建议放在 `plugins/<plugin-id>-plugin/` 下。目录名使用小写字母、数字和短横线。

最小结构：

```text
plugins/example-plugin/
  plugin.json
  plugin.py
  README.md
  requirements.txt
```

文件说明：

- `plugin.json`：必需，声明插件元数据和工具列表。
- `plugin.py`：必需，Python 入口文件，文件名可以在 manifest 的 `entry` 字段中修改。
- `README.md`：必需，说明插件用途、安装配置、工具参数和调用示例。
- `requirements.txt`：可选，声明插件额外 Python 依赖；没有依赖时可留空。
- 其他资源文件：可选，必须放在插件目录内部，不能依赖插件目录外的相对路径。

## plugin.json 格式

`plugin.json` 必须是 UTF-8 JSON 对象。推荐字段如下：

```json
{
  "id": "example-plugin",
  "name": "Example Plugin",
  "version": "1.0.0",
  "description": "Describe what this plugin lets AudioMate do.",
  "entry": "plugin.py",
  "tools": [
    {
      "name": "get_status",
      "description": "Read current status from the target application or service.",
      "function": "get_status",
      "read_only": true
    },
    {
      "name": "set_value",
      "description": "Update a value in the target application or service.",
      "function": "set_value",
      "read_only": false
    }
  ]
}
```

字段规范：

| 字段 | 必需 | 类型 | 规范 |
| --- | --- | --- | --- |
| `id` | 推荐 | string | 插件稳定 ID，使用小写字母、数字和短横线，例如 `reaper-control`。缺省时 AudioMate 会按名称和目录生成 ID，但发布插件必须显式填写。 |
| `name` | 必需 | string | 用户可见名称，简短清晰。 |
| `version` | 推荐 | string | 语义化版本，例如 `1.0.0`。发布新包时必须递增。 |
| `description` | 推荐 | string | 一句话说明插件能力，不写内部实现细节。 |
| `entry` | 推荐 | string | Python 入口文件相对路径，默认 `plugin.py`；必须位于插件目录内，且必须是 `.py` 文件。 |
| `tools` | 推荐 | array | 工具声明列表。没有工具的插件可以导入，但不会给 Agent 暴露可调用能力。 |

工具字段规范：

| 字段 | 必需 | 类型 | 规范 |
| --- | --- | --- | --- |
| `name` | 必需 | string | 工具名，建议使用小写蛇形命名，例如 `project_info`。AudioMate 调用时会规范化为短横线，例如 `plugin.example-plugin.project-info`。 |
| `description` | 推荐 | string | 面向 Agent 的能力说明。写清楚读什么、改什么、何时使用，不要只写一个动词。 |
| `function` | 推荐 | string | `entry` 文件中实际调用的 Python 函数名。缺省时使用 `name`。 |
| `read_only` | 推荐 | boolean | 只读工具填 `true`；会写入、执行、删除、上传、渲染、发送请求或改变外部状态的工具必须填 `false`。 |

命名要求：

- `id`、目录名和工具名发布后不要随意改名，否则用户已有配置和快捷调用会失效。
- 工具名只表达动作和对象，例如 `list_tracks`、`set_track`、`render`。
- 不要用模糊名字，例如 `do_task`、`run`、`handle`。

## Python 入口约定

`entry` 文件中的工具函数必须是可导入的顶层函数。函数名要和 `plugin.json` 里对应工具的 `function` 一致。

推荐写法：

```python
from __future__ import annotations

from typing import Any


PLUGIN_VERSION = "1.0.0"


def get_status(**kwargs: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ready",
        "details": {},
    }


def set_value(name: str | None = None, value: Any = None, **kwargs: Any) -> dict[str, Any]:
    if not name:
        return {
            "ok": False,
            "error": "缺少 name 参数。",
        }
    return {
        "ok": True,
        "updated": {"name": name, "value": value},
    }
```

函数规范：

- 工具函数应返回可 JSON 序列化的数据：`dict`、`list`、`str`、`int`、`float`、`bool` 或 `None`。
- 推荐返回 `dict`，并包含 `ok: true/false`，方便 Agent 判断执行结果。
- 参数应使用清晰字段名，不要要求用户传复杂嵌套结构，除非工具本身确实需要。
- 对外部应用、文件系统、网络、DAW、Wwise、REAPER 等操作要做异常捕获，返回可读错误，而不是让原始 traceback 直接暴露给用户。
- 不要在 import 阶段连接外部服务或执行重操作；连接检查应放到工具函数内。

错误返回建议：

```python
{
    "ok": False,
    "error": "无法连接目标服务，请确认目标应用已启动。",
    "hint": "打开目标应用后重新调用 check_connection。",
}
```

成功返回建议：

```python
{
    "ok": True,
    "data": {
        "items": []
    },
    "message": "读取完成。"
}
```

## README.md 内容要求

`README.md` 面向使用者和审核者，至少包含：

- 插件用途：解决什么问题，连接什么外部应用或服务。
- 安装要求：需要哪些本地软件、端口、环境变量、账号或权限。
- 首次配置步骤：从空环境到可调用工具的步骤。
- 工具列表：每个工具的用途、是否只读、关键参数。
- 调用示例：至少给 2 到 3 个常用 JSON 参数示例。
- 安全边界：哪些操作会写文件、改工程、触发渲染、发送网络请求或改变外部状态。
- 排障：常见错误和解决方式。

## requirements.txt 规范

`requirements.txt` 只写插件额外依赖，不要重复写 AudioMate 主程序已经提供的标准库。

推荐：

```text
requests>=2.32,<3
```

不推荐：

```text
requests
some-package==latest
```

依赖要求：

- 优先使用稳定版本范围，避免完全不锁版本。
- 不要依赖需要管理员权限安装的系统组件，除非 README 明确说明。
- 不要在插件中自动安装依赖、修改系统 Python 或写入全局环境。

## 安全要求

插件不能包含以下内容：

- 明文密钥、账号密码、Token、Cookie 或内部服务器凭证。
- 未经用户明确授权的上传、删除、覆盖、批量修改或远程执行逻辑。
- 导入时自动执行外部命令、网络请求、文件删除或工程修改。
- 指向插件目录外部的入口文件或资源路径。
- 大型二进制文件、缓存、日志、临时文件、`__pycache__`、`.pyc`。

写入类工具必须：

- 在 `plugin.json` 中标记 `read_only: false`。
- 在 README 中说明会修改什么。
- 对危险参数做校验，例如路径、索引、ID、删除范围、输出目录。
- 返回明确的执行摘要，说明实际修改了什么。

## 本地开发流程

1. 在 `plugins/` 下创建插件目录。
2. 编写 `plugin.json`、`plugin.py`、`README.md` 和可选 `requirements.txt`。
3. 在 AudioMate 中打开 `Settings` 或 Market 的 Plugin 管理，选择插件目录导入。
4. 确认插件状态为 `registered`。
5. 用 `plugin.<plugin-id>.<tool-name>` 调用工具验证结果。
6. 修改后重新导入或刷新插件，再测试只读工具和写入工具。

调用名示例：

```text
plugin.example-plugin.get-status
plugin.example-plugin.set-value
```

`plugin.json` 中的 `get_status` 会被规范化为调用名里的 `get-status`。

## 测试清单

发布或提交给维护者前，开发者必须检查：

- `plugin.json` 是合法 JSON。
- `name`、`entry` 存在，`entry` 文件真实存在且是 `.py`。
- 每个工具的 `function` 都能在入口文件中找到。
- 每个工具至少手动调用过一次。
- 只读工具不会修改外部状态。
- 写入工具对缺失参数、非法路径、非法索引有清晰错误返回。
- README 的安装步骤和调用示例可复现。
- 插件目录不包含密钥、日志、缓存、构建产物或用户隐私数据。

## 本地分发与开源发布

准备分发或提交到开源仓库时，插件目录应保持干净，只包含源码、manifest、README、依赖声明和必要资源。发布包中的 `plugin.json` 会作为本地导入和后续扩展管理的核心元数据来源，`version`、`name` 和 `description` 会影响插件列表展示。

推荐发布前递增版本号：

- 修复兼容问题或文档错误：递增 patch，例如 `1.0.0` 到 `1.0.1`。
- 新增工具或向后兼容能力：递增 minor，例如 `1.0.0` 到 `1.1.0`。
- 改名、删除工具或破坏兼容：递增 major，例如 `1.0.0` 到 `2.0.0`。

## 完整最小示例

目录：

```text
plugins/example-plugin/
  plugin.json
  plugin.py
  README.md
  requirements.txt
```

`plugin.json`：

```json
{
  "id": "example-plugin",
  "name": "Example Plugin",
  "version": "1.0.0",
  "description": "Example Plugin demonstrates the minimum AudioMate plugin format.",
  "entry": "plugin.py",
  "tools": [
    {
      "name": "echo",
      "description": "Return the input text for connectivity and argument testing.",
      "function": "echo",
      "read_only": true
    }
  ]
}
```

`plugin.py`：

```python
from __future__ import annotations

from typing import Any


PLUGIN_VERSION = "1.0.0"


def echo(text: str = "", **kwargs: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "text": text,
    }
```

`README.md`：

````markdown
# Example Plugin

This plugin demonstrates the minimum AudioMate plugin format.

## Tools

- `echo`: read-only, returns the input `text`.

## Example

```json
{"text": "hello"}
```
````

`requirements.txt`：

```text

```
