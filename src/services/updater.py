"""Self-update support for packaged Windows releases.

The update repository is intentionally not hard-coded for the open-source tree.
Set ``AUDIOMATE_UPDATE_REPOSITORY=owner/repo`` to enable GitHub release checks.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import json
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Callable, Optional

from src.__version__ import __version__ as CURRENT_VERSION

UPDATE_REPOSITORY = os.environ.get("AUDIOMATE_UPDATE_REPOSITORY", "").strip()
if "/" in UPDATE_REPOSITORY:
    GITHUB_OWNER, GITHUB_REPO = UPDATE_REPOSITORY.split("/", 1)
else:
    GITHUB_OWNER, GITHUB_REPO = "", ""
LATEST_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest" if GITHUB_OWNER else ""
LIST_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page=20" if GITHUB_OWNER else ""
ATOM_FEED = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases.atom" if GITHUB_OWNER else ""
DOWNLOAD_BASE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download" if GITHUB_OWNER else ""
RELEASE_PAGE_BASE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag" if GITHUB_OWNER else ""
ASSET_NAME_RE = re.compile(r"AudioMate-v?[\d.]+-win64\.zip$", re.IGNORECASE)
EXPECTED_ASSET_TEMPLATE = "AudioMate-{tag}-win64.zip"  # tag already includes the v prefix

# Last fetch failure, used by the UI for diagnostics.
last_error: str = ""

# ProgressCallback(stage: str, current: int, total: int)
ProgressCallback = Callable[[str, int, int], None]


# ---------------------------------------------------------------------------
# Release metadata returned by GitHub.
# ---------------------------------------------------------------------------
@dataclass
class ReleaseInfo:
    version: str            # version without leading v, e.g. "1.0.4"
    tag: str                # original tag, e.g. "v1.0.4"
    name: str               # release title
    body: str               # release notes in Markdown
    asset_url: str          # direct zip download URL
    asset_size: int         # asset size in bytes
    html_url: str           # release page URL
    # sha256 of the zip asset, in lowercase hex. Best-effort: present when
    # GitHub returns ``digest`` on the asset OR when a sibling ``<asset>.sha256``
    # text file exists in the same release. Empty string when neither is
    # available; in that case the updater downloads with no integrity check,
    # which we then log loudly.
    asset_sha256: str = ""


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------
def _parse_version(s: str) -> tuple:
    s = s.strip().lstrip("vV")
    parts = re.split(r"[.\-+]", s)
    out = []
    for p in parts:
        if p.isdigit():
            out.append(int(p))
        else:
            # Treat prerelease/build suffixes as 0 for conservative ordering.
            out.append(0)
    return tuple(out) or (0,)


def is_newer(remote: str, local: str = CURRENT_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(local)


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
def _http_get_json(url: str, timeout: float):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"AudioMate-Updater/{CURRENT_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_release_info(data: dict) -> Optional[ReleaseInfo]:
    tag = data.get("tag_name") or ""
    if not tag:
        return None

    # Prefer the expected Windows zip asset; fall back to the first zip asset.
    asset_url = ""
    asset_size = 0
    asset_digest_raw = ""
    fallback = None
    fallback_digest_raw = ""
    sha256_urls: dict[str, str] = {}
    for a in data.get("assets") or []:
        name = a.get("name") or ""
        url = a.get("browser_download_url") or ""
        size = int(a.get("size") or 0)
        digest = str(a.get("digest") or "")  # GitHub 2024+: "sha256:abcd..."
        if not url:
            continue
        if name.lower().endswith(".sha256"):
            # 'AudioMate-v1.2.3-win64.zip.sha256' -> match on the zip name
            sha256_urls[name[: -len(".sha256")]] = url
            continue
        if ASSET_NAME_RE.search(name):
            asset_url, asset_size, asset_digest_raw = url, size, digest
            asset_name = name
            break
        if fallback is None and name.lower().endswith(".zip"):
            fallback = (url, size, name)
            fallback_digest_raw = digest
    else:
        asset_name = ""
    if not asset_url and fallback:
        asset_url, asset_size, asset_name = fallback
        asset_digest_raw = fallback_digest_raw

    if not asset_url:
        return None

    asset_sha256 = _parse_digest_hex(asset_digest_raw, "sha256")
    if not asset_sha256 and asset_name and asset_name in sha256_urls:
        asset_sha256 = _fetch_sha256_sidecar(sha256_urls[asset_name])

    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        name=data.get("name") or tag,
        body=data.get("body") or "",
        asset_url=asset_url,
        asset_size=asset_size,
        html_url=data.get("html_url") or "",
        asset_sha256=asset_sha256,
    )


def _parse_digest_hex(digest: str, algorithm: str) -> str:
    """Extract ``hex`` from an ``algorithm:hex`` string. Empty on mismatch."""
    if not digest or ":" not in digest:
        return ""
    algo, _, hex_part = digest.partition(":")
    if algo.strip().lower() != algorithm:
        return ""
    candidate = hex_part.strip().lower()
    return candidate if re.fullmatch(r"[0-9a-f]+", candidate or "") else ""


def _fetch_sha256_sidecar(url: str, timeout: float = 10.0) -> str:
    """Read a ``.sha256`` sidecar file. Returns lowercase hex or empty."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"AudioMate-Updater/{CURRENT_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read(4096).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    # Sidecar formats: '<hex>' or '<hex>  <filename>' (sha256sum output).
    first = text.split()[0] if text else ""
    candidate = first.lower()
    return candidate if re.fullmatch(r"[0-9a-f]{64}", candidate or "") else ""


def fetch_latest_release(timeout: float = 10.0) -> Optional[ReleaseInfo]:
    """Fetch the latest release metadata from GitHub."""
    global last_error
    last_error = ""
    if not LATEST_API or not LIST_API:
        last_error = "Update repository is not configured. Set AUDIOMATE_UPDATE_REPOSITORY=owner/repo to enable updates."
        return None

    # --- 1) /releases/latest ----------------------------------------------
    try:
        data = _http_get_json(LATEST_API, timeout)
        info = _build_release_info(data)
        if info:
            return info
        last_error = "latest release does not contain a usable zip asset."
    except urllib.error.HTTPError as e:
        # 404 usually means no latest release; fall back to the release list.
        if e.code != 404:
            last_error = f"HTTP {e.code} {e.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        last_error = f"Network error: {e}"
    except (ValueError, KeyError) as e:
        last_error = f"Response parse failed: {e}"

    # --- 2) /releases list fallback ----------------------------------------
    try:
        items = _http_get_json(LIST_API, timeout)
    except urllib.error.HTTPError as e:
        last_error = last_error or f"HTTP {e.code} {e.reason}"
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        last_error = last_error or f"Network error: {e}"
        return None
    except (ValueError, KeyError) as e:
        last_error = last_error or f"Response parse failed: {e}"
        return None

    if not isinstance(items, list) or not items:
        last_error = last_error or "Repository has no releases."
        return None

    # Skip drafts, keep prereleases, and choose the highest semantic version.
    candidates: list[tuple[tuple, dict]] = []
    for it in items:
        if it.get("draft"):
            continue
        tag = it.get("tag_name") or ""
        if not tag:
            continue
        candidates.append((_parse_version(tag), it))
    if not candidates:
        last_error = last_error or "Repository contains only draft releases."
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    for _, data in candidates:
        info = _build_release_info(data)
        if info:
            return info
    last_error = last_error or "No release zip asset matched AudioMate-vX.Y.Z-win64.zip."
    return None


# --- Atom feed fallback -----------------------------------------------------
_ATOM_TAG_RE = re.compile(
    r"<entry>.*?<id>tag:github\.com,\d+:Repository/\d+/(?P<tag>[^<]+)</id>",
    re.DOTALL,
)


def fetch_latest_via_atom(timeout: float = 10.0) -> Optional[ReleaseInfo]:
    """Resolve the latest release from the public GitHub releases Atom feed."""
    global last_error
    if not ATOM_FEED or not DOWNLOAD_BASE or not RELEASE_PAGE_BASE:
        last_error = last_error or "Update repository is not configured."
        return None
    req = urllib.request.Request(
        ATOM_FEED,
        headers={"User-Agent": f"AudioMate-Updater/{CURRENT_VERSION}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        last_error = last_error or f"Atom fallback failed: {e}"
        return None

    tags: list[tuple[tuple, str]] = []
    for m in _ATOM_TAG_RE.finditer(text):
        t = (m.group("tag") or "").strip()
        if t:
            tags.append((_parse_version(t), t))
    if not tags:
        last_error = last_error or "Atom fallback did not contain a release tag."
        return None
    tags.sort(key=lambda x: x[0], reverse=True)
    tag = tags[0][1]

    asset_name = EXPECTED_ASSET_TEMPLATE.format(tag=tag)
    asset_url = f"{DOWNLOAD_BASE}/{tag}/{asset_name}"
    return ReleaseInfo(
        version=tag.lstrip("vV"),
        tag=tag,
        name=tag,
        body="GitHub API access was limited, so the version was resolved from the public releases feed. Open the release page for details.",
        asset_url=asset_url,
        asset_size=0,
        html_url=f"{RELEASE_PAGE_BASE}/{tag}",
    )


def fetch_latest_release_with_fallback(timeout: float = 10.0) -> Optional[ReleaseInfo]:
    """Prefer the GitHub API and fall back to the Atom feed."""
    info = fetch_latest_release(timeout=timeout)
    if info:
        return info
    return fetch_latest_via_atom(timeout=timeout)



def check_for_update() -> Optional[ReleaseInfo]:
    """Return release info only when a newer version is available."""
    info = fetch_latest_release_with_fallback()
    if info and is_newer(info.version):
        return info
    return None


# ---------------------------------------------------------------------------
# Download and installation
# ---------------------------------------------------------------------------
def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _install_dir() -> str:
    """Return the installation directory for frozen builds or the repo root in development."""
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root (src/services -> repo)


class IntegrityError(RuntimeError):
    """Raised when a downloaded asset fails hash verification."""


def download_asset(info: ReleaseInfo, dest_dir: str,
                   progress: Optional[ProgressCallback] = None) -> str:
    """Download an update zip, verify it when possible, and return its path.

    The asset is written to ``<file>.part`` first. If a sha256 digest is
    available, the partial file is verified before being promoted to the final
    zip path. Without an upstream digest this still downloads over HTTPS, but
    logs the computed hash so operators can audit the release.
    """
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, f"AudioMate-{info.tag}.zip")
    part_path = zip_path + ".part"

    # Clear any prior partial / stale final file so we never extract a
    # truncated leftover.
    for stale in (part_path, zip_path):
        if os.path.exists(stale):
            try:
                os.remove(stale)
            except OSError:
                pass

    req = urllib.request.Request(
        info.asset_url,
        headers={"User-Agent": f"AudioMate-Updater/{CURRENT_VERSION}"},
    )
    hasher = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(part_path, "wb") as f:
            total = int(resp.headers.get("Content-Length") or info.asset_size or 0)
            downloaded = 0
            chunk = 64 * 1024
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                hasher.update(buf)
                downloaded += len(buf)
                if progress:
                    progress("downloading", downloaded, total)
    except Exception:
        # Always clean up partial bytes on any error path.
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except OSError:
            pass
        raise

    actual_hex = hasher.hexdigest()
    expected = (info.asset_sha256 or "").lower()
    if expected:
        if actual_hex != expected:
            try:
                os.remove(part_path)
            except OSError:
                pass
            raise IntegrityError(
                f"Update package sha256 verification failed: expected {expected}, got {actual_hex}. "
                "The download has been discarded."
            )
    else:
        # No upstream digest is available; log it so the operator notices.
        print(
            f"[updater] WARNING: no sha256 published for {info.tag}; "
            f"installing anyway (transit-only HTTPS protection). "
            f"actual sha256={actual_hex}"
        )

    os.replace(part_path, zip_path)
    return zip_path


def _validate_zip_members(zf: zipfile.ZipFile, target_dir: str) -> list[zipfile.ZipInfo]:
    target_root = os.path.abspath(target_dir)
    members = zf.infolist()
    for member in members:
        name = member.filename
        windows_path = PureWindowsPath(name)
        normalized_parts = [part for part in name.replace("\\", "/").split("/") if part]
        if any(part == ".." for part in normalized_parts):
            raise RuntimeError(f"Unsafe update package path: {name}")
        if os.path.isabs(name) or windows_path.is_absolute() or windows_path.drive:
            raise RuntimeError(f"Unsafe update package path: {name}")
        destination = os.path.abspath(os.path.join(target_root, name))
        if os.path.commonpath([target_root, destination]) != target_root:
            raise RuntimeError(f"Unsafe update package path: {name}")
    return members


def _extract(zip_path: str, target_dir: str,
             progress: Optional[ProgressCallback] = None) -> str:
    """Extract an update zip and return the directory that contains AudioMate.exe."""
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        members = _validate_zip_members(zf, target_dir)
        for i, member in enumerate(members):
            zf.extract(member, target_dir)
            if progress:
                progress("extracting", i + 1, len(members))

    # Support zips that contain AudioMate.exe at the root or inside one top-level directory.
    if os.path.isfile(os.path.join(target_dir, "AudioMate.exe")):
        return target_dir
    for entry in os.listdir(target_dir):
        sub = os.path.join(target_dir, entry)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "AudioMate.exe")):
            return sub
    raise RuntimeError("Update package does not contain AudioMate.exe")


# ---------------------------------------------------------------------------
# Self-replacement script
# ---------------------------------------------------------------------------
_UPDATE_BAT_TEMPLATE = r"""@echo off
setlocal
chcp 65001 >nul

rem Copy staged update files into the installation directory
timeout /t 3 /nobreak >nul

set "STAGING={staging}"
set "INSTALL={install}"
set "EXE={exe}"
set "LOGFILE=%INSTALL%\update.log"

echo [%date% %time%] Apply update started >> "%LOGFILE%"
echo Staging : %STAGING% >> "%LOGFILE%"
echo Install : %INSTALL% >> "%LOGFILE%"

rem Copy staged files while preserving the updater script and log
robocopy "%STAGING%" "%INSTALL%" /E /R:3 /W:2 /NFL /NDL /NJH /NJS /NP ^
    /XF "{bat_name}" "update.log" >> "%LOGFILE%" 2>&1

set RC=%ERRORLEVEL%
echo [%date% %time%] robocopy exit=%RC% >> "%LOGFILE%"

rem robocopy exit codes 0 through 7 are non-fatal
if %RC% GEQ 8 goto :fail

rem Remove staging directory after a successful copy
rmdir /s /q "%STAGING%" >nul 2>&1

rem Relaunch the application after the update
start "" "%EXE%"

rem Delete this updater script after it exits
(goto) 2>nul & del "%~f0"
exit /b 0

:fail
echo [%date% %time%] UPDATE FAILED, see above >> "%LOGFILE%"
start "" "%EXE%"
exit /b 1
"""


def apply_update_and_exit(staging_dir: str, install_dir: Optional[str] = None) -> None:
    """Launch the external Windows script that applies the update and exits."""
    install_dir = install_dir or _install_dir()
    exe_path = os.path.join(install_dir, "AudioMate.exe")
    bat_name = "_apply_update.bat"
    bat_path = os.path.join(install_dir, bat_name)

    bat_content = _UPDATE_BAT_TEMPLATE.format(
        staging=staging_dir,
        install=install_dir,
        exe=exe_path,
        bat_name=bat_name,
    )
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    # Run the updater detached from the current process group.
    DETACHED = 0x00000008
    NEW_PG = 0x00000200
    flags = DETACHED | NEW_PG
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=flags,
        cwd=install_dir,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Terminate the current process so files can be replaced by the updater.
    os._exit(0)


# ---------------------------------------------------------------------------
# Full update flow
# ---------------------------------------------------------------------------
def perform_update(info: ReleaseInfo,
                   progress: Optional[ProgressCallback] = None) -> None:
    """Download, extract, launch the external replacement script, then exit."""
    if not _is_frozen():
        raise RuntimeError("Automatic updates are only available in packaged releases.")

    install_dir = _install_dir()
    tmp_root = os.path.join(tempfile.gettempdir(), "AudioMateUpdate")
    os.makedirs(tmp_root, exist_ok=True)

    if progress:
        progress("preparing", 0, 0)
    zip_path = download_asset(info, tmp_root, progress=progress)

    staging = os.path.join(install_dir, "_update_staging")
    real_root = _extract(zip_path, staging, progress=progress)

    # Some archives include a top-level application directory. Flatten it into staging.
    if real_root != staging:
        # Move package contents to the staging root before applying the update.
        for name in os.listdir(real_root):
            src = os.path.join(real_root, name)
            dst = os.path.join(staging, name)
            if os.path.exists(dst):
                if os.path.isdir(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    os.remove(dst)
            shutil.move(src, dst)
        shutil.rmtree(real_root, ignore_errors=True)

    if progress:
        progress("launching", 1, 1)
    apply_update_and_exit(staging, install_dir)
