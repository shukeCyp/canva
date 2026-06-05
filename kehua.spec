# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


block_cipher = None
project_dir = Path.cwd()

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
qfluent_datas, qfluent_binaries, qfluent_hiddenimports = collect_all("qfluentwidgets")

datas = playwright_datas + qfluent_datas
binaries = playwright_binaries + qfluent_binaries
hiddenimports = playwright_hiddenimports + qfluent_hiddenimports
hiddenimports += collect_submodules("greenlet")
hiddenimports += collect_submodules("playwright")
hiddenimports += [
    "app.tools.open_leonardo_account",
]

# Bundle Playwright browser downloads installed by:
#   PLAYWRIGHT_BROWSERS_PATH=./browsers python -m playwright install chromium
browsers_dir = project_dir / "browsers"
if browsers_dir.is_dir():
    for f in browsers_dir.rglob("*"):
        if f.is_file():
            datas.append((str(f), str(f.parent.relative_to(project_dir))))


a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_dir / "hooks" / "pyi_rth_playwright.py")],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kehua",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Kehua",
)
