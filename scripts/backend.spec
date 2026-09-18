# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for packaging Sage backend as a standalone executable.

Usage:
    pyinstaller scripts/backend.spec --distpath resources/dist-backend
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
SAGE_CORE_DIR = REPO_ROOT / "packages" / "sage-core" / "sage_core"

datas = []

# Hidden imports that PyInstaller might miss due to dynamic loading in FastAPI/Uvicorn
hidden_imports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "pydantic",
    "sqlite3",
    "sage_core",
]
hidden_imports += collect_submodules("backend")
hidden_imports += collect_submodules("sage_core")

a = Analysis(  # noqa: F821
    [str(BACKEND_DIR / "main.py")],
    pathex=[str(BACKEND_DIR), str(REPO_ROOT / "packages" / "sage-core")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sage-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="backend-standalone",
)
