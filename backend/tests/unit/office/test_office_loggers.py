"""Smoke: backend/office 各模块暴露模块级 logger(日志基线修复 #6)。"""
from __future__ import annotations

import importlib
import logging

import pytest

# 除 __init__.py 外 backend/office/ 下全部模块
_OFFICE_MODULES = [
    "chat_refs",
    "errors",
    "excel",
    "models",
    "path_safety",
    "ppt",
    "session_workspace",
    "storage",
    "tool_service",
    "word",
    "workspace_errors",
    "workspace_search",
]


@pytest.mark.parametrize("name", _OFFICE_MODULES)
def test_office_module_exposes_logger(name: str) -> None:
    mod = importlib.import_module(f"backend.office.{name}")
    assert hasattr(mod, "logger")
    assert isinstance(mod.logger, logging.Logger)
