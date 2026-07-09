import json
import os
import stat
import sys

import pytest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.utils.secure_storage as ss


@pytest.fixture
def isolated_fallback(tmp_path, monkeypatch):
    """Point the plaintext fallback at a temp file and force keyring off."""
    fallback = tmp_path / ".audiomate_secrets.json"
    monkeypatch.setattr(ss, "FALLBACK_FILE", str(fallback), raising=False)
    monkeypatch.setattr(ss, "keyring", None, raising=False)
    return fallback


def test_plaintext_fallback_round_trips_and_reports_backend(isolated_fallback):
    """P0-3: when keyring is unavailable, set_secret persists to the plaintext
    fallback and reports the 'plaintext' backend so the GUI can warn."""
    backend = ss.set_secret("API_KEY", "sk-secret-123")
    assert backend == "plaintext"
    assert ss.is_plaintext_fallback() is True
    assert ss.get_secret("API_KEY") == "sk-secret-123"
    assert isolated_fallback.is_file()
    data = json.loads(isolated_fallback.read_text(encoding="utf-8"))
    assert data["API_KEY"] == "sk-secret-123"


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only: Windows os.chmod cannot set 0600")
def test_fallback_file_is_owner_only_on_posix(isolated_fallback):
    """P0-3: the plaintext secrets file must be chmod 0600 (owner-only) on POSIX."""
    ss.set_secret("API_KEY", "sk-secret-123")
    mode = stat.S_IMODE(os.stat(isolated_fallback).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_set_secret_raises_when_persist_fails(tmp_path, monkeypatch):
    """P0-3: a total persist failure must raise SecretStorageError (not be
    swallowed), so the user is never told a key was saved when it wasn't."""
    monkeypatch.setattr(ss, "keyring", None, raising=False)
    # Point the fallback into a path whose parent directory does not exist,
    # so mkstemp(dir=...) fails.
    bad = tmp_path / "missing_dir" / "secrets.json"
    monkeypatch.setattr(ss, "FALLBACK_FILE", str(bad), raising=False)
    with pytest.raises(ss.SecretStorageError):
        ss.set_secret("K", "v")


def test_keyring_path_reports_keyring_backend(tmp_path, monkeypatch):
    """P0-3: when a keyring backend works, set_secret uses it and reports it."""
    class FakeKeyring:
        def __init__(self):
            self.store = {}

        def set_password(self, service, key, value):
            self.store[(service, key)] = value

        def get_password(self, service, key):
            return self.store.get((service, key))

    monkeypatch.setattr(ss, "keyring", FakeKeyring(), raising=False)
    assert ss.set_secret("X", "y") == "keyring"
    assert ss.is_plaintext_fallback() is False


def test_keyring_failure_falls_back_to_plaintext(isolated_fallback, monkeypatch):
    """P0-3: a keyring backend that raises must NOT crash — it falls back to
    the plaintext store."""
    class BadKeyring:
        def set_password(self, *a, **k):
            raise RuntimeError("no usable backend")

        def get_password(self, *a, **k):
            return None

    monkeypatch.setattr(ss, "keyring", BadKeyring(), raising=False)
    assert ss.set_secret("Z", "z") == "plaintext"
    assert ss.get_secret("Z") == "z"


def test_delete_secret_clears_plaintext_fallback_when_keyring_exists(tmp_path, monkeypatch):
    fallback = tmp_path / ".audiomate_secrets.json"
    monkeypatch.setattr(ss, "FALLBACK_FILE", str(fallback), raising=False)

    class FakeKeyring:
        def delete_password(self, *a, **k):
            raise RuntimeError("missing")

        def get_password(self, *a, **k):
            return None

    fallback.write_text(json.dumps({"API_KEY": "sk-secret-123"}), encoding="utf-8")
    monkeypatch.setattr(ss, "keyring", FakeKeyring(), raising=False)

    ss.delete_secret("API_KEY")

    assert json.loads(fallback.read_text(encoding="utf-8")) == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
