import json
import os
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime

from src.utils.app_paths import (
    CHATS_DIR as _CHATS_DIR,
    DATA_ROOT as _DATA_ROOT,
    SETTINGS_FILE as _SETTINGS_FILE,
    ensure_data_dirs,
    migrate_from_project_root,
)
from src.utils.notification_settings import normalize_notification_settings
from src.pet.store import build_default_pet_settings, seed_default_buddy_pets


# Run one-shot migration from old project-root layout to the user data dir.
# Safe to call repeatedly; no-op on second run.
migrate_from_project_root()
ensure_data_dirs()

# BASE_DIR is kept as a backwards-compatible alias for callers that still
# reach into it; new code should import from src.utils.app_paths directly.
BASE_DIR = str(_DATA_ROOT)
CHATS_DIR = str(_CHATS_DIR)
SETTINGS_FILE = str(_SETTINGS_FILE)


def _atomic_write_json(path: str, data) -> None:
    """Serialize ``data`` to ``path`` atomically.

    Writes to a sibling temp file then ``os.replace`` swaps it into place —
    on POSIX and on NTFS the rename is atomic, so a process kill mid-write
    can never leave the destination half-written. Without this guard,
    settings.json or chats/<id>.json could end up truncated and the next
    launch would fail to parse them.
    """
    target_dir = os.path.dirname(path) or "."
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of the temp file if the swap didn't happen.
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise

DEFAULT_APP_SETTINGS = {
    "theme": "light",
    "notifications": {},
    "plugins": {"items": []},
    "pets": build_default_pet_settings(),
    "buddy_defaults_seeded": False,
    "image_gen": {"model": "gpt-image-2"},
    # Run generated code in an isolated worker process with OS-level
    # restrictions (the secure default). Can be turned off here for debugging.
    "sandbox_process_isolation": True,
    "memory": {
        "enabled": True,
        "auto_inject_user": True,
        "auto_inject_session": True,
        "auto_inject_repo": True,
        "auto_save_session": True,
        "auto_save_repo": True,
        "auto_save_user": False,
        "max_session_records": 80,
        "max_repo_records": 200,
        "max_memory_context_chars": 12000,
    },
}


def normalize_memory_settings(settings):
    source = settings if isinstance(settings, dict) else {}
    defaults = DEFAULT_APP_SETTINGS["memory"]
    normalized = dict(source)
    for key, value in defaults.items():
        normalized.setdefault(key, value)
    return normalized


def normalize_app_settings(settings):
    source = settings if isinstance(settings, dict) else {}
    normalized = dict(source)
    for key, value in DEFAULT_APP_SETTINGS.items():
        if key == "pets":
            continue
        normalized.setdefault(key, deepcopy(value))
    normalized["pets"] = seed_default_buddy_pets(source.get("pets"))
    normalized["buddy_defaults_seeded"] = True
    normalized["notifications"] = normalize_notification_settings(source.get("notifications"))
    normalized["memory"] = normalize_memory_settings(source.get("memory"))
    raw_image_gen = source.get("image_gen") if isinstance(source.get("image_gen"), dict) else {}
    model_val = (raw_image_gen.get("model") or "").strip() or "gpt-image-2"
    normalized["image_gen"] = {"model": model_val}
    return normalized

def ensure_chats_dir():
    if not os.path.exists(CHATS_DIR):
        os.makedirs(CHATS_DIR)

def save_chat(chat_id, title, messages, *, llm_messages=None):
    ensure_chats_dir()
    file_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    data = {
        "id": chat_id,
        "title": title,
        "updated_at": datetime.now().isoformat(),
        "messages": messages
    }
    if llm_messages is not None:
        data["llm_messages"] = llm_messages
    _atomic_write_json(file_path, data)

def load_chat(chat_id):
    file_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def delete_chat(chat_id):
    file_path = os.path.join(CHATS_DIR, f"{chat_id}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
        return True
    return False

def list_chats():
    ensure_chats_dir()
    chats = []
    for filename in os.listdir(CHATS_DIR):
        if filename.endswith(".json"):
            try:
                with open(os.path.join(CHATS_DIR, filename), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    chats.append({
                        "id": data.get("id"),
                        "title": data.get("title", "Untitled Chat"),
                        "updated_at": data.get("updated_at", "")
                    })
            except (OSError, ValueError, json.JSONDecodeError):
                # Corrupt/unreadable chat files shouldn't break the sidebar
                # listing; KeyboardInterrupt/SystemExit must still propagate.
                continue
    # Sort by updated_at desc
    chats.sort(key=lambda x: x["updated_at"], reverse=True)
    return chats

def create_new_chat():
    chat_id = str(uuid.uuid4())
    return chat_id


def load_app_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return normalize_app_settings(data)
        except Exception as e:
            print(f"[Settings] Failed to load {SETTINGS_FILE}: {e}")
    return normalize_app_settings({})


def save_app_settings(settings):
    if not isinstance(settings, dict):
        return False
    try:
        _atomic_write_json(SETTINGS_FILE, settings)
        return True
    except Exception:
        return False
