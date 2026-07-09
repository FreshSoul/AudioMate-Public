from __future__ import annotations

import os
import random
import sys
import traceback
import string
import warnings


AUDIOMATE_REAPER_PYTHON_DIR = r"__AUDIOMATE_REAPER_PYTHON_DIR__"
AUDIOMATE_REAPER_SITE_PACKAGES = r"__AUDIOMATE_REAPER_SITE_PACKAGES__"


def _add_path(path):
    if path and os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)


def _add_reascript(resource_path, script_path):
    script_path = os.path.abspath(script_path)
    if not os.path.exists(script_path):
        raise FileNotFoundError(script_path)
    if os.path.splitext(script_path)[1] != ".py":
        raise ValueError(f"{script_path} is not a Python module.")

    ini_file = os.path.join(resource_path, "reaper-kb.ini")
    if not os.path.exists(ini_file):
        open(ini_file, "a", encoding="utf-8").close()
    with open(ini_file, "r", encoding="utf-8", errors="ignore") as handle:
        content = handle.read()
    for line in content.splitlines():
        if not line.startswith("SCR 4 0 "):
            continue
        parts = line.split(" ")
        if len(parts) > 3 and parts[-1] == script_path:
            return f'"_{parts[3].strip("_")}"'

    chars = string.ascii_letters + string.digits
    code = "RS" + "".join(random.choice(chars) for _ in range(40))
    while code in content:
        code = "RS" + "".join(random.choice(chars) for _ in range(40))
    script_name = os.path.basename(script_path)
    with open(ini_file, "a", encoding="utf-8") as handle:
        handle.write(f'SCR 4 0 {code} "Custom: {script_name}" {script_path}\n')
    return f'"_{code}"'


def _python_string_literal(value):
    return repr(str(value or ""))


def _install_activate_reapy_launcher(resource_path):
    target_dir = os.path.join(resource_path, "Scripts", "AudioMate")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "activate_reapy_server.py")
    python_dir = _python_string_literal(AUDIOMATE_REAPER_PYTHON_DIR)
    site_packages = _python_string_literal(AUDIOMATE_REAPER_SITE_PACKAGES)
    content = f'''from __future__ import annotations

import os
import runpy
import sys


AUDIOMATE_REAPER_PYTHON_DIR = {python_dir}
AUDIOMATE_REAPER_SITE_PACKAGES = {site_packages}


def _add_path(path):
    if path and os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)


_add_path(AUDIOMATE_REAPER_SITE_PACKAGES)
_add_path(os.path.join(AUDIOMATE_REAPER_PYTHON_DIR, "Lib", "site-packages"))
_add_path(AUDIOMATE_REAPER_PYTHON_DIR)

runpy.run_module("reapy.reascripts.activate_reapy_server", run_name="__main__")
'''
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content)
    return target


def _configure_reapy(reapy):
    resource_path = reapy.get_resource_path()
    try:
        from reapy.config import config as reapy_config

        reapy_config.add_web_interface(resource_path)
        action = _add_reascript(resource_path, _install_activate_reapy_launcher(resource_path))
        reapy_config.set_ext_state("reapy", "activate_reapy_server", action, resource_path)
    except AttributeError:
        reapy.config.enable_dist_api()


def main():
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    _add_path(AUDIOMATE_REAPER_SITE_PACKAGES)
    _add_path(os.path.join(AUDIOMATE_REAPER_PYTHON_DIR, "Lib", "site-packages"))
    _add_path(AUDIOMATE_REAPER_PYTHON_DIR)

    import reapy

    _configure_reapy(reapy)
    print("AudioMate reapy dist API enabled.")


try:
    main()
except Exception:
    print("AudioMate reapy bootstrap failed:")
    print(traceback.format_exc())
    raise
