"""Application data paths — centralised directory resolution.

All user-mutable state (settings, chats, memory, logs, buddy, scheduled
tasks) lives under a single root. In development (running from source) the
root is the project directory; in a frozen (PyInstaller) build the root is
``%LOCALAPPDATA%/AudioMate`` (Windows) or the platform equivalent.

On first launch after the migration, if the old project-root files exist
and the new location is empty, they are **copied** (not moved) so the user
keeps a backup in the repo root until they manually delete it.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _project_root() -> Path:
    """Return the project root (repo root or PyInstaller _MEIPASS parent)."""
    if _is_frozen():
        return Path(os.path.dirname(sys.executable))
    return Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _user_data_root() -> Path:
    """Return the platform-appropriate user data directory.

    - Frozen (installed): ``%LOCALAPPDATA%/AudioMate`` (Windows) or
      ``~/.local/share/AudioMate`` (Linux/Mac).
    - Development (source): project root (preserves current behaviour).
    """
    if not _is_frozen():
        return _project_root()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "AudioMate"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AudioMate"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(xdg) / "AudioMate"


# ---------------------------------------------------------------------------
# Public paths
# ---------------------------------------------------------------------------

DATA_ROOT: Path = _user_data_root()

CHATS_DIR: Path = DATA_ROOT / "chats"
LOGS_DIR: Path = DATA_ROOT / "logs"
MEMORY_DIR: Path = DATA_ROOT / "memory"
KNOWLEDGE_DIR: Path = DATA_ROOT / "knowledge"
SKILLS_DIR: Path = DATA_ROOT / "skills"
PLUGINS_DIR: Path = DATA_ROOT / "plugins"
SETTINGS_FILE: Path = DATA_ROOT / "settings.json"
SCHEDULED_TASKS_FILE: Path = DATA_ROOT / "scheduled_tasks.json"
BUDDY_STATE_FILE: Path = DATA_ROOT / "buddy_state.json"
AUDIO_RULES_FILE: Path = DATA_ROOT / "audio_rules.json"

# Legacy (project-root) paths — used only for migration detection.
_LEGACY_ROOT: Path = _project_root()


# ---------------------------------------------------------------------------
# Auto-migration
# ---------------------------------------------------------------------------

_MIGRATION_MARKER = DATA_ROOT / ".migrated_from_project_root"

_MIGRATE_FILES = [
    ("settings.json", SETTINGS_FILE),
    ("scheduled_tasks.json", SCHEDULED_TASKS_FILE),
    ("buddy_state.json", BUDDY_STATE_FILE),
]

_MIGRATE_DIRS = [
    ("chats", CHATS_DIR),
    ("memory", MEMORY_DIR),
    ("logs", LOGS_DIR),
    ("knowledge", KNOWLEDGE_DIR),
    ("skills", SKILLS_DIR),
    ("plugins", PLUGINS_DIR),
]


def ensure_data_dirs() -> None:
    """Create all required data directories if they don't exist."""
    for d in (DATA_ROOT, CHATS_DIR, LOGS_DIR, MEMORY_DIR):
        d.mkdir(parents=True, exist_ok=True)


def migrate_from_project_root() -> bool:
    """Copy legacy project-root data to the user data directory.

    Returns True if migration was performed. Skips if:
    - Running from source (paths are the same).
    - Migration marker already exists.
    - No legacy files found.
    """
    if not _is_frozen():
        return False
    if _MIGRATION_MARKER.exists():
        return False
    if _LEGACY_ROOT == DATA_ROOT:
        return False

    migrated_anything = False
    ensure_data_dirs()

    for filename, dest in _MIGRATE_FILES:
        src = _LEGACY_ROOT / filename
        if src.is_file() and not dest.exists():
            try:
                shutil.copy2(str(src), str(dest))
                migrated_anything = True
            except Exception:
                pass

    for dirname, dest_dir in _MIGRATE_DIRS:
        src_dir = _LEGACY_ROOT / dirname
        if src_dir.is_dir() and not dest_dir.exists():
            try:
                shutil.copytree(str(src_dir), str(dest_dir))
                migrated_anything = True
            except Exception:
                pass

    if migrated_anything:
        try:
            _MIGRATION_MARKER.write_text("migrated", encoding="utf-8")
        except Exception:
            pass

    return migrated_anything
