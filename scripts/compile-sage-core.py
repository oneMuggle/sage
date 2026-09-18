#!/usr/bin/env python3
"""Cython compilation script for sage_core package.

Compiles Python source files in packages/sage-core/sage_core/ to C extensions
(.pyd on Windows, .so on Linux) for code protection and performance.

Usage:
    python scripts/compile-sage-core.py build_ext --inplace
    python scripts/compile-sage-core.py build_ext --build-lib <output-dir>
"""

import sys
from pathlib import Path
from setuptools import setup

try:
    from Cython.Build import cythonize
    from Cython.Distutils import build_ext
except ImportError:
    print("Error: Cython is not installed. Run: pip install cython", file=sys.stderr)
    sys.exit(1)

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
SAGE_CORE_DIR = REPO_ROOT / "packages" / "sage-core" / "sage_core"

if not SAGE_CORE_DIR.exists():
    print(f"Error: sage_core directory not found at {SAGE_CORE_DIR}", file=sys.stderr)
    sys.exit(1)

# Find all .py files to compile, excluding __init__.py (needed for package structure)
# Keeping __init__.py as pure Python avoids package import issues
py_files = []
for py_path in SAGE_CORE_DIR.rglob("*.py"):
    if py_path.name == "__init__.py":
        continue
    rel_path = py_path.relative_to(REPO_ROOT)
    py_files.append(str(rel_path))

print(f"Found {len(py_files)} files to compile in sage_core:")
for f in py_files:
    print(f"  - {f}")

# Compiler directives: binding=True is critical for Pydantic / inspect compatibility
compiler_directives = {
    "language_level": "3",
    "always_allow_keywords": True,
    "binding": True,
    "embedsignature": True,
}

setup(
    name="sage_core_compiled",
    ext_modules=cythonize(
        py_files,
        compiler_directives=compiler_directives,
        quiet=False,
    ),
    cmdclass={"build_ext": build_ext},
)
