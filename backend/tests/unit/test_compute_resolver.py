# ruff: noqa: PT019
"""``backend.adapters.out.compute._resolver`` 单测。

覆盖：

- 4 条解析路径分别命中（``executable_path`` / ``python_module`` / PATH 查找 /
  缺失的 sidecar 自动跳过）
- ``GHM_EXECUTABLE_PATH`` 环境变量优先于 yaml
- 多次 ``resolve()`` 缓存生效
- ``invalidate()`` 清空缓存
- 全部来源失败时抛 ``ExecutableNotFoundError`` 且 ``tried`` 列出全部
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.adapters.out.compute._resolver import (
    ExecutableNotFoundError,
    ExecutableResolver,
    ResolvedExecutable,
)

# ---------- 辅助 fixtures ----------


@pytest.fixture  # noqa: PT001 — 兼容 CI ruff 0.15.x (偏好无括号)
def fake_exe(tmp_path: Path) -> Path:
    """生成一个临时的"可执行"文件（chmod +x）。"""
    p = tmp_path / "fake-exe"
    p.write_text("#!/bin/sh\necho mock\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


@pytest.fixture  # noqa: PT001 — 兼容 CI ruff 0.15.x (偏好无括号)
def another_fake_exe(tmp_path: Path) -> Path:
    """第二个临时可执行文件（用于优先级测试）。"""
    p = tmp_path / "another-exe"
    p.write_text("#!/bin/sh\necho another\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


@pytest.fixture  # noqa: PT001 — 兼容 CI ruff 0.15.x (偏好无括号)
def _clean_env() -> Iterator[None]:
    """确保测试前清除 GHM_EXECUTABLE_PATH 环境变量。"""
    saved = os.environ.pop("GHM_EXECUTABLE_PATH", None)
    yield
    if saved is not None:
        os.environ["GHM_EXECUTABLE_PATH"] = saved


# ---------- 各路径命中 ----------


def test_resolves_executable_path(fake_exe: Path, _clean_env: None) -> None:
    """yaml.executable_path 指向有效可执行文件 → 命中。"""
    resolver = ExecutableResolver(config={"executable_path": str(fake_exe)})

    result = resolver.resolve()

    assert result.argv_prefix == [str(fake_exe)]
    assert result.source == "executable_path"
    assert result.working_dir is None


def test_resolves_python_module(fake_exe: Path, _clean_env: None) -> None:
    """python_module.python 可用 → 拼出 ``python -m ghm``。"""
    resolver = ExecutableResolver(
        config={
            "python_module": {
                "python": str(fake_exe),
                "module": "ghm",
                "working_dir": "/tmp/ghm",
            },
        },
    )

    result = resolver.resolve()

    assert result.argv_prefix == [str(fake_exe), "-m", "ghm"]
    assert result.source == "python_module"
    assert result.working_dir == "/tmp/ghm"


def test_python_module_default_module_name(fake_exe: Path, _clean_env: None) -> None:
    """python_module.module 缺省时默认 ``ghm``。"""
    resolver = ExecutableResolver(
        config={"python_module": {"python": str(fake_exe)}},
    )

    result = resolver.resolve()

    assert result.argv_prefix[-1] == "ghm"


def test_resolves_path_lookup(
    fake_exe: Path,
    _clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``shutil.which`` 命中 path_lookup_name → 返回查到的路径。"""
    monkeypatch.setattr(
        "backend.adapters.out.compute._resolver.shutil.which",
        lambda name: str(fake_exe) if name == "ghm-cli" else None,
    )
    resolver = ExecutableResolver(config={"path_lookup_name": "ghm-cli"})

    result = resolver.resolve()

    assert result.argv_prefix == [str(fake_exe)]
    assert result.source == "path_lookup"


def test_default_path_lookup_name(
    fake_exe: Path,
    _clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """path_lookup_name 缺省时使用 ``ghm-cli``。"""
    monkeypatch.setattr(
        "backend.adapters.out.compute._resolver.shutil.which",
        lambda name: str(fake_exe) if name == "ghm-cli" else None,
    )
    resolver = ExecutableResolver(config={})  # 完全空配置 → 仅触发 PATH 查找

    result = resolver.resolve()

    assert result.source == "path_lookup"


# ---------- 优先级 ----------


def test_executable_path_beats_python_module(
    fake_exe: Path,
    another_fake_exe: Path,
    _clean_env: None,
) -> None:
    """executable_path 命中即返回，python_module 不再尝试。"""
    resolver = ExecutableResolver(
        config={
            "executable_path": str(fake_exe),
            "python_module": {"python": str(another_fake_exe), "module": "ghm"},
        },
    )

    result = resolver.resolve()

    assert result.source == "executable_path"
    assert result.argv_prefix == [str(fake_exe)]


def test_env_var_overrides_yaml(
    fake_exe: Path,
    another_fake_exe: Path,
    _clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GHM_EXECUTABLE_PATH 环境变量优先于 yaml.executable_path。"""
    monkeypatch.setenv("GHM_EXECUTABLE_PATH", str(another_fake_exe))
    resolver = ExecutableResolver(config={"executable_path": str(fake_exe)})

    result = resolver.resolve()

    assert result.argv_prefix == [str(another_fake_exe)]


def test_sidecar_field_skipped_when_not_implemented(
    fake_exe: Path,
    _clean_env: None,
) -> None:
    """sidecar_name 当前实现是 no-op，回退到 python_module 命中。"""
    resolver = ExecutableResolver(
        config={
            "sidecar_name": "ghm-cli",  # 当前实现仅记录到 tried，不解析
            "python_module": {"python": str(fake_exe), "module": "ghm"},
        },
    )

    result = resolver.resolve()

    assert result.source == "python_module"


# ---------- 失败路径 ----------


def test_all_sources_fail_raises(_clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """所有来源都不可用 → 抛 ExecutableNotFoundError 并列出 tried。"""
    monkeypatch.setattr(
        "backend.adapters.out.compute._resolver.shutil.which",
        lambda name: None,
    )
    resolver = ExecutableResolver(
        config={
            "executable_path": "/nonexistent/ghm-cli",
            "python_module": {"python": "/also/nonexistent/python", "module": "ghm"},
        },
    )

    with pytest.raises(ExecutableNotFoundError) as exc_info:
        resolver.resolve()

    tried_str = " ".join(exc_info.value.tried)
    assert "executable_path=/nonexistent/ghm-cli" in tried_str
    assert "python_module" in tried_str
    assert "shutil.which" in tried_str


def test_nonexistent_path_is_skipped(
    fake_exe: Path,
    _clean_env: None,
) -> None:
    """yaml.executable_path 不存在时 → 回退到下一级别。"""
    resolver = ExecutableResolver(
        config={
            "executable_path": "/no/such/file",
            "python_module": {"python": str(fake_exe), "module": "ghm"},
        },
    )

    result = resolver.resolve()

    assert result.source == "python_module"


def test_non_executable_file_is_skipped(
    tmp_path: Path,
    fake_exe: Path,
    _clean_env: None,
) -> None:
    """文件存在但无 +x 权限时 → 跳过。"""
    plain = tmp_path / "not-executable"
    plain.write_text("plain text\n")  # 无 +x
    resolver = ExecutableResolver(
        config={
            "executable_path": str(plain),
            "python_module": {"python": str(fake_exe), "module": "ghm"},
        },
    )

    result = resolver.resolve()

    assert result.source == "python_module"


# ---------- 缓存 ----------


def test_resolve_is_cached(
    fake_exe: Path,
    _clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多次 resolve() 不应重复触发 IO 检查。"""
    call_count = {"n": 0}

    original_is_file = Path.is_file

    def counting_is_file(self: Path) -> bool:
        call_count["n"] += 1
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", counting_is_file)

    resolver = ExecutableResolver(config={"executable_path": str(fake_exe)})
    first = resolver.resolve()
    count_after_first = call_count["n"]
    second = resolver.resolve()

    assert first is second  # 同一对象（缓存命中）
    assert call_count["n"] == count_after_first  # 第二次未触发 IO


def test_invalidate_clears_cache(
    fake_exe: Path,
    _clean_env: None,
) -> None:
    """invalidate() 后下次 resolve 会重新查询。"""
    resolver = ExecutableResolver(config={"executable_path": str(fake_exe)})
    first = resolver.resolve()
    resolver.invalidate()
    second = resolver.resolve()

    assert first is not second  # 新对象（重新生成）
    assert first.argv_prefix == second.argv_prefix


# ---------- 数据结构 ----------


def test_resolved_executable_defaults() -> None:
    """ResolvedExecutable 的可选字段默认值。"""
    r = ResolvedExecutable(argv_prefix=["x"])

    assert r.working_dir is None
    assert r.env is None
    assert r.source == ""
