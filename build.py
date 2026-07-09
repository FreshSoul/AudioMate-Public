import PyInstaller.__main__
import os
import subprocess
import sys


def ensure_reaper_runtime(project_root: str) -> None:
    runtime_dir = os.path.join(project_root, 'runtime', 'reaper-python')
    runtime_python = os.path.join(runtime_dir, 'python.exe')
    runtime_dll = os.path.join(runtime_dir, 'python311.dll')
    reapy_dir = os.path.join(runtime_dir, 'Lib', 'site-packages', 'reapy')
    if os.path.exists(runtime_python) and os.path.exists(runtime_dll) and os.path.isdir(reapy_dir):
        print('REAPER Python runtime found.')
        return
    print('REAPER Python runtime is missing; preparing runtime/reaper-python...')
    subprocess.run([sys.executable, os.path.join('scripts', 'prepare_reaper_runtime.py')], check=True)

if __name__ == '__main__':
    print("Starting build process...")

    # Ensure we are in the project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)
    ensure_reaper_runtime(project_root)

    args = [
        'AudioMate.spec',
        '--clean',
        '--noconfirm',
    ]

    print("PyInstaller args:")
    for a in args:
        print(f"  {a}")
    print()

    PyInstaller.__main__.run(args)

    print("\nBuild complete! Check the 'dist/AudioMate' folder.")
