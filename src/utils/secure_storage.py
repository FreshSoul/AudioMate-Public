from __future__ import annotations

import json
import os
import tempfile

try:
    import keyring  # type: ignore
except Exception:
    keyring = None

SERVICE_NAME = "AudioMate.Credentials"
FALLBACK_FILE = os.path.join(os.path.expanduser("~"), ".audiomate_secrets.json")


class SecretStorageError(Exception):
    """Raised when a secret cannot be persisted anywhere."""


def _restrict_permissions(path: str) -> None:
    """Best-effort owner-only permissions for plaintext fallback files."""
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _load_fallback_store(path: str | None = None) -> dict:
    path = path or FALLBACK_FILE
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_fallback_store(data: dict, path: str | None = None) -> None:
    path = path or FALLBACK_FILE
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".secrets-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _restrict_permissions(tmp_path)
        os.replace(tmp_path, path)
        _restrict_permissions(path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def set_secret(key: str, value: str) -> str:
    """Persist a secret and return the backend used: ``keyring`` or ``plaintext``."""
    if keyring:
        try:
            keyring.set_password(SERVICE_NAME, key, value)
            return "keyring"
        except Exception:
            pass
    try:
        data = _load_fallback_store()
        data[key] = value
        _save_fallback_store(data)
        return "plaintext"
    except Exception as exc:
        raise SecretStorageError(
            f"Unable to save secret: keyring is unavailable and plaintext fallback failed ({exc})."
        ) from exc


def is_plaintext_fallback() -> bool:
    """True when the OS keyring package is unavailable."""
    return keyring is None


def get_secret(key: str):
    if keyring:
        try:
            value = keyring.get_password(SERVICE_NAME, key)
        except Exception:
            value = None
        if value is not None:
            return value

    value = _load_fallback_store().get(key)
    if value is not None:
        return value
    return None


def delete_secret(key: str) -> None:
    if keyring:
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except Exception:
            pass

    data = _load_fallback_store()
    if key in data:
        data.pop(key, None)
        try:
            _save_fallback_store(data)
        except Exception:
            pass
