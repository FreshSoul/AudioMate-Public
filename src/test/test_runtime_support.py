"""Unit tests for sub-agent code-loop helpers in runtime_support."""

import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Skip the Qt-heavy import surface; import only what we need by referencing
# the runtime_support module after the PyQt6 stub is in place. The two helpers
# we test are pure-Python.
from src.gui.runtime_support import (
    _extract_python_block,
    _make_restricted_plugin_call,
    _make_guarded_import,
    _DEFAULT_ALLOWED_IMPORTS,
)


# ---------------------------------------------------------------------------
# _extract_python_block
# ---------------------------------------------------------------------------


def test_extract_python_block_single_python_fence():
    text = "Sure.\n```python\nx = 1\nprint(x)\n```\nDone."
    assert _extract_python_block(text) == "x = 1\nprint(x)"


def test_extract_python_block_py_alias():
    text = "before\n```py\nprint(\"hi\")\n```\nafter"
    assert _extract_python_block(text) == 'print("hi")'


def test_extract_python_block_returns_first_when_multiple():
    text = "```python\nfirst()\n```\nmid\n```python\nsecond()\n```"
    assert _extract_python_block(text) == "first()"


def test_extract_python_block_bare_block_only_when_unique():
    text = "talk\n```\nplain = 1\n```\nmore"
    assert _extract_python_block(text) == "plain = 1"
    # Two bare blocks → ambiguous, returns None.
    text2 = "```\na = 1\n```\n```\nb = 2\n```"
    assert _extract_python_block(text2) is None


def test_extract_python_block_none_when_no_block():
    assert _extract_python_block("Just talking, no code here.") is None
    assert _extract_python_block("") is None
    assert _extract_python_block(None) is None


# ---------------------------------------------------------------------------
# _make_restricted_plugin_call
# ---------------------------------------------------------------------------


class _FakePluginRuntime:
    def __init__(self, by_plugin):
        # by_plugin: {plugin_id: [tool_name, ...]}
        self._by_plugin = by_plugin
        self.last_call = None

    def list_tools(self, allowed_plugin_ids=None):
        out = []
        for pid, tools in self._by_plugin.items():
            if allowed_plugin_ids is not None and pid not in allowed_plugin_ids:
                continue
            for name in tools:
                out.append({"name": name, "plugin": pid})
        return out

    def call_tool(self, name, input_data=None, mode="Agent Mode"):
        self.last_call = (name, input_data, mode)
        return {"ok": True, "echoed": input_data}


def test_restricted_call_rejects_unbound_tool():
    rt = _FakePluginRuntime({"p1": ["plugin.p1.foo"], "p2": ["plugin.p2.bar"]})
    call = _make_restricted_plugin_call(rt, allowed_plugin_ids={"p1"})
    try:
        call("plugin.p2.bar", {})
    except PermissionError as exc:
        assert "plugin.p2.bar" in str(exc)
    else:
        raise AssertionError("expected PermissionError for unbound tool")


def test_restricted_call_passes_bound_tool_to_runtime():
    rt = _FakePluginRuntime({"p1": ["plugin.p1.foo"]})
    call = _make_restricted_plugin_call(rt, allowed_plugin_ids={"p1"})
    result = call("plugin.p1.foo", {"x": 1})
    assert result == {"ok": True, "echoed": {"x": 1}}
    assert rt.last_call == ("plugin.p1.foo", {"x": 1}, "Agent Mode")


def test_restricted_call_with_empty_allowed_rejects_everything():
    rt = _FakePluginRuntime({"p1": ["plugin.p1.foo"]})
    call = _make_restricted_plugin_call(rt, allowed_plugin_ids=set())
    try:
        call("plugin.p1.foo", {})
    except PermissionError:
        pass
    else:
        raise AssertionError("empty allow-list should reject every tool")


def test_restricted_call_coerces_non_dict_input_to_dict():
    rt = _FakePluginRuntime({"p1": ["plugin.p1.foo"]})
    call = _make_restricted_plugin_call(rt, allowed_plugin_ids={"p1"})
    call("plugin.p1.foo", "not a dict")
    assert rt.last_call[1] == {}


# ---------------------------------------------------------------------------
# _make_guarded_import
# ---------------------------------------------------------------------------


def test_guarded_import_passes_whitelisted_without_asking():
    calls = []
    def ask(name):
        calls.append(name)
        return False  # would deny if invoked
    allowed = set(_DEFAULT_ALLOWED_IMPORTS)
    guarded = _make_guarded_import(allowed, ask)
    # json is in the default whitelist → no prompt, returns the real module.
    mod = guarded("json")
    assert mod.__name__ == "json"
    assert calls == []


def test_guarded_import_asks_user_for_unknown_and_caches():
    ask_count = {"n": 0}
    def ask(name):
        ask_count["n"] += 1
        return True
    allowed = set(_DEFAULT_ALLOWED_IMPORTS)
    # textwrap is a stdlib module deliberately NOT in the default whitelist.
    assert "textwrap" not in allowed
    guarded = _make_guarded_import(allowed, ask)
    first = guarded("textwrap")
    assert first.__name__ == "textwrap"
    assert ask_count["n"] == 1
    # Second import of the same module must NOT re-prompt.
    second = guarded("textwrap")
    assert second.__name__ == "textwrap"
    assert ask_count["n"] == 1


def test_guarded_import_raises_when_user_denies():
    def deny(_name):
        return False
    allowed = set(_DEFAULT_ALLOWED_IMPORTS)
    guarded = _make_guarded_import(allowed, deny)
    try:
        guarded("textwrap")
    except ImportError as exc:
        assert "denied" in str(exc).lower() and "textwrap" in str(exc)
    else:
        raise AssertionError("expected ImportError when user denies")


def test_guarded_import_with_none_callback_denies_unknown():
    allowed = set(_DEFAULT_ALLOWED_IMPORTS)
    guarded = _make_guarded_import(allowed, None)
    try:
        guarded("textwrap")
    except ImportError:
        pass
    else:
        raise AssertionError("expected ImportError when callback is None")


if __name__ == "__main__":  # pragma: no cover — manual run helper
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        fn()
    print("OK")
