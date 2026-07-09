from __future__ import annotations

import importlib.util
import os
import re
import traceback
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable

from src.tools.base import Tool, ToolContext, ToolResult, ToolResultStatus
from src.tools.registry import ToolRegistry
from src.utils.plugin_store import build_plugin_payload, normalize_plugin_settings


def _slugify(text: str, fallback: str = "plugin") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return cleaned or fallback


@dataclass
class _PluginRuntimeRecord:
    plugin_item: dict
    module: ModuleType | None = None
    instance: Any = None
    tool_names: list[str] = field(default_factory=list)


class PluginTool(Tool):
    def __init__(self, plugin_item: dict, tool_spec: dict, callback: Callable[[dict, ToolContext], Any]):
        self.plugin_item = plugin_item
        self.tool_spec = tool_spec
        self.callback = callback
        self._name = f"plugin.{plugin_item.get('id')}.{tool_spec.get('name')}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return str(self.tool_spec.get("description") or self.plugin_item.get("description") or "Plugin tool")

    def is_read_only(self, input: dict | None = None) -> bool:
        return bool(self.tool_spec.get("read_only"))

    def prompt(self) -> str:
        return (
            f"{self.description} Use call_plugin_tool('{self.name}', input_dict) "
            "from generated Python code to invoke this plugin tool."
        )

    def execute(self, input: dict, context: ToolContext) -> ToolResult:
        try:
            plugin_context = ToolContext(
                waapi_client=context.waapi_client,
                toolbox=context.toolbox,
                mode=context.mode,
                parent_widget=context.parent_widget,
                extra={**(context.extra or {}), "plugin": self.plugin_item},
            )
            result = self.callback(input if isinstance(input, dict) else {}, plugin_context)
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, dict):
                output = result.get("output") or result.get("message") or str(result)
                return ToolResult(output=str(output), data=result)
            return ToolResult(output=str(result or ""))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                output=f"Plugin tool '{self.name}' failed: {exc}",
                status=ToolResultStatus.ERROR,
                data={"traceback": traceback.format_exc()},
            )


class PluginRuntimeService:
    def __init__(self, registry: ToolRegistry, base_context_factory: Callable[[], dict] | None = None):
        self.registry = registry
        self.base_context_factory = base_context_factory
        self._records: dict[str, _PluginRuntimeRecord] = {}
        self._settings = {"items": []}

    def configure(self, app_settings) -> dict:
        settings = normalize_plugin_settings(app_settings)
        next_ids = {item.get("id") for item in settings.get("items", []) if item.get("id")}
        for plugin_id in list(self._records):
            if plugin_id not in next_ids:
                self.unload_plugin(plugin_id)

        updated_items = []
        for item in settings.get("items", []):
            prepared = dict(item)
            plugin_id = prepared.get("id")
            if not prepared.get("enabled"):
                self.unload_plugin(plugin_id)
                prepared["status"] = "discovered"
                prepared["error"] = ""
                updated_items.append(prepared)
                continue
            loaded = self.load_plugin(prepared)
            updated_items.append(loaded)

        self._settings = build_plugin_payload({"items": updated_items})
        return self._settings

    def load_plugin(self, plugin_item: dict) -> dict:
        plugin_id = str(plugin_item.get("id") or "").strip()
        self.unload_plugin(plugin_id)
        prepared = dict(plugin_item)
        try:
            source_dir = os.path.abspath(str(prepared.get("source_dir") or ""))
            entry = str(prepared.get("entry") or "plugin.py")
            entry_path = os.path.abspath(os.path.join(source_dir, entry))
            if os.path.commonpath([source_dir, entry_path]) != source_dir:
                raise ValueError("Plugin entry 不能指向插件目录之外")
            if not os.path.isfile(entry_path):
                raise ValueError(f"Plugin entry 不存在: {entry}")

            module_name = f"audiomate_plugin_{_slugify(plugin_id)}"
            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if spec is None or spec.loader is None:
                raise ValueError("无法加载 Plugin entry")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            prepared["status"] = "loaded"

            init_context = self._build_init_context(prepared)
            instance = None
            if hasattr(module, "Plugin"):
                instance = module.Plugin()
                if hasattr(instance, "initialize"):
                    instance.initialize(init_context)
            elif hasattr(module, "init_plugin"):
                instance = module.init_plugin(init_context)
            prepared["status"] = "initialized"

            tools = self._resolve_tool_specs(prepared, module, instance)
            tool_names = []
            for tool_spec in tools:
                callback = self._resolve_tool_callback(tool_spec, module, instance)
                tool = PluginTool(prepared, tool_spec, callback)
                self.registry.register(tool)
                tool_names.append(tool.name)
            prepared["status"] = "registered"
            prepared["error"] = ""
            prepared["tools"] = tools
            self._records[plugin_id] = _PluginRuntimeRecord(prepared, module, instance, tool_names)
            return prepared
        except Exception as exc:  # noqa: BLE001
            self.unload_plugin(plugin_id)
            prepared["status"] = "failed"
            prepared["error"] = str(exc)
            return prepared

    def unload_plugin(self, plugin_id: str) -> None:
        if not plugin_id:
            return
        record = self._records.pop(plugin_id, None)
        if record is None:
            return
        for tool_name in record.tool_names:
            self.registry.unregister(tool_name)
        for target in (record.instance, record.module):
            if target is None:
                continue
            cleanup = getattr(target, "cleanup", None) or getattr(target, "shutdown", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass

    def shutdown(self) -> None:
        for plugin_id in list(self._records):
            self.unload_plugin(plugin_id)

    def list_tools(self, allowed_plugin_ids: set | None = None) -> list[dict]:
        tools = []
        for plugin_id, record in self._records.items():
            if allowed_plugin_ids is not None and plugin_id not in allowed_plugin_ids:
                continue
            for tool_name in record.tool_names:
                tool = self.registry.find_tool(tool_name)
                if tool:
                    tools.append({
                        "name": tool.name,
                        "description": tool.description,
                        "plugin": record.plugin_item.get("name"),
                    })
        return tools

    def build_prompt_guidance(self, allowed_plugin_ids: set | None = None) -> str:
        tools = self.list_tools(allowed_plugin_ids=allowed_plugin_ids)
        if not tools:
            return ""
        lines = [
            "\nACTIVE PLUGIN TOOLS:",
            "- Plugins are user-installed executable tools.",
            "- Invoke them from Python code with call_plugin_tool(tool_name, input_dict).",
            "- Use plugin tools only when they materially help the user's request.",
        ]
        for tool in tools:
            lines.append(f"- {tool['name']} ({tool.get('plugin') or 'Plugin'}): {tool.get('description') or ''}")
        return "\n".join(lines).strip() + "\n\n"

    def call_tool(self, name: str, input_data: dict | None = None, mode: str = "Agent Mode"):
        tool = self.registry.find_tool(str(name or ""))
        if tool is None or not tool.name.startswith("plugin."):
            raise ValueError(f"Plugin tool not found: {name}")
        context = ToolContext(mode=mode, extra=self._build_init_context({}))
        result = tool.execute(input_data or {}, context)
        if result.is_error:
            raise RuntimeError(result.output)
        return result.data if result.data is not None else result.output

    def context_functions(self, mode_getter: Callable[[], str] | None = None) -> dict:
        def _mode() -> str:
            return mode_getter() if mode_getter else "Agent Mode"

        def call_plugin_tool(name, input_data=None):
            return self.call_tool(str(name), input_data if isinstance(input_data, dict) else {}, _mode())

        return {
            "list_plugin_tools": self.list_tools,
            "call_plugin_tool": call_plugin_tool,
        }

    def _build_init_context(self, plugin_item: dict) -> dict:
        context = {}
        if self.base_context_factory:
            try:
                context.update(self.base_context_factory() or {})
            except Exception:
                pass
        context["plugin"] = plugin_item
        return context

    def _resolve_tool_specs(self, plugin_item: dict, module: ModuleType, instance: Any) -> list[dict]:
        tools = list(plugin_item.get("tools") or [])
        source = instance if instance is not None else module
        declared = getattr(source, "TOOLS", None)
        if isinstance(declared, list):
            for item in declared:
                if isinstance(item, dict):
                    tools.append(item)
        normalized = []
        seen = set()
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = _slugify(item.get("name"), fallback="")
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append({
                "name": name,
                "description": str(item.get("description") or "").strip(),
                "function": str(item.get("function") or name).strip(),
                "read_only": bool(item.get("read_only", False)),
            })
        return normalized

    def _resolve_tool_callback(self, tool_spec: dict, module: ModuleType, instance: Any):
        function_name = tool_spec.get("function") or tool_spec.get("name")
        targets = [target for target in (instance, module) if target is not None]
        for target in targets:
            callback = getattr(target, function_name, None)
            if callable(callback):
                return callback
        raise ValueError(f"Plugin tool function not found: {function_name}")
