# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['tkinter', 'tkinter.ttk', 'tkinter.filedialog', 'tkinter.messagebox']
hiddenimports += collect_submodules('tkinter')


a = Analysis(
    ['..\\app\\gpt_image_generator.py'],
    pathex=['C:\\Users\\57276\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\Lib'],
    binaries=[('C:\\Users\\57276\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\DLLs\\_tkinter.pyd', '.'), ('C:\\Users\\57276\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\DLLs\\tcl86t.dll', '.'), ('C:\\Users\\57276\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\DLLs\\tk86t.dll', '.')],
    datas=[('C:\\Users\\57276\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\Lib\\tkinter', 'tkinter'), ('C:\\Users\\57276\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\tcl\\tcl8.6', 'tcl\\tcl8.6'), ('C:\\Users\\57276\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\tcl\\tk8.6', 'tcl\\tk8.6')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GPT Image Generator CN2',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GPT Image Generator CN2',
)
