from pathlib import Path
import runpy
import sys

from src.services.reaper_setup import ReaperSetupService


def _make_runtime(app_root: Path) -> Path:
    runtime = app_root / "runtime" / "reaper-python"
    site_packages = runtime / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "reapy").mkdir()
    (runtime / "python39.dll").write_bytes(b"fake dll")
    # Embeddable/standalone CPython ships the stdlib as pythonXX.zip beside
    # the DLL — this marks the dir as a valid REAPER ReaScript interpreter.
    (runtime / "python39.zip").write_bytes(b"fake stdlib")
    return runtime


def _make_bootstrap_template(app_root: Path) -> None:
    target = app_root / "assets" / "reaper" / "audiomate_reapy_bootstrap.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        'ROOT = r"__AUDIOMATE_REAPER_PYTHON_DIR__"\n'
        'SITE = r"__AUDIOMATE_REAPER_SITE_PACKAGES__"\n',
        encoding="utf-8",
    )


def _copy_real_bootstrap_template(app_root: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "assets" / "reaper" / "audiomate_reapy_bootstrap.py"
    target = app_root / "assets" / "reaper" / "audiomate_reapy_bootstrap.py"
    target.parent.mkdir(parents=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _make_fake_reapy_runtime(runtime: Path, resource_dir: Path, volatile_script: Path) -> None:
    site_packages = runtime / "Lib" / "site-packages"
    config_dir = site_packages / "reapy" / "config"
    reascripts_dir = site_packages / "reapy" / "reascripts"
    config_dir.mkdir(parents=True, exist_ok=True)
    reascripts_dir.mkdir(parents=True, exist_ok=True)
    (runtime / "python39.dll").write_bytes(b"fake dll")
    # Embeddable-CPython stdlib marker so _runtime_from_path accepts it.
    (runtime / "python39.zip").write_bytes(b"fake stdlib")
    (site_packages / "reapy" / "__init__.py").write_text(
        f'from . import config\n\ndef get_resource_path():\n    return r"{resource_dir}"\n',
        encoding="utf-8",
    )
    (config_dir / "__init__.py").write_text("from . import config\n", encoding="utf-8")
    (config_dir / "config.py").write_text(
        "class CaseInsensitiveDict(dict):\n"
        "    def __contains__(self, key):\n"
        "        return isinstance(key, str) and super().__contains__(key.lower())\n\n"
        "def add_web_interface(resource_path):\n"
        "    return None\n\n"
        "def get_activate_reapy_server_path():\n"
        f"    return r'{volatile_script}'\n\n"
        "def set_ext_state(section, key, value, resource_path):\n"
        "    with open(__import__('os').path.join(resource_path, 'extstate.txt'), 'w', encoding='utf-8') as handle:\n"
        "        handle.write(value)\n",
        encoding="utf-8",
    )
    (reascripts_dir / "__init__.py").write_text("", encoding="utf-8")
    (reascripts_dir / "activate_reapy_server.py").write_text("print('fake server')\n", encoding="utf-8")


def test_reaper_setup_configures_ini_and_installs_bootstrap(tmp_path):
    app_root = tmp_path / "app"
    resource_dir = tmp_path / "REAPER"
    app_root.mkdir()
    resource_dir.mkdir()
    runtime = _make_runtime(app_root)
    _make_bootstrap_template(app_root)
    reaper_ini = resource_dir / "reaper.ini"
    reaper_ini.write_text("[reaper]\nfoo=bar\n", encoding="utf-8")

    service = ReaperSetupService(app_root=app_root)
    status = service.status(resource_dir)

    assert status.ready_to_configure is True
    result = service.configure(resource_dir)

    configured_ini = reaper_ini.read_text(encoding="utf-8")
    assert "foo=bar" in configured_ini
    assert "reascript=1" in configured_ini
    assert f"pythonlibpath64={runtime.resolve()}" in configured_ini
    assert "pythonlibdll64=python39.dll" in configured_ini
    assert Path(result["backup"]).exists()

    bootstrap = resource_dir / "Scripts" / "AudioMate" / "audiomate_reapy_bootstrap.py"
    assert bootstrap.exists()
    bootstrap_text = bootstrap.read_text(encoding="utf-8")
    assert str(runtime.resolve()).replace("\\", "\\\\") in bootstrap_text


def test_reaper_setup_reports_missing_runtime(tmp_path):
    app_root = tmp_path / "app"
    resource_dir = tmp_path / "REAPER"
    app_root.mkdir()
    resource_dir.mkdir()
    _make_bootstrap_template(app_root)
    (resource_dir / "reaper.ini").write_text("[reaper]\n", encoding="utf-8")

    status = ReaperSetupService(app_root=app_root).status(resource_dir)

    assert status.ready_to_configure is False
    assert any("runtime" in warning for warning in status.warnings)


def test_reaper_setup_finds_pyinstaller_internal_assets_but_rejects_frozen_runtime(tmp_path):
    # The bootstrap TEMPLATE is discovered inside _internal, but a frozen
    # _internal dir (base_library.zip beside the DLL) must NOT be accepted as
    # the REAPER ReaScript interpreter — that is exactly what crashed REAPER
    # on Win11. The real embeddable runtime under runtime/reaper-python wins.
    app_root = tmp_path / "AudioMate"
    internal = app_root / "_internal"
    resource_dir = tmp_path / "REAPER"
    app_root.mkdir()
    internal.mkdir()
    resource_dir.mkdir()
    # Frozen onedir signature: python313.dll + reapy + base_library.zip.
    (internal / "python313.dll").write_bytes(b"fake dll")
    (internal / "base_library.zip").write_bytes(b"frozen archive")
    (internal / "reapy").mkdir()
    _make_bootstrap_template(internal)
    # A real standalone runtime alongside the app.
    runtime = _make_runtime(app_root)
    (resource_dir / "reaper.ini").write_text("[reaper]\n", encoding="utf-8")

    status = ReaperSetupService(app_root=app_root).status(resource_dir)

    assert status.ready_to_configure is True
    assert status.bootstrap_template == internal / "assets" / "reaper" / "audiomate_reapy_bootstrap.py"
    assert status.runtime is not None
    # NOT the frozen _internal — the embeddable runtime.
    assert status.runtime.root == runtime.resolve()
    assert status.runtime.is_embeddable is True


def test_reaper_setup_rejects_frozen_internal_when_no_real_runtime(tmp_path):
    # When ONLY a frozen _internal exists (no runtime/reaper-python), the
    # service must report "no runtime" rather than configure a crashing setup.
    app_root = tmp_path / "AudioMate"
    internal = app_root / "_internal"
    resource_dir = tmp_path / "REAPER"
    app_root.mkdir()
    internal.mkdir()
    resource_dir.mkdir()
    (internal / "python313.dll").write_bytes(b"fake dll")
    (internal / "base_library.zip").write_bytes(b"frozen archive")
    (internal / "reapy").mkdir()
    _make_bootstrap_template(internal)
    (resource_dir / "reaper.ini").write_text("[reaper]\n", encoding="utf-8")

    status = ReaperSetupService(app_root=app_root).status(resource_dir)

    assert status.runtime is None
    assert status.ready_to_configure is False
    assert any("runtime" in warning for warning in status.warnings)


def test_reaper_setup_uses_existing_uppercase_reaper_ini(tmp_path):
    app_root = tmp_path / "app"
    resource_dir = tmp_path / "REAPER"
    app_root.mkdir()
    resource_dir.mkdir()
    runtime = _make_runtime(app_root)
    _make_bootstrap_template(app_root)
    uppercase_ini = resource_dir / "REAPER.ini"
    uppercase_ini.write_text(
        "[REAPER]\n"
        "foo=bar\n"
        "pythonpath64=C:\\old\n"
        "pythonlib64=python37.dll\n",
        encoding="utf-8",
    )

    service = ReaperSetupService(app_root=app_root)
    status = service.status(resource_dir)
    result = service.configure(resource_dir)

    configured_ini = uppercase_ini.read_text(encoding="utf-8")
    assert status.reaper_ini == uppercase_ini
    assert result["reaper_ini"] == str(uppercase_ini)
    assert "foo=bar" in configured_ini
    assert "pythonpath64=" not in configured_ini
    assert "pythonlib64=" not in configured_ini
    assert f"pythonlibpath64={runtime.resolve()}" in configured_ini
    assert "pythonlibdll64=python39.dll" in configured_ini


def test_runtime_from_path_rejects_frozen_dir_and_accepts_embeddable(tmp_path):
    service = ReaperSetupService(app_root=tmp_path)

    # Frozen onedir: DLL + base_library.zip → not embeddable.
    frozen = tmp_path / "_internal"
    frozen.mkdir()
    (frozen / "python313.dll").write_bytes(b"x")
    (frozen / "base_library.zip").write_bytes(b"x")
    (frozen / "reapy").mkdir()
    frozen_runtime = service._runtime_from_path(frozen)
    assert frozen_runtime is not None
    assert frozen_runtime.is_embeddable is False

    # Frozen onedir detected via the AudioMate exe sitting beside the DLL.
    frozen2 = tmp_path / "app"
    frozen2.mkdir()
    (frozen2 / "python311.dll").write_bytes(b"x")
    (frozen2 / "python311.zip").write_bytes(b"x")
    (frozen2 / "AudioMate.exe").write_bytes(b"x")
    assert service._runtime_from_path(frozen2).is_embeddable is False

    # Real embeddable CPython: DLL + pythonXX.zip, no frozen markers.
    embed = tmp_path / "reaper-python"
    embed.mkdir()
    (embed / "python311.dll").write_bytes(b"x")
    (embed / "python311.zip").write_bytes(b"x")
    embed_runtime = service._runtime_from_path(embed)
    assert embed_runtime is not None
    assert embed_runtime.is_embeddable is True


def test_bootstrap_registers_stable_activate_launcher(tmp_path):
    app_root = tmp_path / "AudioMate-v1.1.0-win64"
    internal = app_root / "_internal"
    runtime = internal / "runtime" / "reaper-python"
    resource_dir = tmp_path / "REAPER"
    volatile_script = runtime / "Lib" / "site-packages" / "reapy" / "reascripts" / "activate_reapy_server.py"
    app_root.mkdir()
    internal.mkdir(parents=True)
    runtime.mkdir(parents=True)
    resource_dir.mkdir()
    volatile_script.parent.mkdir(parents=True)
    volatile_script.write_text("print('volatile')\n", encoding="utf-8")
    _make_fake_reapy_runtime(runtime, resource_dir, volatile_script)
    _copy_real_bootstrap_template(internal)
    (resource_dir / "reaper.ini").write_text("[reaper]\n", encoding="utf-8")

    service = ReaperSetupService(app_root=app_root)
    result = service.configure(resource_dir)
    bootstrap = Path(result["bootstrap"])

    previous_modules = {name: sys.modules.pop(name) for name in list(sys.modules) if name == "reapy" or name.startswith("reapy.")}
    try:
        runpy.run_path(str(bootstrap), run_name="__main__")
    finally:
        for name in list(sys.modules):
            if name == "reapy" or name.startswith("reapy."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)

    stable_launcher = resource_dir / "Scripts" / "AudioMate" / "activate_reapy_server.py"
    kb_text = (resource_dir / "reaper-kb.ini").read_text(encoding="utf-8")
    launcher_text = stable_launcher.read_text(encoding="utf-8")
    assert stable_launcher.exists()
    assert str(stable_launcher) in kb_text
    assert str(volatile_script) not in kb_text
    assert "runpy.run_module(\"reapy.reascripts.activate_reapy_server\", run_name=\"__main__\")" in launcher_text
    # The Python 3.13 configparser monkeypatch is gone (runtime is now 3.11).
    installed_bootstrap = (resource_dir / "Scripts" / "AudioMate" / "audiomate_reapy_bootstrap.py").read_text(encoding="utf-8")
    assert "_audiomate_py313_patch" not in installed_bootstrap
