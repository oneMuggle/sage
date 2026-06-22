"""SAGE_DB_PATH 环境变量集成测试"""
import os
import tempfile
from pathlib import Path

import pytest


def test_db_path_from_env(monkeypatch, tmp_path):
    target = tmp_path / "custom-sage.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(target))
    # 重新导入以触发 __init__ 重读
    import importlib
    from backend.data import database
    importlib.reload(database)
    db = database.Database()
    assert db.db_path == str(target)
    db.init_db()
    assert target.exists()
    db.close()


def test_db_path_default_when_no_env(monkeypatch):
    monkeypatch.delenv("SAGE_DB_PATH", raising=False)
    import importlib
    from backend.data import database
    importlib.reload(database)
    db = database.Database()
    # 默认路径包含 'sage.db'
    assert db.db_path.endswith("sage.db")
    db.close()
