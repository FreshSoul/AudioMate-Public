"""Regression: Qt setMarkdown drops CJK inside language-tagged code fences.

Bug: assistant replies containing a fenced code block with a language tag
(```text / ```python) AND CJK content rendered with the Chinese silently
dropped — users reported it as "乱码回复". Root cause is a QTextEdit.setMarkdown
parser defect; the fix strips the cosmetic language tag before rendering.
"""

from __future__ import annotations

import re

import pytest

from src.gui.widgets import _strip_code_fence_language

F = "`" * 3


def _cjk(s: str) -> int:
    return len(re.findall(r"[一-鿿]", s))


def test_strip_removes_language_tag_keeps_fence():
    src = f"{F}text\n树\n{F}"
    out = _strip_code_fence_language(src)
    assert out == f"{F}\n树\n{F}"


def test_strip_leaves_plain_fence_untouched():
    src = f"{F}\ncode\n{F}"
    assert _strip_code_fence_language(src) == src


def test_strip_preserves_inline_code_and_text():
    src = "正文 `inline` 文本，没有围栏"
    assert _strip_code_fence_language(src) == src


def test_strip_handles_multiple_blocks():
    src = f"{F}text\n甲\n{F}\n中间\n{F}python\n乙\n{F}"
    out = _strip_code_fence_language(src)
    assert "text" not in out.split("\n")[0]
    assert "甲" in out and "乙" in out and "中间" in out


def test_cjk_survives_setmarkdown_after_strip(qapp):
    """End-to-end against the real chat message that exposed the bug: render
    through the same path MessageBubble uses and assert no Chinese is lost.

    The trigger is cumulative (several language-tagged CJK code blocks in one
    message), so we use the captured real reply as the fixture rather than a
    synthetic snippet.
    """
    import os

    from PyQt6.QtWidgets import QTextEdit

    fixture = os.path.join(os.path.dirname(__file__), "fixtures_cjk_fence.txt")
    with open(fixture, encoding="utf-8") as fh:
        src = fh.read()

    src_cjk = _cjk(src)
    assert src_cjk > 500, "fixture should carry a large CJK document"

    te = QTextEdit()
    te.setMarkdown(src)
    before = _cjk(te.toPlainText())

    te.setMarkdown(_strip_code_fence_language(src))
    after = _cjk(te.toPlainText())

    # Unfixed path loses the vast majority; fix must recover (near) all of it.
    assert before < src_cjk * 0.2, f"fixture no longer triggers the bug: before={before} src={src_cjk}"
    assert after >= src_cjk * 0.95, f"fix incomplete: after={after} src={src_cjk}"
