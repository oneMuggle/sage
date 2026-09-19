#!/usr/bin/env python3
"""Cython compilation script for sage_core package.

Compiles Python source files in packages/sage-core/sage_core/ to C extensions
(.pyd on Windows, .so on Linux) for code protection and performance.

Usage:
    python scripts/compile-sage-core.py build_ext --inplace
    python scripts/compile-sage-core.py build_ext --build-lib <output-dir>
"""

import os
import sys
from pathlib import Path
from setuptools import setup, Extension

try:
    from Cython.Build import cythonize
    from Cython.Distutils import build_ext
except ImportError:
    print("Error: Cython is not installed. Run: pip install cython", file=sys.stderr)
    sys.exit(1)

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
SAGE_CORE_DIR = REPO_ROOT / "packages" / "sage-core" / "sage_core"

if not SAGE_CORE_DIR.is_dir():
    print(f"Error: sage_core directory not found at {SAGE_CORE_DIR}", file=sys.stderr)
    sys.exit(1)

# Build explicit Extension objects with correct dotted module names.
#
# CRITICAL: We must NOT pass raw file paths (e.g. "packages/sage-core/sage_core/entities/agent.py")
# to cythonize() because setuptools derives module names from these paths. The hyphen in
# "sage-core" is not a valid Python identifier, causing setuptools to normalise it to an
# underscore when computing the output .pyd path — placing compiled extensions in a
# different directory tree than the bundle script expects.
#
# Instead we derive module names relative to the sage_core package root:
#   sage_core/entities/agent.py → "sage_core.entities.agent"
# and pass `package_dir={"sage_core": ...}` so that `build_ext --inplace` writes .pyd
# files into the actual source tree (`packages/sage-core/sage_core/...`) regardless of
# the caller's cwd. Without `package_dir`, setuptools resolves `sage_core` as a
# top-level package and places .pyd at `<cwd>/sage_core/` — which is WRONG whenever
# cwd != packages/sage-core (verified empirically: both path-based cythonize and the
# plain-Extension version write .pyd to repo root).
ext_modules = []
for py_path in sorted(SAGE_CORE_DIR.rglob("*.py")):
    if py_path.name == "__init__.py":
        continue
    rel_to_pkg = py_path.relative_to(SAGE_CORE_DIR.parent)  # sage_core/entities/agent.py
    module_name = str(rel_to_pkg.with_suffix("")).replace(os.sep, ".")  # sage_core.entities.agent
    ext_modules.append(Extension(module_name, sources=[str(py_path)]))

print(f"Found {len(ext_modules)} files to compile in sage_core:")
for ext in ext_modules:
    print(f"  - {ext.name}")

# Compiler directives: binding=True is critical for Pydantic / inspect compatibility
compiler_directives = {
    "language_level": "3",
    "always_allow_keywords": True,
    "binding": True,
    "embedsignature": True,
}

setup(
    name="sage_core_compiled",
    # Map the top-level `sage_core` package to the absolute source directory.
    # Without this, `build_ext --inplace` resolves `sage_core` as a top-level
    # package at cwd and places .pyd there — which is WRONG when cwd != packages/sage-core.
    package_dir={"sage_core": str(SAGE_CORE_DIR)},
    ext_modules=cythonize(
        ext_modules,
        compiler_directives=compiler_directives,
        quiet=False,
    ),
    cmdclass={"build_ext": build_ext},
)
