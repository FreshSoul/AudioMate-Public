"""Prompt guidance builders that do not need direct widget access."""

from __future__ import annotations


def build_structured_tool_prompt_guidance(tool_registry, mode: str, logger=None) -> str:
    if tool_registry is None:
        return ""
    try:
        manifest = tool_registry.build_tools_manifest_prompt(mode=mode)
    except Exception as exc:
        if logger is not None:
            logger.warning("Failed to build structured tool manifest: %s", exc)
        return ""
    return (
        "\nSTRUCTURED TOOL INTERFACE (PREFERRED):\n"
        "- Prefer `call_structured_tool(tool_name, input_dict)` for common operations instead of raw WAAPI payloads.\n"
        "- The registry validates schema, permissions, WAAPI connectivity, and Ask/Agent availability.\n"
        "- In Ask Mode, unavailable tools are denied by default. Do not work around denial with raw WAAPI calls.\n"
        "- External coding sub-agents are available through `external_agent.codex` and `external_agent.claude_code` when their CLIs are installed. Use them for codebase-heavy review/implementation tasks, pass an explicit `cwd`, and summarize their stdout/stderr for the user.\n"
        "- External coding sub-agents launch local processes and may read/write files or use network access; they are Agent Mode only. Prefer read-only prompts unless the user clearly asked for implementation.\n"
        "- PowerShell is available through `powershell.run` / `run_powershell(...)` in Agent Mode only. Every invocation shows a user confirmation dialog before the process starts; if the user declines, do not retry or work around it.\n"
        "- If no dedicated tool covers a known WAAPI URI, use `waapi.call_documented_read` for read-only URIs or `waapi.call_documented_write` in Agent Mode for write/procedure URIs; these calls are policy-gated and checked against the connected Wwise version when possible.\n"
        "- Use raw `waapi_client.call(...)` only as a last resort after checking dedicated tools and documented-call tools.\n"
        "- Before any raw `waapi_client.call(...)`, inspect `get_waapi_schema(uri)` or `waapi.get_schema` and build payloads from the returned `argsSchema` and `optionsSchema` only.\n"
        "- Common WAAPI routing: use `waapi.get_selected_objects` for selection, `waapi.get_objects` for object.get queries, `waapi.get_property` for one value, `waapi.batch_set_property` for repeated property edits, `waapi.set_reference` for Output Bus/Attenuation references, `waapi.get_property_reference_names` before uncertain fields, and `waapi.find_in_project_explorer` for UI highlighting.\n"
        "- Version-aware routing: use `waapi.get_version_context` and `waapi.resolve_hierarchy_root` before choosing legacy roots. Wwise 2025+ prefers `\\Containers` for Actor-Mixer/Music content; older versions use `\\Actor-Mixer Hierarchy` and `\\Interactive Music Hierarchy`.\n"
        "- Bus routing: Wwise 2025+ examples use `\\Busses` and `Main Audio Bus`, while older projects/docs may use `\\Master-Mixer Hierarchy` and `Master Audio Bus`; use `waapi.get_busses` or `waapi.resolve_main_bus` first. Use `waapi.create_bus` for Bus/AuxBus creation, `waapi.set_bus_property` for BusVolume/OutputBusVolume-style properties, and `waapi.set_object_output_bus` to route Sound/Actor-Mixer objects. Never set OutputBus on Bus/AuxBus objects.\n"
        "- Runtime SoundEngine routing: use `waapi.soundengine_get_state` / `waapi.soundengine_get_switch` for readback, and Agent-only `waapi.soundengine_post_event`, `waapi.soundengine_set_rtpc`, `waapi.soundengine_set_state`, `waapi.soundengine_set_switch`, or `waapi.soundengine_stop_all` for runtime actions. These are not project-object edits.\n"
        "- SoundBank routing: use `waapi.soundbank_get_inclusions`, `waapi.soundbank_set_inclusions`, and `waapi.soundbank_generate`; use `waapi.project_save` for saving the current project.\n"
        "- Container assignment routing: use `waapi.blendcontainer_get_assignments`, `waapi.blendcontainer_add_track`, `waapi.blendcontainer_set_assignment`, `waapi.switchcontainer_get_assignments`, and `waapi.switchcontainer_set_assignment` instead of hand-building Blend/Switch assignment payloads.\n"
        "- Attenuation curves have dedicated tools: `waapi.get_attenuation_curve` and `waapi.set_attenuation_curve`. Do not hand-build those raw payloads unless the structured tool is insufficient.\n"
        "- Interactive Music routing: use `waapi.get_music_structure` to inspect music hierarchy, `waapi.create_music_object` for MusicSegment/MusicTrack/MusicPlaylistContainer/MusicSwitchContainer, `waapi.create_music_cue` for MusicCue because it must use `list: Cues`, and `waapi.set_state_groups` / `waapi.set_state_properties` for state-driven music setup.\n"
        "- The open-source build does not vendor third-party WAAPI documentation; for exact payloads, inspect `get_waapi_schema(uri)` / `waapi.get_schema` against the user's connected Wwise instance.\n"
        "- Available tools JSON manifest:\n"
        f"{manifest}\n\n"
    )


def build_mcp_prompt_guidance(active_config: dict, user_query: str = "",
                               tools_by_server: dict | None = None) -> str:
    if not isinstance(active_config, dict) or not active_config.get("enabled"):
        return ""

    enabled_configs = active_config.get("enabled_configs") if isinstance(active_config.get("enabled_configs"), list) else []
    selected_name = str(active_config.get("selected") or "").strip()
    config_names = [str(item.get("name") or "").strip() for item in enabled_configs if isinstance(item, dict)]
    lowered_names = " ".join(config_names).casefold()

    guidance = [
        "\nMCP ROUTING GUIDANCE:\n",
        f"- Enabled MCP configs in priority order: {', '.join(config_names) or selected_name or 'unknown'}\n",
        "- `list_mcp_tools()` returns tools from enabled MCP configs with `config_name` metadata.\n",
        "- `call_mcp_tool()` resolves duplicate tool names by this priority order unless `config_name` is provided.\n",
    ]
    for item in enabled_configs[:5]:
        if not isinstance(item, dict):
            continue
        endpoint = str(item.get("url") or item.get("command") or "").strip()
        transport = str(item.get("transport") or "").strip()
        if endpoint:
            guidance.append(f"- {item.get('name')}: {transport or 'unknown'} · {endpoint}\n")

    # Enumerate each MCP server's actual tool inventory. This is what
    # finally lets the LLM see e.g. REAPER tools and know they can be
    # invoked via call_mcp_tool(...).
    if isinstance(tools_by_server, dict) and tools_by_server:
        guidance.append("\nMCP TOOL INVENTORY (callable via call_mcp_tool):\n")
        for server_name, tools in tools_by_server.items():
            if not isinstance(tools, list) or not tools:
                continue
            tool_lines = []
            for tool in tools[:30]:
                if not isinstance(tool, dict):
                    continue
                name = str(tool.get("name") or "").strip()
                if not name:
                    continue
                desc = str(tool.get("description") or "").strip().replace("\n", " ")
                if len(desc) > 120:
                    desc = desc[:117] + "…"
                tool_lines.append(f"  · {name}" + (f" — {desc}" if desc else ""))
            if tool_lines:
                guidance.append(f"- Server \"{server_name}\":\n")
                guidance.extend(line + "\n" for line in tool_lines)
        guidance.append(
            "- Example invocation (use this exact pattern):\n"
            "  ```python\n"
            "  result = call_mcp_tool(\"<tool_name>\", {\"arg\": value}, config_name=\"<server_name>\")\n"
            "  print(result)\n"
            "  ```\n"
        )

    if "飞书" in lowered_names or "feishu" in lowered_names or "lark" in lowered_names:
        guidance.extend(
            [
                "- When the user's request involves Feishu/Lark content, such as 飞书文档、知识库、云文档、表格、多维表格、wiki、doc、docx、sheet、file token, you SHOULD consider the enabled Feishu/Lark MCP configs first.\n",
                "- If the user directly provides a Feishu/Lark wiki/doc/sheet URL and asks to read, summarize, or extract content, try MCP before generic webpage fetching because the normal web page often redirects to login.\n",
                "- You are NOT forced to call MCP on every Feishu-related request. Decide based on whether MCP is likely to provide fresher, more authoritative, or directly actionable data.\n",
                "- If MCP seems relevant, a good first step is to call `get_active_mcp_config()` or `list_mcp_tools()` to inspect the available capabilities, then call `call_mcp_tool(...)` only when it helps answer the request.\n",
                "- If the request is clearly unrelated to Feishu/Lark content, do not force MCP; use WAAPI, local tools, webpage access, or normal reasoning as appropriate.\n",
            ]
        )
    else:
        guidance.extend(
            [
                "- If the user's request clearly matches one of the enabled MCP server domains, you may choose MCP first; otherwise do not force MCP.\n",
                "- Use MCP when it provides the most direct path to the requested external data or operation.\n",
            ]
        )

    if user_query:
        guidance.append("- Base the MCP decision on the user's latest request, not on previous turns alone.\n")

    return "".join(guidance) + "\n"


def build_document_tools_guidance() -> str:
    """Tell the LLM about the structured document-reader tools.

    These are exposed both to the main agent (via build_executor_context)
    and to every sub-agent sandbox (independent of plugin allowlists),
    because document reading is generic and not plugin-bound.
    """
    return (
        "\nDOCUMENT READING TOOLS:\n"
        "- For CSV/XLSX/DOCX/PPTX attachments, prefer the structured readers"
        " over `read_user_file`. They return typed Python dicts you can index"
        " directly, instead of a flat string that loses sheet names, table"
        " structure, headings, and notes.\n"
        "- `read_csv(path, max_rows=10000, encoding=None, delimiter=None)`"
        " → {path, encoding, delimiter, row_count, rows, columns, truncated,"
        " dtypes}. Encoding and delimiter are auto-sniffed when not given.\n"
        "- `read_xlsx(path, sheet=None, max_rows=10000)` → {path, sheets:"
        " [{name, row_count, columns, rows, truncated}]}. Pass `sheet=\"Name\"`"
        " or `sheet=<int>` to read a single sheet. Numbers and dates keep"
        " their native types (dates are ISO strings).\n"
        "- `read_docx(path)` → {path, title, paragraphs:[{text,style}],"
        " headings:[{level,text}], tables:[{rows}], section_count}.\n"
        "- `read_pptx(path)` → {path, slide_count, slides:[{index, title,"
        " body_text, tables, notes}]}.\n"
        "- On failure each reader returns `{\"error\": <reason>, \"path\":"
        " <path>}` instead of raising, so multi-turn sub-agent loops don't"
        " die on a single traceback.\n"
        "- Example:\n"
        "  ```python\n"
        "  data = read_xlsx(file_path)\n"
        "  for sheet in data[\"sheets\"]:\n"
        "      print(sheet[\"name\"], len(sheet[\"rows\"]), sheet[\"columns\"])\n"
        "  ```\n"
        "- `read_user_file` still works for any text-shaped file and now also"
        " emits structured markdown for the four formats above (sheet names,"
        " headings, slide titles + notes preserved), but the dict-returning"
        " readers remain the precise choice when you need to index by row,"
        " column, slide index, or heading level.\n\n"
    )
