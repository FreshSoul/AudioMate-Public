"""Golden-task runner — execute the golden tasks against a real LLM.

Reads your AudioMate ``settings.json`` to get the same API key / base URL /
model you use in the GUI (override with ``--model`` / ``--api-key``).
Sends each task's ``user_query`` through ``LLMService.stream_events``,
extracts code blocks + native tool_use calls from the response, scores
against the expectations in ``golden_tasks.json``, and prints a summary.

Usage
-----
::

    # Use the model from settings.json
    python scripts/run_golden_tasks.py

    # Override model
    python scripts/run_golden_tasks.py --model claude-opus-4-6

    # Run a subset (by id or category)
    python scripts/run_golden_tasks.py --id create_actor_mixer --id list_events
    python scripts/run_golden_tasks.py --category loudness_analysis

    # Limit to first N tasks (smoke test)
    python scripts/run_golden_tasks.py --limit 5

    # Write a JSON report
    python scripts/run_golden_tasks.py --report golden_report.json

    # Run each task N times and report average pass rate
    python scripts/run_golden_tasks.py --runs 3

The runner uses a MINIMAL system prompt — it's testing whether the model
can pick the right tool / API given the task description alone. To test
the full AudioMate prompt stack, use ``--system-prompt full`` (loads the
real prompt blocks). ``minimal`` (default) is faster and isolates the
model's intrinsic knowledge from the prompt scaffolding.

Exit code is 0 if pass_rate >= --threshold (default 0.0 — never fail),
1 otherwise. Use ``--threshold 0.8`` in CI to gate on regressions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Make ``src.*`` importable when running from repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.provider_events import (  # noqa: E402
    FinishReason,
    ProviderError,
    TextDelta,
    ThinkingDelta,
    ToolUse,
    UsageInfo,
)
from src.llm.service import LLMService  # noqa: E402
from src.test.golden_tasks_runner import (  # noqa: E402
    TaskScore,
    load_golden_tasks,
    score_task,
    summarize,
)
from src.utils.app_paths import SETTINGS_FILE  # noqa: E402
from src.utils.parsing import extract_code_blocks, extract_pseudo_tool_code_blocks  # noqa: E402


# ---------------------------------------------------------------------------
# Settings & prompts
# ---------------------------------------------------------------------------


_MINIMAL_SYSTEM_PROMPT_BASE = (
    "You are an AudioMate assistant capable of controlling Wwise via WAAPI.\n"
    "When the user asks for an action or query that touches Wwise, respond "
    "with a ```python_waapi``` code block that performs it. For pure chat or "
    "explanation, respond with plain text and DO NOT generate a code block.\n\n"

    "EXECUTION ENVIRONMENT — inside python_waapi blocks you have a "
    "``waapi_client`` object plus the following helpers. Prefer the helper "
    "over a hand-written WAAPI call wherever it exists:\n"
    "  - ``analyze_audio_file(path)`` — single local audio file\n"
    "  - ``analyze_directory_loudness(path, recursive=True)`` — folder sweep\n"
    "  - ``analyze_selected_source_files_loudness()`` — selection-scoped\n"
    "  - ``analyze_project_source_files_loudness()`` — whole project\n"
    "  - ``analyze_selected_sources_full_route_loudness()`` — incl. bus chain\n"
    "  - ``normalize_audio_loudness(path, target_lufs)`` — write op\n"
    "  - ``import_audio_files_to_selected_wwise(paths)`` — write op\n"
    "  - ``get_selected_source_files()`` / ``get_project_source_files()``\n"
    "  - ``read_user_file(path)`` — local file read (NOT raw open())\n"
    "  - ``list_local_directory(path)`` — listing (NOT os.listdir)\n"
    "  - ``describe_local_path(path)`` — file/dir/missing introspection\n"
    "  - ``write_user_file(path, content)`` / ``write_file_tree(base_dir, files)``\n"
    "  - ``fetch_webpage(url)`` — sandboxed HTTP fetch (NOT urllib/requests)\n"
    "  - ``call_mcp_tool(name, arguments)`` — invoke an MCP server tool\n"
    "  - ``read_feishu_doc(url)`` — Feishu/Lark links (NOT fetch_webpage)\n"
    "  - ``lookup_waapi_doc(uri_or_keyword)`` — read official WAAPI docs\n"
    "  - ``search_waapi_functions(keyword)`` — search the WAAPI function index\n\n"

    "SELF-CORRECTION RULE (CRITICAL): If you are NOT 100% sure about a WAAPI "
    "function name, argument shape, or property name, you MUST FIRST call "
    "``lookup_waapi_doc(...)`` (or ``search_waapi_functions(...)``) inside a "
    "python_waapi block to read the official docs before you write the action "
    "code. Do not guess from memory. Do not answer from memory when the user "
    "asks how to use a specific API — look it up.\n\n"

    "WEB & EXTERNAL CONTENT RULE: If the user gives a URL or asks you to "
    "consult a web page, you MUST call ``fetch_webpage(url)`` (or "
    "``read_feishu_doc`` for Feishu/Lark links). Do not answer from memory "
    "about the page contents — fetch it.\n\n"

    "WAAPI NAME SAFETY: NEVER invent procedure names that merely sound right. "
    "These names DO NOT EXIST and must never be generated: "
    "``ak.wwise.core.object.addStateGroup``, "
    "``ak.wwise.core.object.setStatePropValue``, "
    "``ak.wwise.core.object.setRTPCBinding``. Use documented names: "
    "``ak.wwise.core.object.setStateGroups``, "
    "``ak.wwise.core.object.setReference``, "
    "``ak.wwise.core.object.setAttenuationCurve``. When uncertain, look up.\n\n"

    "AMBIGUITY RULE: If the user request is genuinely ambiguous (target "
    "object unspecified, scope unclear, multiple reasonable interpretations), "
    "output ONLY this block, nothing else:\n"
    "  [INTENT_CLARIFY]\n"
    "  - First possible intent\n"
    "  - Second possible intent\n"
    "  [/INTENT_CLARIFY]\n"
    "Synonyms that all count as 'analyze': 分析, 锐评, 评估, 检查, 看看, "
    "analyze, review, critique. Only ask when you really don't know — do NOT "
    "ask for routine confirmations.\n\n"

    "EDGE CASE — INVALID NAMES: Wwise object names cannot contain "
    "``/`` ``\\`` ``:`` ``*`` ``?`` ``\"`` ``<`` ``>`` ``|`` ``#``. If the "
    "user asks for a name containing one of these, do NOT silently rename "
    "and execute — explain the limitation, propose a sanitised name, and "
    "wait for confirmation (no code block).\n"
)


_MODE_AGENT_SUFFIX = (
    "\n\nCURRENT MODE: Agent Mode — write operations (normalize, import, "
    "create, delete, modify) are ALLOWED."
)

_MODE_ASK_SUFFIX = (
    "\n\nCURRENT MODE: Ask Mode — write operations are BLOCKED. "
    "``normalize_audio_loudness``, ``write_user_file``, ``write_file_tree``, "
    "``import_audio_files_to_selected_wwise``, and any ``ak.wwise.core.object."
    "create/set/delete/move/copy`` are unavailable. If the user requests a "
    "write op, refuse with a brief explanation and tell them to switch to "
    "Agent Mode. Do NOT generate code that calls a blocked function."
)

_DISCONNECTED_SUFFIX = (
    "\n\nWWISE CONNECTION: Wwise is currently NOT CONNECTED (未连接). "
    "Do NOT generate any python_waapi code block that touches the live "
    "project (no ``ak.wwise.core``, no ``waapi_client.call``, no helpers "
    "that depend on a Wwise selection or project). For action requests, "
    "explain briefly what would happen and tell the user to click Connect "
    "first. For pure conceptual questions you may still answer."
)

_CONNECTED_SUFFIX = (
    "\n\nWWISE CONNECTION: Wwise IS CONNECTED. Live project access is "
    "available."
)

_OUTPUT_PROTOCOL_SUFFIX = (
    "\n\nFINAL OUTPUT PROTOCOL (NON-NEGOTIABLE):\n"
    "- NEVER output <tool_call>, <tool_use>, <function>, <tool_response>, "
    "or JSON tool-call tags. Those are not executable by AudioMate.\n"
    "- NEVER fabricate tool responses or pretend a tool already ran. The app "
    "executes your fenced code block after you send it.\n"
    "- For every executable action, output fenced code only in this exact "
    "shape:\n"
    "```python_waapi\n"
    "# executable Python here\n"
    "```\n"
    "- If no action should run, use plain text only."
)


def _build_minimal_prompt(*, mode: str = "Agent Mode", connected: bool = True) -> str:
    """Compose the minimal prompt with mode + connection context appended."""
    out = _MINIMAL_SYSTEM_PROMPT_BASE
    out += _MODE_AGENT_SUFFIX if mode == "Agent Mode" else _MODE_ASK_SUFFIX
    out += _CONNECTED_SUFFIX if connected else _DISCONNECTED_SUFFIX
    out += _OUTPUT_PROTOCOL_SUFFIX
    return out


def _build_full_prompt(*, mode: str = "Agent Mode", connected: bool = True) -> str:
    """Compose a full AudioMate-like prompt with WAAPI rules + tool guidance.

    This approximates what the GUI sends. It's not byte-identical (GUI has
    dynamic retrieval, memory, MCP config, etc.) but covers the core
    scaffolding: identity, WAAPI rules, tool list, mode/connection context.
    """
    from src.engine.prompt_guidance import (
        build_structured_tool_prompt_guidance,
        build_document_tools_guidance,
    )
    from src.llm.retrieval import WaapiDocRetriever

    # Identity + role
    out = (
        "You are AudioMate, an AI assistant specialized in Wwise audio "
        "middleware. You help users control Wwise via WAAPI, analyze audio "
        "files, manage local files, and access external resources.\n\n"
    )

    # WAAPI rules (the big block from waapi_retriever)
    try:
        retriever = WaapiDocRetriever()
        retriever.initialize()
        rules = retriever.get_rules()
        if rules:
            out += "# WAAPI Usage Rules\n\n" + rules + "\n\n"
    except Exception as exc:
        print(f"WARN: failed to load WAAPI rules: {exc}", file=sys.stderr)

    # Tool guidance (structured tool list + doc tools)
    try:
        from src.tools import create_default_registry
        registry = create_default_registry()
        tool_guidance = build_structured_tool_prompt_guidance(registry, mode=mode)
        doc_guidance = build_document_tools_guidance()
        out += tool_guidance + "\n\n" + doc_guidance + "\n\n"
    except Exception as exc:
        print(f"WARN: failed to build tool guidance: {exc}", file=sys.stderr)

    # Mirror the GUI's EXECUTION ENVIRONMENT block — lists the local helpers
    # that exist alongside ``waapi_client``. Without this, ``--system-prompt
    # full`` actually KNOWS LESS than ``minimal`` about helpers like
    # ``read_user_file`` / ``fetch_webpage`` / ``call_mcp_tool``.
    out += (
        "\nEXECUTION ENVIRONMENT (helpers in scope inside python_waapi blocks):\n"
        "- ``waapi_client`` — direct WAAPI client (fall back when no helper fits).\n"
        "- ``read_user_file(path)`` — read a local text file.\n"
        "- ``list_local_directory(path)`` — list a folder's entries.\n"
        "- ``describe_local_path(path)`` — file / folder / missing introspection.\n"
        "- ``write_user_file(path, content)`` (Agent only) / ``write_file_tree(base_dir, files)``.\n"
        "- ``analyze_audio_file(path)`` / ``analyze_directory_loudness(path, recursive=True)``.\n"
        "- ``analyze_selected_source_files_loudness(...)`` / ``analyze_project_source_files_loudness(...)``.\n"
        "- ``analyze_selected_sources_full_route_loudness(...)`` — accounts for bus gain chain.\n"
        "- ``normalize_audio_loudness(path, target_lufs)`` (Agent only) — backs up by default.\n"
        "- ``import_audio_files_to_selected_wwise(paths)`` (Agent only) — prefer over hand-written ``ak.wwise.core.audio.import``.\n"
        "- ``get_selected_source_files()`` / ``get_project_source_files()``.\n"
        "- ``fetch_webpage(url)`` — sandboxed external fetch. NOT urllib/requests.\n"
        "- ``call_mcp_tool(name, arguments=None, timeout_seconds=60, config_name=None)``.\n"
        "- ``read_feishu_doc(url)`` — Feishu/Lark docs (NOT fetch_webpage).\n"
        "- ``lookup_waapi_doc(uri_or_keyword)`` / ``search_waapi_functions(keyword)``.\n"
        "- ``get_active_mcp_config()`` / ``list_mcp_tools()``.\n\n"
    )

    # Mode + connection context
    out += _MODE_AGENT_SUFFIX if mode == "Agent Mode" else _MODE_ASK_SUFFIX
    out += _CONNECTED_SUFFIX if connected else _DISCONNECTED_SUFFIX

    # Final decision gate — ordered rules. This MUST come last so it has the
    # final word. The ordering is the whole point: ``--system-prompt full``
    # previously let the "always emit code" rule override clarification /
    # self-correction, so the model would guess a default and execute on
    # ambiguous requests ("把音量调大一点" → silently +1dB). We now force a
    # strict precedence: clarify → guard → verify → THEN act.
    out += (
        "\n\n"
        "DECISION GATE — evaluate these in order, top to bottom. The FIRST "
        "rule that matches decides your response; do not skip ahead.\n\n"

        "STEP 1 — AMBIGUITY CHECK (highest priority, but use a HIGH bar):\n"
        "- Only treat a request as ambiguous when there is NO reasonable way "
        "to proceed: no inferable target AND no sensible default. Examples of "
        "genuinely ambiguous: '分析一下' (analyze WHAT?), '把音量调大一点' "
        "(which object? how much?).\n"
        "- IMPORTANT — these are NOT ambiguous, proceed normally:\n"
        "  * 'the selected object(s)' / '选中的对象' — operating on the current "
        "Wwise selection is the normal default; just read the selection.\n"
        "  * A request that names a concrete property/value/target (e.g. "
        "'set Volume to -6 dB', 'MaxDistance 30m', 'tempo 120 BPM').\n"
        "  * A request that references a prior error to fix — that is a "
        "self-correction, handle it in STEP 3, do NOT ask which object.\n"
        "- If (and only if) genuinely ambiguous: output ONLY a "
        "``[INTENT_CLARIFY]`` block with 2-3 mutually-exclusive "
        "interpretations, and STOP. Do NOT pick a default. Do NOT emit code. "
        "When in doubt and a selection-based default exists, PREFER acting "
        "over asking.\n\n"

        "STEP 2 — BOUNDARY / SAFETY CHECK:\n"
        "- Wwise object name contains illegal chars (/ \\ : * ? \" < > | #)? → "
        "explain the limitation, propose a sanitised name, STOP (no code).\n"
        "- Ask Mode + a write operation requested? → refuse, tell user to "
        "switch to Agent Mode, STOP (no code).\n"
        "- Wwise disconnected + request needs the live project? → explain, "
        "tell user to Connect first, STOP (no live-WAAPI code).\n\n"

        "STEP 3 — VERIFY-BEFORE-WRITE CHECK:\n"
        "- Are you 100% certain of the exact WAAPI procedure name, argument "
        "shape, property name, or version-specific field? If NOT, your FIRST "
        "action in the code block must be a verification call: "
        "``lookup_waapi_doc(...)``, ``search_waapi_functions(...)``, "
        "``getSchema``, or ``getPropertyAndReferenceNames``. Never guess a "
        "name from memory — especially for version-sensitive params "
        "(attenuation curve types, music tempo/signature, 3D spatialization, "
        "distance/radius fields).\n\n"

        "STEP 4 — ACTION OUTPUT (only if STEPS 1-2 did not stop you):\n"
        "- The request is an ACTION (modify / create / delete / set / "
        "increase / decrease / assign / batch edit / analyze / import / "
        "normalize / read / list / fetch / lookup): output ``python_waapi`` "
        "code that actually performs it. Do NOT just describe what you'd do.\n"
        "- Complex multi-step tasks: multiple ``python_waapi`` blocks, each "
        "preceded by a short step description.\n"
        "- HELPER PRIORITY (applies to EVERY step, large tasks included): if "
        "a provided helper covers a step, you MUST use it — do NOT fall back "
        "to hand-written low-level WAAPI just because the task is big. Use "
        "``import_audio_files_to_selected_wwise(...)`` NOT raw "
        "``ak.wwise.core.audio.import``; use "
        "``analyze_project_source_files_loudness()`` / "
        "``analyze_selected_source_files_loudness()`` / "
        "``analyze_directory_loudness(...)`` NOT hand-rolled source "
        "enumeration; use ``normalize_audio_loudness(...)`` for loudness "
        "writes. The bigger the pipeline, the MORE important per-step helpers "
        "are — never silently reimplement a helper inline.\n"
        "- A bare description WITHOUT a code block is INVALID for a clear "
        "action request — always include the code.\n"
        "- Pure explanation / conceptual question: respond in plain text, no "
        "code block."
    )
    out += _OUTPUT_PROTOCOL_SUFFIX

    return out


def _load_settings() -> dict:
    if not SETTINGS_FILE.is_file():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _load_credentials_from_keyring() -> tuple[str | None, str | None]:
    """Read api_key + base_url from the same secure store the GUI uses."""
    try:
        from src.services.auth_session import AuthSession
    except Exception:
        return None, None
    try:
        sess = AuthSession()
        return (
            (sess.get_api_key() or None),
            (sess.get_base_url() or None),
        )
    except Exception:
        return None, None


def _default_remote_base_url() -> str | None:
    try:
        from src.llm.embedding_defaults import DEFAULT_REMOTE_BASE_URL
        return DEFAULT_REMOTE_BASE_URL
    except Exception:
        return None


def _resolve_credentials(args) -> tuple[str | None, str | None, str]:
    """Returns (api_key, base_url, model). Override order: CLI > env > keyring > settings."""
    settings = _load_settings()
    keyring_key, keyring_url = _load_credentials_from_keyring()
    api_key = (
        args.api_key
        or os.environ.get("AUDIOMATE_API_KEY")
        or keyring_key
        or settings.get("api_key")
    )
    base_url = (
        args.base_url
        or os.environ.get("AUDIOMATE_BASE_URL")
        or keyring_url
        or settings.get("base_url")
        or _default_remote_base_url()
    )
    model = args.model or settings.get("model") or "claude-opus-4-6"
    return api_key, base_url, model


# ---------------------------------------------------------------------------
# Per-task execution
# ---------------------------------------------------------------------------


def _collect_response(llm: LLMService, messages: list[dict], system: str) -> dict:
    """Drive the event stream once and collect everything we need to score.

    Returns ``{text, thinking, tool_calls, usage, elapsed_ms, error}``.
    """
    text_buf: list[str] = []
    thinking_buf: list[str] = []
    tool_calls: list[dict] = []
    usage: UsageInfo | None = None
    err: str | None = None

    started = time.perf_counter()
    try:
        for event in llm.stream_events(messages, stream=True, system=system):
            if isinstance(event, TextDelta):
                text_buf.append(event.text)
            elif isinstance(event, ThinkingDelta):
                thinking_buf.append(event.text)
            elif isinstance(event, ToolUse):
                tool_calls.append({"name": event.name, "input": event.input})
            elif isinstance(event, UsageInfo):
                usage = event
            elif isinstance(event, ProviderError):
                err = event.message
            elif isinstance(event, FinishReason):
                pass
    except Exception as exc:  # noqa: BLE001
        err = f"runner exception: {exc}"

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "text": "".join(text_buf),
        "thinking": "".join(thinking_buf),
        "tool_calls": tool_calls,
        "usage": usage,
        "elapsed_ms": elapsed_ms,
        "error": err,
    }


def _tool_calls_for_scoring(response_text: str, native_calls: list[dict]) -> list[dict]:
    """Merge native ``tool_use`` events + markdown ``python_waapi`` blocks.

    Both shapes count for ``expected_tool == 'waapi_python_exec'``: native
    calls preserve their own name (when the model uses real tools), while
    code blocks are wrapped as ``waapi_python_exec`` synthetic calls.
    """
    out = list(native_calls)
    blocks = extract_code_blocks(response_text) + extract_pseudo_tool_code_blocks(response_text)
    for b in blocks:
        if b.get("language") in {"python_waapi", "python"}:
            out.append({"name": "waapi_python_exec", "input": {"code": b.get("code", "")}})
    return out


def _print_per_task(score: TaskScore, raw: dict, verbose: bool) -> None:
    status = "PASS" if score.passed else "FAIL"
    elapsed = raw.get("elapsed_ms", 0)
    print(
        f"[{status}] {score.task_id:32}  tool={score.tool_match:.0f}  "
        f"signal={score.signal_recall:.2f}  forbid={score.forbidden_avoidance:.0f}  "
        f"{elapsed}ms"
    )
    if not score.passed or verbose:
        if score.missing_signals:
            print(f"        missing: {score.missing_signals}")
        if score.found_forbidden:
            print(f"        FORBIDDEN: {score.found_forbidden}")
        if raw.get("error"):
            print(f"        error: {raw['error']}")
    if verbose:
        preview = (raw.get("text") or "")[:240].replace("\n", " ")
        print(f"        text: {preview}")
        if raw.get("tool_calls"):
            for tc in raw["tool_calls"]:
                code = (tc.get("input") or {}).get("code", "")
                print(f"        tool: {tc.get('name')}  code[:120]={code[:120]!r}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AudioMate golden tasks against a real LLM.")
    parser.add_argument("--model", help="Model name (overrides settings.json)")
    parser.add_argument("--api-key", help="API key (overrides settings.json / env)")
    parser.add_argument("--base-url", help="Base URL (overrides settings.json / env)")
    parser.add_argument("--id", action="append", default=[], help="Run only tasks with these ids (repeatable)")
    parser.add_argument("--category", action="append", default=[], help="Run only tasks in these categories (repeatable)")
    parser.add_argument("--limit", type=int, help="Run at most N tasks")
    parser.add_argument("--runs", type=int, default=1, help="Run each task N times (averages pass rate)")
    parser.add_argument("--threshold", type=float, default=0.0, help="Exit non-zero if pass_rate < threshold")
    parser.add_argument("--report", help="Write JSON report to this path")
    parser.add_argument("--verbose", action="store_true", help="Print response previews for every task")
    parser.add_argument("--system-prompt", choices=["minimal", "full"], default="minimal",
                        help="``minimal`` isolates model knowledge; ``full`` loads real AudioMate prompt blocks (not yet wired).")
    args = parser.parse_args()

    api_key, base_url, model = _resolve_credentials(args)
    if not api_key:
        print("ERROR: no API key (set --api-key, $AUDIOMATE_API_KEY, or configure in AudioMate GUI first).", file=sys.stderr)
        return 2

    tasks = load_golden_tasks()
    if args.id:
        keep = set(args.id)
        tasks = [t for t in tasks if t.get("id") in keep]
    if args.category:
        keep = set(args.category)
        tasks = [t for t in tasks if t.get("category") in keep]
    if args.limit:
        tasks = tasks[: args.limit]

    if not tasks:
        print("No tasks selected.", file=sys.stderr)
        return 2

    print(f"Model:    {model}")
    print(f"Base URL: {base_url or '(default)'}")
    print(f"Tasks:    {len(tasks)}  x  {args.runs} run(s)")
    print(f"Prompt:   {args.system_prompt}")
    print("-" * 80)

    llm = LLMService(api_key=api_key, base_url=base_url, model=model)

    all_scores: list[TaskScore] = []
    per_task_records: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read = 0
    total_cache_creation = 0

    for task in tasks:
        # Extract per-task context (mode, connection state)
        ctx = task.get("ctx") or {}
        mode = ctx.get("mode", "Agent Mode")
        connected = ctx.get("waapi_connected", True)

        # Build [REDACTED] with task-specific context
        if args.system_prompt == "full":
            system_prompt = _build_full_prompt(mode=mode, connected=connected)
        else:
            system_prompt = _build_minimal_prompt(mode=mode, connected=connected)

        for run_idx in range(args.runs):
            messages = [{"role": "user", "content": task["user_query"]}]
            raw = _collect_response(llm, messages, system=system_prompt)
            tool_calls = _tool_calls_for_scoring(raw["text"], raw["tool_calls"])
            score = score_task(task, raw["text"], tool_calls=tool_calls)

            if raw["usage"] is not None:
                total_input_tokens += raw["usage"].input_tokens
                total_output_tokens += raw["usage"].output_tokens
                total_cache_read += raw["usage"].cache_read_input_tokens
                total_cache_creation += raw["usage"].cache_creation_input_tokens

            run_label = f"{task['id']}#run{run_idx + 1}" if args.runs > 1 else task["id"]
            all_scores.append(TaskScore(
                task_id=run_label,
                tool_match=score.tool_match,
                signal_recall=score.signal_recall,
                forbidden_avoidance=score.forbidden_avoidance,
                missing_signals=score.missing_signals,
                found_forbidden=score.found_forbidden,
                response_preview=score.response_preview,
            ))
            _print_per_task(all_scores[-1], raw, verbose=args.verbose)

            per_task_records.append({
                "id": task["id"],
                "run": run_idx + 1,
                "category": task.get("category"),
                "passed": score.passed,
                "tool_match": score.tool_match,
                "signal_recall": score.signal_recall,
                "forbidden_avoidance": score.forbidden_avoidance,
                "missing_signals": score.missing_signals,
                "found_forbidden": score.found_forbidden,
                "elapsed_ms": raw["elapsed_ms"],
                "input_tokens": raw["usage"].input_tokens if raw["usage"] else None,
                "output_tokens": raw["usage"].output_tokens if raw["usage"] else None,
                "cache_read_input_tokens": raw["usage"].cache_read_input_tokens if raw["usage"] else None,
                "response_preview": (raw["text"] or "")[:500],
                "tool_calls_count": len(tool_calls),
                "error": raw["error"],
            })

    print("-" * 80)
    stats = summarize(all_scores)
    print(f"Pass rate:         {stats['pass_rate']:.1%}  ({stats['passed']}/{stats['count']})")
    print(f"Avg tool_match:    {stats['avg_tool_match']:.2f}")
    print(f"Avg signal_recall: {stats['avg_signal_recall']:.2f}")
    print(f"Avg forbid_avoid:  {stats['avg_forbidden_avoidance']:.2f}")
    print(f"Tokens:            input={total_input_tokens}  output={total_output_tokens}  "
          f"cache_read={total_cache_read}  cache_creation={total_cache_creation}")

    # Per-category breakdown
    by_cat: dict[str, list[bool]] = {}
    for rec in per_task_records:
        by_cat.setdefault(rec["category"] or "(none)", []).append(rec["passed"])
    print("\nPer category:")
    for cat in sorted(by_cat.keys()):
        results = by_cat[cat]
        rate = sum(results) / len(results) if results else 0
        print(f"  {cat:24}  {rate:.0%}  ({sum(results)}/{len(results)})")

    if args.report:
        report = {
            "model": model,
            "base_url": base_url,
            "system_prompt_mode": args.system_prompt,
            "summary": stats,
            "totals": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cache_read_input_tokens": total_cache_read,
                "cache_creation_input_tokens": total_cache_creation,
            },
            "tasks": per_task_records,
        }
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\nReport written to {args.report}")

    if stats["pass_rate"] < args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
