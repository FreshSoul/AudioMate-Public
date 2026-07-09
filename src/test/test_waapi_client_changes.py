"""Regression tests for WwiseClient change tracking."""

import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.waapi.client import WwiseClient


class FakeWaapiBackend:
    def __init__(self, result=None, exc=None):
        self.result = result if result is not None else {}
        self.exc = exc
        self.calls = []

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if self.exc:
            raise self.exc
        return self.result


def make_client(fake_backend):
    client = WwiseClient()
    client.connected = True
    client.client = fake_backend
    client.reset_changes()
    return client


client = make_client(FakeWaapiBackend(result={"return": []}))
client.call("ak.wwise.core.object.get", {"from": {"ofType": ["Sound"]}})
assert client.has_changes is False

client = make_client(FakeWaapiBackend(result={"id": "created"}))
client.call("ak.wwise.core.object.create", {"parent": "{00000000-0000-0000-0000-000000000000}", "type": "Sound", "name": "S"})
assert client.has_changes is True

client = make_client(FakeWaapiBackend(result={"id": "created"}))
result = client.call("ak.wwise.core.object.create", {"parent": "", "type": "Sound", "name": "S"})
assert result.get("error")
assert client.has_changes is False

client = make_client(FakeWaapiBackend(exc=RuntimeError("boom")))
result = client.call("ak.wwise.core.object.create", {"parent": "{00000000-0000-0000-0000-000000000000}", "type": "Sound", "name": "S"})
assert result.get("error") == "boom"
assert client.has_changes is False

client = make_client(FakeWaapiBackend(result={"error": "invalid_arguments"}))
result = client.call("ak.wwise.core.object.create", {"parent": "{00000000-0000-0000-0000-000000000000}", "type": "Sound", "name": "S"})
assert result.get("error") == "invalid_arguments"
assert client.has_changes is False

print("test_waapi_client_changes: OK")
