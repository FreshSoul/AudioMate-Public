from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


BOOTSTRAP_TEMPLATE = Path("assets") / "reaper" / "audiomate_reapy_bootstrap.py"
BOOTSTRAP_INSTALL_RELATIVE = Path("Scripts") / "AudioMate" / "audiomate_reapy_bootstrap.py"
REAPER_INI_NAME = "reaper.ini"
REAPER_INI_CANDIDATES = ("REAPER.ini", "reaper.ini")


@dataclass(frozen=True)
class ReaperPythonRuntime:
    root: Path
    dll: Path
    site_packages: Path | None
    has_reapy: bool
    is_embeddable: bool = True


@dataclass(frozen=True)
class ReaperSetupStatus:
    app_root: Path
    resource_dir: Path | None
    reaper_ini: Path | None
    runtime: ReaperPythonRuntime | None
    bootstrap_template: Path
    bootstrap_installed: Path | None
    current_python_path: str
    current_python_lib: str
    ready_to_configure: bool
    needs_bootstrap_run: bool
    warnings: list[str]

    def as_dict(self) -> dict:
        runtime = None
        if self.runtime is not None:
            runtime = {
                "root": str(self.runtime.root),
                "dll": str(self.runtime.dll),
                "site_packages": str(self.runtime.site_packages) if self.runtime.site_packages else "",
                "has_reapy": self.runtime.has_reapy,
            }
        return {
            "app_root": str(self.app_root),
            "resource_dir": str(self.resource_dir) if self.resource_dir else "",
            "reaper_ini": str(self.reaper_ini) if self.reaper_ini else "",
            "runtime": runtime,
            "bootstrap_template": str(self.bootstrap_template),
            "bootstrap_installed": str(self.bootstrap_installed) if self.bootstrap_installed else "",
            "current_python_path": self.current_python_path,
            "current_python_lib": self.current_python_lib,
            "ready_to_configure": self.ready_to_configure,
            "needs_bootstrap_run": self.needs_bootstrap_run,
            "warnings": list(self.warnings),
        }


class ReaperSetupError(RuntimeError):
    pass


class ReaperSetupService:
    def __init__(self, app_root: str | os.PathLike | None = None, app_settings: dict | None = None):
        self.app_root = Path(app_root) if app_root else self._default_app_root()
        self.app_settings = app_settings if isinstance(app_settings, dict) else {}

    def status(self, resource_dir: str | os.PathLike | None = None) -> ReaperSetupStatus:
        resource_path = self._resolve_resource_dir(resource_dir)
        reaper_ini = self._resolve_reaper_ini(resource_path) if resource_path else None
        runtime = self._find_runtime()
        bootstrap_template = self._find_bootstrap_template()
        bootstrap_installed = resource_path / BOOTSTRAP_INSTALL_RELATIVE if resource_path else None
        current_python_path, current_python_lib = self._read_current_python_config(reaper_ini)

        warnings = []
        if resource_path is None:
            warnings.append("未找到 REAPER 资源目录。可设置 AUDIOMATE_REAPER_RESOURCE_DIR 或先启动一次 REAPER。")
        elif not reaper_ini or not reaper_ini.exists():
            warnings.append(f"REAPER 资源目录中缺少 {REAPER_INI_NAME}。请先启动一次 REAPER。")
        if not bootstrap_template.exists():
            warnings.append(f"缺少 AudioMate REAPER bootstrap 模板: {bootstrap_template}")
        if runtime is None:
            warnings.append("未找到 AudioMate 随包的 REAPER Python runtime。可设置 AUDIOMATE_REAPER_PYTHON_DIR。")
        elif not runtime.has_reapy:
            warnings.append(f"REAPER Python runtime 中没有找到 reapy: {runtime.root}")

        ready = resource_path is not None and reaper_ini is not None and reaper_ini.exists() and bootstrap_template.exists() and runtime is not None and runtime.has_reapy
        needs_bootstrap_run = ready
        if bootstrap_installed and bootstrap_installed.exists() and runtime is not None:
            try:
                installed_text = bootstrap_installed.read_text(encoding="utf-8", errors="ignore")
                needs_bootstrap_run = str(runtime.root) not in installed_text
            except OSError:
                needs_bootstrap_run = True

        return ReaperSetupStatus(
            app_root=self.app_root,
            resource_dir=resource_path,
            reaper_ini=reaper_ini,
            runtime=runtime,
            bootstrap_template=bootstrap_template,
            bootstrap_installed=bootstrap_installed,
            current_python_path=current_python_path,
            current_python_lib=current_python_lib,
            ready_to_configure=ready,
            needs_bootstrap_run=needs_bootstrap_run,
            warnings=warnings,
        )

    def configure(self, resource_dir: str | os.PathLike | None = None) -> dict:
        status = self.status(resource_dir)
        if status.resource_dir is None or status.reaper_ini is None:
            raise ReaperSetupError("无法定位 REAPER 资源目录。")
        if not status.reaper_ini.exists():
            raise ReaperSetupError(f"找不到 REAPER 配置文件: {status.reaper_ini}")
        if status.runtime is None:
            raise ReaperSetupError("未找到 AudioMate 随包的 REAPER Python runtime。")
        if not status.runtime.has_reapy:
            raise ReaperSetupError("REAPER Python runtime 中缺少 reapy。")
        if not status.bootstrap_template.exists():
            raise ReaperSetupError(f"缺少 bootstrap 模板: {status.bootstrap_template}")

        backup_path = self._backup_file(status.reaper_ini)
        self._write_reaper_python_config(status.reaper_ini, status.runtime)
        installed_bootstrap = self._install_bootstrap(status)
        return {
            "resource_dir": str(status.resource_dir),
            "reaper_ini": str(status.reaper_ini),
            "backup": str(backup_path),
            "python_dir": str(status.runtime.root),
            "python_dll": status.runtime.dll.name,
            "bootstrap": str(installed_bootstrap),
            "next_step": "重启 REAPER 后，在 Action List 运行 AudioMate/audiomate_reapy_bootstrap.py 一次。",
        }

    def format_status(self, status: ReaperSetupStatus | None = None) -> str:
        status = status or self.status()
        lines = ["REAPER 配置检测"]
        lines.append(f"资源目录: {status.resource_dir or '未找到'}")
        lines.append(f"配置文件: {status.reaper_ini or '未找到'}")
        if status.runtime is None:
            lines.append("内置 Python: 未找到")
        else:
            lines.append(f"内置 Python: {status.runtime.root}")
            lines.append(f"Python DLL: {status.runtime.dll.name}")
            lines.append(f"reapy: {'已找到' if status.runtime.has_reapy else '缺失'}")
        if status.current_python_path or status.current_python_lib:
            lines.append(f"REAPER 当前 Python 目录: {status.current_python_path or '未设置'}")
            lines.append(f"REAPER 当前 Python DLL: {status.current_python_lib or '未设置'}")
        lines.append(f"Bootstrap: {status.bootstrap_installed or '未安装'}")
        if status.warnings:
            lines.append("")
            lines.extend(f"- {warning}" for warning in status.warnings)
        return "\n".join(lines)

    @staticmethod
    def _default_app_root() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    def _bundle_roots(self) -> list[Path]:
        roots = [self.app_root]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
        internal = self.app_root / "_internal"
        if internal.exists():
            roots.append(internal)
        seen = set()
        unique_roots = []
        for root in roots:
            try:
                resolved = root.expanduser().resolve()
            except OSError:
                resolved = root.expanduser()
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                unique_roots.append(resolved)
        return unique_roots

    def _find_bootstrap_template(self) -> Path:
        for root in self._bundle_roots():
            candidate = root / BOOTSTRAP_TEMPLATE
            if candidate.exists():
                return candidate
        return self.app_root / BOOTSTRAP_TEMPLATE

    def _resolve_resource_dir(self, explicit: str | os.PathLike | None = None) -> Path | None:
        candidates = []
        if explicit:
            candidates.append(Path(explicit))
        settings = self.app_settings.get("reaper_setup") if isinstance(self.app_settings.get("reaper_setup"), dict) else {}
        if settings.get("resource_dir"):
            candidates.append(Path(str(settings.get("resource_dir"))))
        if os.environ.get("AUDIOMATE_REAPER_RESOURCE_DIR"):
            candidates.append(Path(os.environ["AUDIOMATE_REAPER_RESOURCE_DIR"]))
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "REAPER")
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            candidates.append(Path(localappdata) / "REAPER")
        for candidate in candidates:
            try:
                path = candidate.expanduser().resolve()
            except OSError:
                path = candidate.expanduser()
            if path.exists() and path.is_dir():
                return path
        return None

    @staticmethod
    def _resolve_reaper_ini(resource_path: Path | None) -> Path | None:
        if resource_path is None:
            return None
        for name in REAPER_INI_CANDIDATES:
            candidate = resource_path / name
            if candidate.exists():
                return candidate
        try:
            for candidate in resource_path.iterdir():
                if candidate.is_file() and candidate.name.casefold() == REAPER_INI_NAME.casefold():
                    return candidate
        except OSError:
            pass
        return resource_path / REAPER_INI_CANDIDATES[0]

    def _find_runtime(self) -> ReaperPythonRuntime | None:
        candidates = []
        settings = self.app_settings.get("reaper_setup") if isinstance(self.app_settings.get("reaper_setup"), dict) else {}
        for key in ("python_dir", "runtime_dir"):
            if settings.get(key):
                candidates.append(Path(str(settings.get(key))))
        if os.environ.get("AUDIOMATE_REAPER_PYTHON_DIR"):
            candidates.append(Path(os.environ["AUDIOMATE_REAPER_PYTHON_DIR"]))
        candidates.extend([
            self.app_root / "runtime" / "reaper-python",
            self.app_root / "resources" / "reaper-python",
            self.app_root / "reaper-python",
        ])
        for root in self._bundle_roots():
            candidates.extend([
                root / "runtime" / "reaper-python",
                root / "resources" / "reaper-python",
                root / "reaper-python",
            ])
        # NOTE: we deliberately do NOT treat a bundle root that merely contains
        # ``reapy/`` (e.g. PyInstaller's frozen ``_internal``) as a runtime.
        # REAPER loads ``pythonlibdll`` directly into its own process; the
        # frozen interpreter is not a valid embeddable CPython and crashes
        # REAPER on Win11 (its CRT/loader deps are borrowed from the host).
        # Only a real standalone/embeddable CPython is accepted below.
        for candidate in candidates:
            runtime = self._runtime_from_path(candidate)
            if runtime is not None and runtime.is_embeddable:
                return runtime
        return None

    @staticmethod
    def _is_frozen_runtime_dir(root: Path) -> bool:
        """A PyInstaller-frozen dir is NOT a valid REAPER ReaScript interpreter.

        Tell-tale signs of a frozen onedir bundle: ``base_library.zip`` next to
        the DLL, or the AudioMate executable sitting alongside it.
        """
        try:
            if (root / "base_library.zip").exists():
                return True
            for exe in root.glob("*.exe"):
                if exe.name.lower().startswith("audiomate"):
                    return True
        except OSError:
            pass
        return False

    @staticmethod
    def _has_embeddable_stdlib(root: Path, dll: Path) -> bool:
        """An embeddable/standalone CPython ships the stdlib as ``pythonXX.zip``
        beside the DLL, or as a real ``Lib/`` tree."""
        try:
            stem = dll.stem  # e.g. "python311"
            if (root / f"{stem}.zip").exists():
                return True
            if any(root.glob("python3*.zip")):
                return True
            lib_dir = root / "Lib"
            if lib_dir.is_dir():
                return True
        except OSError:
            pass
        return False

    def _runtime_from_path(self, raw_path: Path) -> ReaperPythonRuntime | None:
        try:
            root = raw_path.expanduser().resolve()
        except OSError:
            root = raw_path.expanduser()
        if not root.exists() or not root.is_dir():
            return None
        dlls = sorted(root.glob("python*.dll"))
        dll = next((item for item in dlls if item.name.lower() != "python3.dll"), None) or (dlls[0] if dlls else None)
        if dll is None:
            return None
        site_packages = self._find_site_packages(root)
        has_reapy = bool(site_packages and (site_packages / "reapy").exists())
        is_embeddable = self._has_embeddable_stdlib(root, dll) and not self._is_frozen_runtime_dir(root)
        return ReaperPythonRuntime(
            root=root,
            dll=dll,
            site_packages=site_packages,
            has_reapy=has_reapy,
            is_embeddable=is_embeddable,
        )

    @staticmethod
    def _find_site_packages(root: Path) -> Path | None:
        candidates = [root / "Lib" / "site-packages"]
        candidates.extend(root.glob("Lib/site-packages"))
        candidates.extend(root.glob("Lib/python*/site-packages"))
        if (root / "reapy").exists():
            candidates.append(root)
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    @staticmethod
    def _read_current_python_config(reaper_ini: Path | None) -> tuple[str, str]:
        if reaper_ini is None or not reaper_ini.exists():
            return "", ""
        python_path = ""
        python_lib = ""
        try:
            lines = reaper_ini.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return "", ""
        for line in lines:
            key, sep, value = line.partition("=")
            if not sep:
                continue
            key = key.strip().lower()
            value = value.strip()
            if key in {"pythonlibpath64", "pythonlibpath", "pythonpath64", "pythonpath"} and value:
                python_path = value
            elif key in {"pythonlibdll64", "pythonlibdll", "pythonlib64", "pythonlib"} and value:
                python_lib = value
        return python_path, python_lib

    @staticmethod
    def _backup_file(path: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.name}.audiomate-backup-{stamp}")
        shutil.copy2(path, backup_path)
        return backup_path

    def _write_reaper_python_config(self, reaper_ini: Path, runtime: ReaperPythonRuntime) -> None:
        text = reaper_ini.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        updates = {
            "reascript": "1",
            "pythonlibpath": str(runtime.root),
            "pythonlibpath64": str(runtime.root),
            "pythonlibdll": runtime.dll.name,
            "pythonlibdll64": runtime.dll.name,
        }
        obsolete_keys = {"pythonpath", "pythonpath64", "pythonlib", "pythonlib64"}
        seen = set()
        output = []
        inserted = False
        in_reaper_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_reaper_section and not inserted:
                    for key, value in updates.items():
                        if key not in seen:
                            output.append(f"{key}={value}")
                    inserted = True
                in_reaper_section = stripped.lower() == "[reaper]"
            key, sep, _value = line.partition("=")
            normalized_key = key.strip().lower() if sep else ""
            if normalized_key in updates:
                output.append(f"{normalized_key}={updates[normalized_key]}")
                seen.add(normalized_key)
            elif normalized_key in obsolete_keys:
                continue
            else:
                output.append(line)
        if not lines:
            output.append("[reaper]")
            in_reaper_section = True
        if not inserted:
            if not in_reaper_section and not any(line.strip().lower() == "[reaper]" for line in output):
                output.append("[reaper]")
            for key, value in updates.items():
                if key not in seen:
                    output.append(f"{key}={value}")
        reaper_ini.write_text("\n".join(output) + "\n", encoding="utf-8")

    def _install_bootstrap(self, status: ReaperSetupStatus) -> Path:
        if status.resource_dir is None or status.runtime is None:
            raise ReaperSetupError("bootstrap 安装缺少 REAPER 目录或 Python runtime。")
        target = status.resource_dir / BOOTSTRAP_INSTALL_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        template = status.bootstrap_template.read_text(encoding="utf-8")
        site_packages = str(status.runtime.site_packages) if status.runtime.site_packages else ""
        rendered = template.replace("__AUDIOMATE_REAPER_PYTHON_DIR__", str(status.runtime.root).replace("\\", "\\\\"))
        rendered = rendered.replace("__AUDIOMATE_REAPER_SITE_PACKAGES__", site_packages.replace("\\", "\\\\"))
        target.write_text(rendered, encoding="utf-8")
        return target
