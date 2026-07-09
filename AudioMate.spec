# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = [('src/llm/waapi_docs', 'src/llm/waapi_docs'), ('src/gui/assets', 'src/gui/assets'), ('assets/reaper', 'assets/reaper'), ('AudioMate.jpg', '.'), ('runtime/reaper-python', 'runtime/reaper-python')]
binaries = []

# Auto-collect every internal src.* submodule. Excludes tests + scratch dirs.
_SRC_EXCLUDES = ('src.test', 'src.test.', 'src.gui.Buddy', 'src.utils.agent_tooling')


def _filter_src(name):
    return not any(name == ex or name.startswith(ex + '.') for ex in _SRC_EXCLUDES)


hiddenimports = collect_submodules('src', filter=_filter_src)

# Third-party packages PyInstaller's static analysis can miss (lazy imports,
# C-extension reach into data files, package-private submodules).
hiddenimports += [
    'numpy', 'librosa', 'pyloudnorm', 'soundfile', 'bs4', 'PyPDF2', 'docx',
    'openpyxl', 'pptx', 'pandas', 'chardet', 'openai', 'anthropic', 'mcp',
    'anyio', 'httpx', 'httpcore', 'keyring.backends', 'keyring.backends.Windows',
    'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore', 'PyQt6.QtNetwork', 'reapy',
    'win32job', 'win32api', 'win32process', 'win32security', 'win32con', 'pywintypes',
]
tmp_ret = collect_all('autobahn')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += collect_data_files('mcp')
hiddenimports += collect_submodules('mcp', filter=lambda name: not name.startswith('mcp.cli'))
tmp_ret = collect_all('anyio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('httpx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('httpcore')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('bs4')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PyQt6.QtWebEngineWidgets')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('keyring')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('reapy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('chardet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openpyxl')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pptx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep optional web frontends out of the desktop bundle.
    excludes=['web'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AudioMate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['AudioMate.jpg'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AudioMate',
)
