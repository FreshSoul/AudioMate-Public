from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any


class MCPRuntimeError(RuntimeError):
    pass


class MCPRuntimeService:
    def __init__(self, app_settings: dict | None = None):
        self._selected_name = ""
        self._order: list[str] = []
        self._enabled_names: list[str] = []
        self._configs: dict[str, dict] = {}
        self._tools_cache: list[dict[str, Any]] = []
        self._cache_key: tuple | None = None
        self.configure(app_settings or {})

    def configure(self, app_settings: dict | None = None):
        source = app_settings if isinstance(app_settings, dict) else {}
        raw_configs = source.get("mcp_configs") if isinstance(source.get("mcp_configs"), dict) else {}
        configs = {}
        for name, config in raw_configs.items():
            normalized_name = str(name or "").strip()
            if not normalized_name or not isinstance(config, dict):
                continue
            normalized_config = dict(config)
            if "enabled" not in normalized_config:
                normalized_config["enabled"] = False
            else:
                normalized_config["enabled"] = bool(normalized_config.get("enabled"))
            configs[normalized_name] = normalized_config

        raw_order = source.get("mcp_config_order") if isinstance(source.get("mcp_config_order"), list) else []
        order = []
        seen = set()
        for item in raw_order:
            name = str(item or "").strip()
            if name in configs and name not in seen:
                order.append(name)
                seen.add(name)
        for name in configs:
            if name not in seen:
                order.append(name)
                seen.add(name)

        enabled_names = [name for name in order if bool(configs.get(name, {}).get("enabled"))]
        selected = str(source.get("mcp_selected_config") or "").strip()
        if selected not in enabled_names:
            selected = enabled_names[0] if enabled_names else ""

        self._configs = configs
        self._order = order
        self._enabled_names = enabled_names
        self._selected_name = selected
        self._invalidate_cache()

    def _invalidate_cache(self):
        self._tools_cache = []
        self._cache_key = None

    def has_active_config(self) -> bool:
        return bool(self._enabled_names)

    def describe_active_config(self) -> dict[str, Any]:
        enabled_configs = []
        for name in self._enabled_names:
            config = self._prepare_config(self._configs.get(name) or {})
            item = {
                "name": name,
                "transport": (config.get("transport") or config.get("type") or ("stdio" if config.get("command") else "")).strip(),
            }
            if "url" in config:
                item["url"] = config.get("url")
            if "command" in config:
                item["command"] = config.get("command")
                item["args"] = config.get("args") or []
            enabled_configs.append(item)

        first_name = self._enabled_names[0] if self._enabled_names else ""
        config = self._prepare_config(self._configs.get(first_name) or {})
        summary = {
            "selected": first_name,
            "enabled": bool(enabled_configs),
            "enabled_count": len(enabled_configs),
            "enabled_configs": enabled_configs,
            "order": list(self._order),
            "transport": (config.get("transport") or config.get("type") or ("stdio" if config.get("command") else "")).strip(),
        }
        if "url" in config:
            summary["url"] = config.get("url")
        if "command" in config:
            summary["command"] = config.get("command")
            summary["args"] = config.get("args") or []
        return summary

    def _candidate_url_transports(self, config: dict) -> list[str]:
        explicit = str(config.get("transport") or config.get("type") or "").strip()
        if explicit:
            return [explicit]
        if config.get("url"):
            return ["streamable_http", "sse"]
        return []

    def list_tools(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        cache_key = self._build_cache_key()
        if not force_refresh and self._cache_key == cache_key and self._tools_cache:
            return list(self._tools_cache)
        tools = self._run_async(self._list_tools_async())
        self._tools_cache = list(tools)
        self._cache_key = cache_key
        return tools

    def list_tools_grouped(self, force_refresh: bool = False) -> dict[str, list[dict[str, Any]]]:
        """Return ``{config_name: [tool, ...]}`` so callers (e.g. system-prompt
        builders) can enumerate tools per MCP server. Never raises on
        configuration errors — returns an empty dict instead, because this
        path is best-effort prompt enrichment, not a hard runtime dependency.
        """
        try:
            tools = self.list_tools(force_refresh=force_refresh)
        except Exception:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("config_name") or tool.get("mcp_config") or "").strip()
            if not name:
                continue
            grouped.setdefault(name, []).append(tool)
        return grouped

    def call_tool(
        self,
        tool_name: str,
        arguments: dict | None = None,
        timeout_seconds: int = 60,
        config_name: str | None = None,
    ) -> dict[str, Any]:
        normalized_name = (tool_name or "").strip()
        if not normalized_name:
            raise MCPRuntimeError("tool_name is required")
        return self._run_async(
            self._call_tool_async(
                tool_name=normalized_name,
                arguments=arguments or {},
                timeout_seconds=timeout_seconds,
                config_name=config_name,
            )
        )

    def _build_cache_key(self) -> tuple:
        config_fingerprints = []
        for name in self._order:
            config = self._configs.get(name, {})
            try:
                fingerprint = json.dumps(config, sort_keys=True, ensure_ascii=False, default=str)
            except TypeError:
                fingerprint = repr(config)
            config_fingerprints.append((name, fingerprint))
        return (tuple(self._enabled_names), tuple(config_fingerprints))

    def _run_async(self, coroutine):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        result_box: dict[str, Any] = {}

        def runner():
            try:
                result_box["result"] = asyncio.run(coroutine)
            except BaseException as exc:  # propagate exactly to the caller thread
                result_box["error"] = exc

        thread = threading.Thread(target=runner, name="MCPRuntimeAsyncBridge", daemon=True)
        thread.start()
        thread.join()
        if "error" in result_box:
            raise result_box["error"]
        return result_box.get("result")

    def _prepare_config(self, config: dict) -> dict:
        prepared = dict(config or {})
        if prepared.get("mcpServers") and isinstance(prepared["mcpServers"], dict):
            first_key = next(iter(prepared["mcpServers"]), "")
            if first_key:
                prepared = dict(prepared["mcpServers"][first_key])
        prepared.pop("active", None)
        prepared.pop("enabled", None)
        return prepared

    def _prepare_stdio_env(self, config: dict) -> dict:
        if sys.platform != "win32":
            return config
        prepared = dict(config)
        env = dict(prepared.get("env") or {})
        user_keys_lower = {key.lower(): key for key in env}
        for sys_key, sys_value in os.environ.items():
            if sys_key.lower() not in user_keys_lower:
                env[sys_key] = sys_value
        prepared["env"] = env
        return prepared

    def _require_enabled_config(self, config_name: str) -> dict:
        name = str(config_name or "").strip()
        if not name or name not in self._configs or name not in self._enabled_names:
            raise MCPRuntimeError("No enabled MCP configuration is available. Please enable one in Settings.")
        return self._prepare_config(self._configs[name])

    async def _open_session(self, config_name: str):
        try:
            import mcp
            from mcp.client.sse import sse_client
        except Exception as exc:
            raise MCPRuntimeError(f"MCP dependency is unavailable: {exc}") from exc

        cfg = self._require_enabled_config(config_name)
        exit_stack = AsyncExitStack()
        session = None

        logging_callback = None
        read_timeout = timedelta(seconds=int(cfg.get("session_read_timeout", 60) or 60))

        try:
            if cfg.get("url"):
                transport_errors: list[str] = []
                for transport_type in self._candidate_url_transports(cfg):
                    try:
                        if transport_type == "streamable_http":
                            try:
                                from mcp.client.streamable_http import streamablehttp_client
                            except Exception as exc:
                                raise MCPRuntimeError(f"streamable_http transport is unavailable: {exc}") from exc

                            read_stream, write_stream, _ = await exit_stack.enter_async_context(
                                streamablehttp_client(
                                    url=cfg["url"],
                                    headers=cfg.get("headers") or {},
                                    timeout=timedelta(seconds=int(cfg.get("timeout", 30) or 30)),
                                    sse_read_timeout=timedelta(seconds=int(cfg.get("sse_read_timeout", 300) or 300)),
                                    terminate_on_close=bool(cfg.get("terminate_on_close", True)),
                                )
                            )
                            session = await exit_stack.enter_async_context(
                                mcp.ClientSession(
                                    read_stream=read_stream,
                                    write_stream=write_stream,
                                    read_timeout_seconds=read_timeout,
                                    logging_callback=logging_callback,
                                )
                            )
                        else:
                            streams = await exit_stack.enter_async_context(
                                sse_client(
                                    url=cfg["url"],
                                    headers=cfg.get("headers") or {},
                                    timeout=float(cfg.get("timeout", 5) or 5),
                                    sse_read_timeout=float(cfg.get("sse_read_timeout", 300) or 300),
                                )
                            )
                            session = await exit_stack.enter_async_context(
                                mcp.ClientSession(
                                    *streams,
                                    read_timeout_seconds=read_timeout,
                                    logging_callback=logging_callback,
                                )
                            )
                        break
                    except Exception as exc:
                        transport_errors.append(f"{transport_type}: {exc}")
                        await exit_stack.aclose()
                        exit_stack = AsyncExitStack()
                        session = None
                if session is None:
                    details = "; ".join(transport_errors) or "no transport candidates succeeded"
                    raise MCPRuntimeError(f"Unable to connect to MCP server at {cfg['url']}: {details}")
            else:
                stdio_cfg = self._prepare_stdio_env(cfg)
                server_params = mcp.StdioServerParameters(**stdio_cfg)
                # In PyInstaller windowed builds, sys.stderr can be an invalid
                # Windows handle. The MCP stdio client passes its errlog to
                # subprocess stderr, so provide a real file handle explicitly.
                stdio_errlog = exit_stack.enter_context(open(os.devnull, "w", encoding="utf-8"))
                streams = await exit_stack.enter_async_context(mcp.stdio_client(server_params, errlog=stdio_errlog))
                session = await exit_stack.enter_async_context(
                    mcp.ClientSession(
                        *streams,
                        read_timeout_seconds=read_timeout,
                        logging_callback=logging_callback,
                    )
                )

            await session.initialize()
            return session, exit_stack
        except Exception:
            await exit_stack.aclose()
            raise

    async def _list_tools_async(self) -> list[dict[str, Any]]:
        if not self._enabled_names:
            raise MCPRuntimeError("No MCP configuration enabled. Please enable one in Settings.")

        tools = []
        for config_name in self._enabled_names:
            session, exit_stack = await self._open_session(config_name)
            try:
                response = await session.list_tools()
                for item in getattr(response, "tools", []) or []:
                    schema = getattr(item, "inputSchema", None)
                    tools.append(
                        {
                            "name": getattr(item, "name", ""),
                            "description": getattr(item, "description", "") or "",
                            "input_schema": schema if isinstance(schema, dict) else {},
                            "config_name": config_name,
                            "mcp_config": config_name,
                        }
                    )
            finally:
                await exit_stack.aclose()
        return tools

    def _serialize_content_item(self, item: Any) -> dict[str, Any]:
        if hasattr(item, "model_dump"):
            data = item.model_dump(mode="json")
        elif hasattr(item, "dict"):
            data = item.dict()
        else:
            data = {"type": type(item).__name__, "value": str(item)}
        if isinstance(data, dict) and "text" in data and data.get("text") is not None:
            data["text"] = str(data.get("text"))
        return data if isinstance(data, dict) else {"value": data}

    async def _resolve_tool_config_name(self, tool_name: str, config_name: str | None = None) -> str:
        requested_name = str(config_name or "").strip()
        if requested_name:
            if requested_name not in self._enabled_names:
                raise MCPRuntimeError(f"MCP configuration is not enabled: {requested_name}")
            return requested_name

        tools = await self._list_tools_async()
        for item in tools:
            if item.get("name") == tool_name and item.get("config_name") in self._enabled_names:
                return str(item.get("config_name"))
        raise MCPRuntimeError(f"MCP tool not found in enabled configurations: {tool_name}")

    async def _call_tool_async(self, tool_name: str, arguments: dict, timeout_seconds: int, config_name: str | None = None) -> dict[str, Any]:
        resolved_config_name = await self._resolve_tool_config_name(tool_name, config_name=config_name)
        session, exit_stack = await self._open_session(resolved_config_name)
        try:
            result = await session.call_tool(
                name=tool_name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=max(1, int(timeout_seconds or 60))),
            )
            content_items = [self._serialize_content_item(item) for item in (getattr(result, "content", None) or [])]
            text_parts = []
            for item in content_items:
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())
            return {
                "tool": tool_name,
                "config_name": resolved_config_name,
                "mcp_config": resolved_config_name,
                "arguments": arguments,
                "is_error": bool(getattr(result, "isError", False)),
                "content": content_items,
                "text": "\n\n".join(text_parts).strip(),
            }
        finally:
            await exit_stack.aclose()