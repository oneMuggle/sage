"""R100 — SettingsRepository KEYS 白名单守卫（防 Zotero 类静默断链复发）。

AST 扫描 backend/ 全部生产代码（排除 tests/），收集对 SettingsRepository
实例变量调用 ``.get("key") / .set("key", ...) / .get_json / .set_json`` 的
字符串字面量键，断言全部在 ``SettingsRepository.KEYS`` 白名单内。

背景（R94，#1377）：zotero_routes 用的键未入白名单，``set()`` 抛
ValueError 被吞、``get()`` 静默返回 None —— 配置写入假成功。新增键时
本守卫会在 CI 直接报出缺失清单。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.data.settings_repo import SettingsRepository

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
GET_METHODS = {"get", "get_json"}
SET_METHODS = {"set", "set_json"}


def _iter_py_files() -> list[Path]:
    skip_parts = {"tests", "__pycache__", ".venv", "export_assets"}
    out: list[Path] = []
    for p in BACKEND_ROOT.rglob("*.py"):
        if skip_parts & set(p.parts):
            continue
        out.append(p)
    return out


def _extract_settings_keys(tree: ast.Module) -> set[str]:
    """收集 SettingsRepository 实例变量上的 get/set 字符串字面量键。

    只追踪 ``x = SettingsRepository()`` 直接赋值 —— `repo` 等通用变量名
    被 agent/run/project 仓储复用，按名追踪会大量误报。
    """
    repo_classes = {"SettingsRepository", "SettingsRepo"}
    tracked: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Assign, ast.AnnAssign))  # noqa: UP038 — py38 运行时 isinstance 不支持 X | Y
            and node.value is not None
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, (ast.Name, ast.Attribute))  # noqa: UP038 — py38 运行时 isinstance 不支持 X | Y
            and getattr(node.value.func, "id", None) in repo_classes
        ) or (
            isinstance(node, (ast.Assign, ast.AnnAssign))  # noqa: UP038 — py38 运行时 isinstance 不支持 X | Y
            and node.value is not None
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr in repo_classes
        ):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    tracked.add(target.id)

    keys: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in tracked
        ):
            continue
        if node.func.attr not in GET_METHODS | SET_METHODS:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue  # 动态键无法静态验证，跳过
        value = node.args[0].value
        if isinstance(value, str):
            keys.add(value)
    return keys


def test_settings_keys_all_in_whitelist() -> None:
    missing: dict[str, list[str]] = {}
    for path in _iter_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        keys = _extract_settings_keys(tree)
        bad = sorted(k for k in keys if k not in SettingsRepository.KEYS)
        if bad:
            missing[str(path.relative_to(BACKEND_ROOT))] = bad

    assert not missing, (
        "以下文件使用了未列入 SettingsRepository.KEYS 白名单的设置键"
        "（set() 会抛 ValueError 被吞、get() 静默返回 None —— R94 Zotero 断链同款）：\n"
        + "\n".join(f"  {f}: {ks}" for f, ks in sorted(missing.items()))
    )


def test_known_keys_present_in_whitelist() -> None:
    """抽样回归：历史上踩过坑的键必须一直在白名单内。"""
    assert "zotero_db_path" in SettingsRepository.KEYS
    assert "app_settings" in SettingsRepository.KEYS
    assert "permission_mode" in SettingsRepository.KEYS


def test_unknown_key_get_returns_none_and_set_raises() -> None:
    """锁定白名单语义：未收录键 get 返 None / set 抛 ValueError（守卫的存在依据）。"""
    repo = SettingsRepository.__new__(SettingsRepository)  # 跳过 DB 初始化
    assert repo.get("definitely_not_a_key") is None
    with pytest.raises(ValueError, match="not in whitelist"):
        repo.set("definitely_not_a_key", "v")
