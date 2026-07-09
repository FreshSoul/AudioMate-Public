"""Prepare the standalone CPython runtime that REAPER's ReaScript engine loads.

WHY THIS EXISTS
---------------
REAPER loads ``pythonlibdll`` *directly into its own process* as the ReaScript
interpreter. AudioMate must therefore hand REAPER a real, self-contained,
embeddable CPython — NOT its own PyInstaller-frozen ``python3XX.dll`` /
``_internal`` directory. The frozen interpreter borrows its CRT/loader
dependencies from the host system; on Windows 11 that borrowing fails at the
native level and REAPER hard-crashes (闪退) the moment the bootstrap script
runs ``import reapy``. Windows 10 only "worked" by luck of compatible system
DLLs. See src/services/reaper_setup.py and src/test/test_reaper_setup.py.

This script populates ``runtime/reaper-python/`` with the official Python 3.11
*embeddable* package plus ``python-reapy``. The result is a local build artifact:
it is ignored by Git and must not be committed to the open-source repository.
Packaged releases may bundle the generated runtime, or distributors may provide
it separately as a release asset, with the applicable third-party notices.

reapy 0.10.0 is clean on Python 3.11, so the bootstrap no longer needs the
3.13 ``CaseInsensitiveDict`` monkeypatch.

USAGE
-----
    python scripts/prepare_reaper_runtime.py            # download + populate
    python scripts/prepare_reaper_runtime.py --verify   # just check the result

Re-running is idempotent: it wipes and rebuilds ``runtime/reaper-python/``.
Requires network access to python.org and PyPI.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


PY_VERSION = "3.11.9"
PY_TAG = "311"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
REAPY_SPEC = "python-reapy==0.10.0"

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "runtime" / "reaper-python"
SITE_PACKAGES = RUNTIME_DIR / "Lib" / "site-packages"


def _download(url: str) -> bytes:
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def populate() -> None:
    if RUNTIME_DIR.exists():
        print(f"removing existing {RUNTIME_DIR}")
        shutil.rmtree(RUNTIME_DIR)
    RUNTIME_DIR.mkdir(parents=True)

    # 1) Official embeddable CPython — self-contained, ships vcruntime140.dll.
    print(f"[1/4] unpacking Python {PY_VERSION} embeddable")
    with zipfile.ZipFile(io.BytesIO(_download(EMBED_URL))) as zf:
        zf.extractall(RUNTIME_DIR)

    # 2) Enable ``site`` so Lib/site-packages (and thus reapy) is importable.
    #    The embeddable build ships pythonXX._pth with site disabled.
    pth = RUNTIME_DIR / f"python{PY_TAG}._pth"
    print(f"[2/4] enabling site in {pth.name}")
    lines = pth.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.strip() == "#import site":
            out.append("import site")
        else:
            out.append(line)
    if "Lib\\site-packages" not in "\n".join(out):
        out.append("Lib\\site-packages")
    pth.write_text("\n".join(out) + "\n", encoding="utf-8")
    SITE_PACKAGES.mkdir(parents=True, exist_ok=True)

    # 3) Bootstrap pip into THIS embeddable interpreter, then 4) install reapy
    #    into Lib/site-packages. reapy is pure-Python, so --target is safe.
    print("[3/4] bootstrapping pip")
    get_pip = RUNTIME_DIR / "get-pip.py"
    get_pip.write_bytes(_download(GET_PIP_URL))
    runtime_python = RUNTIME_DIR / "python.exe"
    subprocess.run([str(runtime_python), str(get_pip), "--no-warn-script-location"], check=True)

    print(f"[4/4] installing {REAPY_SPEC}")
    subprocess.run(
        [str(runtime_python), "-m", "pip", "install", REAPY_SPEC,
         "--target", str(SITE_PACKAGES), "--no-warn-script-location"],
        check=True,
    )
    get_pip.unlink(missing_ok=True)

    # Trim dev-only tooling REAPER never imports (pip/setuptools/wheel were
    # only needed to install reapy). Keeps the committed runtime lean.
    _trim_dev_tooling()
    print("done.")


def _trim_dev_tooling() -> None:
    print("  trimming pip/setuptools/wheel (not needed by REAPER)")
    patterns = ["pip", "pip-*", "setuptools", "setuptools-*", "_distutils_hack",
                "wheel", "wheel-*", "pkg_resources", "distutils-precedence.pth",
                "packaging", "packaging-*"]
    for base in (SITE_PACKAGES, RUNTIME_DIR / "Scripts"):
        if not base.exists():
            continue
        for pattern in patterns:
            for path in base.glob(pattern):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
    scripts_dir = RUNTIME_DIR / "Scripts"
    if scripts_dir.exists() and not any(scripts_dir.iterdir()):
        scripts_dir.rmdir()


def verify() -> bool:
    ok = True
    dll = RUNTIME_DIR / f"python{PY_TAG}.dll"
    stdlib = RUNTIME_DIR / f"python{PY_TAG}.zip"
    reapy_pkg = SITE_PACKAGES / "reapy"
    for label, path in (("python DLL", dll), ("stdlib zip", stdlib), ("reapy package", reapy_pkg)):
        present = path.exists()
        print(f"  {'OK ' if present else 'MISSING'} {label}: {path}")
        ok = ok and present
    if (RUNTIME_DIR / "base_library.zip").exists():
        print("  ERROR: base_library.zip present — looks like a frozen dir, not embeddable!")
        ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="only verify, do not download")
    args = parser.parse_args()
    if not args.verify:
        populate()
    print("verifying runtime/reaper-python:")
    ok = verify()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
