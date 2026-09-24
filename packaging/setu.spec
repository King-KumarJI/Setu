# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for Setu.

Must be run on Windows, with the project's own virtualenv active
(PySide6 installed) and pyinstaller installed in that same venv --
PyInstaller bundles whatever interpreter/environment it's run from,
so it cannot cross-build a Windows executable from this Linux
development sandbox. See packaging/build.ps1, which runs this spec.

Produces a single portable Setu.exe (--onefile-equivalent via the
EXE(..., a.binaries, ..., exclude_binaries=False) form below) rather
than a full installer -- Rule 15 (GUI stays simple) extends naturally
to "the distribution stays simple": one .exe, no install wizard, no
registry writes. See 04-phases.md Phase 7 ("Installer OR portable
package") -- portable is the deliberate choice here.

windowed=True (console=False) is intentional: Setu is a GUI tool, and
per Rule 3 nothing worth seeing should ever be going to a console
anyway -- diagnostics go to the log file (app.utils.logging.get_log_dir()).
"""
import sys
from pathlib import Path

block_cipher = None

# packaging/setu.spec -> project root is one level up.
PROJECT_ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(PROJECT_ROOT / 'app' / 'main.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    # main.py imports PySide6 lazily inside main(), not at module level
    # (so the CLI/tests keep working without it installed) -- name it
    # explicitly here since PyInstaller's static import scan is most
    # reliable when a package is imported at module scope, and Qt's
    # plugin-loading machinery in particular benefits from the
    # official PyInstaller hook running.
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Setu',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'app' / 'resources' / 'icon.ico'),
    version=str(PROJECT_ROOT / 'packaging' / 'version_info.txt'),
)
