# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for packaging Sage backend as a standalone executable.

Usage:
    pyinstaller scripts/backend.spec --distpath resources/dist-backend
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
SAGE_CORE_DIR = REPO_ROOT / "packages" / "sage-core" / "sage_core"
DOCS_DIR = REPO_ROOT / "docs"

# 白名单单一真相源：backend/services/sage_docs/paths.py::TECHNICAL_WHITELIST
# （electron-builder.yml 的 docs filter 是同一份列表的 YAML 副本）。
import sys  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))
from backend.services.sage_docs.paths import TECHNICAL_WHITELIST  # noqa: E402

datas = [
    # M4-T5: 专家模板与黄金任务集是数据文件,PyInstaller 不跟踪静态资源,
    # 必须显式打入 bundle,否则 specialist_templates / golden_tasks.json 在
    # 发行包中不可见导致 list_templates / run_golden_eval 抛「文件缺失」。
    (str(BACKEND_DIR / "services" / "specialist_templates"), "backend/services/specialist_templates"),
    (str(BACKEND_DIR / "services" / "golden_tasks.json"), "backend/services"),
]
# Sage 内置文档（sage-guide 知识源）：落到 <MEIPASS>/docs，
# paths.resolve_docs_root() 的 PyInstaller 分支会在此查找。
datas.append((str(DOCS_DIR / "user-manual"), "docs/user-manual"))
datas += [
    (str(DOCS_DIR / "technical" / name), "docs/technical") for name in TECHNICAL_WHITELIST
]

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
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)  # noqa: F821

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
