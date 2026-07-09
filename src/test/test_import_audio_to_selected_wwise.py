import os
import sys
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.tools import create_default_registry
from src.utils.agent_tools import AgentToolbox


class FakeWaapiClient:
    def __init__(self):
        self.calls = []
        self.connected = True

    def get_selected_objects(self):
        return {
            "objects": [
                {
                    "id": "{11111111-2222-3333-4444-555555555555}",
                    "name": "Selected Folder",
                    "type": "Folder",
                    "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Selected Folder",
                }
            ]
        }

    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        return {
            "files": [r"C:\Project\Originals\SFX\Region_01.wav"],
            "objects": [
                {
                    "id": "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}",
                    "name": "Region_01",
                    "type": "Sound SFX",
                    "path": "\\Actor-Mixer Hierarchy\\Default Work Unit\\Selected Folder\\Region_01",
                }
            ],
            "log": [],
        }


class FakeWaapiApplicationError(Exception):
    def __init__(self, message, log):
        super().__init__(message)
        self.kwargs = {"message": message, "details": {"log": log, "procedureUri": "ak.wwise.core.audio.import"}}


class FakeCopyFailureWaapiClient(FakeWaapiClient):
    def call(self, uri, args=None, options=None):
        self.calls.append((uri, args, options))
        if len(self.calls) == 1:
            raise FakeWaapiApplicationError(
                "content has errors, see details for more information",
                [{"message": "Copy file to originals folder failed. : Region_01.wav", "severity": "Error"}],
            )
        return {
            "files": [r"C:\Project\Originals\SFX\Region_01.wav"],
            "objects": [{"id": "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}", "name": "Region_01"}],
            "log": [],
        }


def test_default_registry_exposes_import_tool():
    registry = create_default_registry()
    assert registry.find_tool("import_audio_files_to_selected_wwise") is not None
    print("test_default_registry_exposes_import_tool: OK")


def test_import_audio_files_to_selected_wwise_builds_audio_import_payload():
    fake = FakeWaapiClient()
    toolbox = AgentToolbox(parent_widget=None, waapi_client=fake)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = os.path.join(tmp, "Region:01.wav")
        txt_path = os.path.join(tmp, "notes.txt")
        with open(wav_path, "wb") as handle:
            handle.write(b"RIFF....WAVE")
        with open(txt_path, "w", encoding="utf-8") as handle:
            handle.write("not audio")

        result = toolbox.import_audio_files_to_selected_wwise([wav_path, txt_path, os.path.join(tmp, "missing.wav")])

    assert result["ok"] is True
    assert result["target"]["id"] == "{11111111-2222-3333-4444-555555555555}"
    assert len(fake.calls) == 1
    uri, args, options = fake.calls[0]
    assert uri == "ak.wwise.core.audio.import"
    assert args["importOperation"] == "useExisting"
    assert args["default"]["importLocation"] == "{11111111-2222-3333-4444-555555555555}"
    assert args["default"]["importLanguage"] == "SFX"
    assert args["imports"][0]["audioFile"].endswith("Region:01.wav")
    assert args["imports"][0]["objectPath"] == "Region_01"
    assert args["imports"][0]["objectType"] == "Sound SFX"
    assert options["return"] == ["id", "name", "type", "path", "originalFilePath"]
    assert len(result["skipped"]) == 2
    print("test_import_audio_files_to_selected_wwise_builds_audio_import_payload: OK")


def test_import_audio_files_to_selected_wwise_retries_copy_failures():
    fake = FakeCopyFailureWaapiClient()
    toolbox = AgentToolbox(parent_widget=None, waapi_client=fake)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = os.path.join(tmp, "Region_01.wav")
        with open(wav_path, "wb") as handle:
            handle.write(b"RIFF....WAVE")

        result = toolbox.import_audio_files_to_selected_wwise(
            [wav_path],
            file_ready_timeout=1,
            batch_size=10,
            retry_on_copy_failure=True,
        )

    assert result["ok"] is True
    assert len(fake.calls) == 2
    assert result["imported_count"] == 1
    print("test_import_audio_files_to_selected_wwise_retries_copy_failures: OK")


if __name__ == "__main__":
    test_default_registry_exposes_import_tool()
    test_import_audio_files_to_selected_wwise_builds_audio_import_payload()
    test_import_audio_files_to_selected_wwise_retries_copy_failures()
