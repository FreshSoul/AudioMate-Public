"""Shared pytest fixtures for the AudioMate test suite.

Provides ``qapp`` so widget-touching tests don't have to construct
QApplication themselves, and forces Qt to use the offscreen platform plugin
so the suite is headless (and runnable in CI).
"""

from __future__ import annotations

import os
import sys

import pytest


# Headless Qt — must be set before QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """A session-wide QApplication instance.

    pytest-qt provides its own ``qapp`` fixture, but we declare ours
    explicitly so tests that don't import pytest-qt can still reach it.
    """
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app
