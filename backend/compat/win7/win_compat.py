"""
win_compat.py — Windows / Python 3.8 兼容原语

收敛 W4/W5 散在各处的 _win_abspath / reparse-safe / with 重写逻辑，
供 backend 统一 import。
"""
import os
import pathlib
import sys
from typing import Union

def win_abspath(p: Union[str, pathlib.Path]) -> pathlib.Path:
    """W4 遗留：Windows 原子写越界检查前的归一化入口。"""
    pp = pathlib.Path(p)
    try:
        return pp.resolve()
    except Exception:
        return pp.absolute()

def is_win7() -> bool:
    return sys.platform == "win32"

def py38_with_compat(code: str) -> str:
    """
    简单重写：把 `with (a, b):` 降级为嵌套 with，供脚本调用。
    实际重写由 scripts/py38_compat_rewrite.py 负责，这里仅作运行时判定。
    """
    if sys.version_info >= (3, 9):
        return code
    return code.replace("with (", "with  # py38-compat: original `with (`\n    with ")

__all__ = ["win_abspath", "is_win7", "py38_with_compat"]
