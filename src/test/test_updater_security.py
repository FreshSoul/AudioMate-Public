import os
import sys
import zipfile

import pytest

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services import updater


@pytest.mark.parametrize("member_name", ["../evil.txt", "..\\evil.txt", "C:/evil.txt"])
def test_extract_rejects_unsafe_zip_member_paths(tmp_path, member_name):
    zip_path = tmp_path / "update.zip"
    target_dir = tmp_path / "target"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(member_name, "bad")

    with pytest.raises(RuntimeError, match="Unsafe update package path"):
        updater._extract(str(zip_path), str(target_dir))

    assert not (tmp_path / "evil.txt").exists()
