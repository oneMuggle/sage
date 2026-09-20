"""Task 1 回归测试——技能运行时与注册断言。

本文件写于 Task 1（TDD 红阶段），断言下列预期行为：

1. shipped 技能（如 academic-search）在生产 ``InprocSkillAdapter`` 中可见
   ——当前实现因显式传 ``dirs=[...]`` 绕过 shipped fallback 而失败。
2. shipped 目录**不**应出现在 ``ScriptRunner`` 的 allowed_roots 中
   ——当前实现尚未修复，本断言与 (1) 共同约束 Task 2 的分离修复。
3. 存在一个非密钥运行时上下文 helper
   ``backend.tools.skill_runtime_context.get_runtime_context()``，
   返回 ``python_path`` 与 ``env`` 字段，且不泄漏任何密钥。
4. 外部技能契约（storage-analyzer 形状：``when_to_use`` + ``user-invocable``
   + script，无 ``requires.bins``）应在显式 ``SAGE_SKILLS_DIR`` 下被发现、
   自动激活使用 ``when_to_use``、slash 列表包含该命令，且在没有
   ``requires`` 时不会发生隐式 Python 门控。
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. shipped 技能应在生产 adapter 中可见
# ---------------------------------------------------------------------------


def test_shipped_skill_visible_in_production_adapter(tmp_path, monkeypatch):
    """InprocSkillAdapter() 默认应装载 shipped/academic-search。"""
    import backend.adapters.out.skill.inproc as inproc_mod
    from backend.adapters.out.skill.inproc import InprocSkillAdapter

    # 隔离：清空单例 + 设置一个不存在的 SAGE_SKILLS_DIR
    # 以便只依赖 shipped fallback。
    monkeypatch.delenv("SAGE_SKILLS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    # 避免 cwd/skills 与 ~/.sage/skills 干扰
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    inproc_mod._skill_adapter_singleton = None

    try:
        adapter = InprocSkillAdapter()
        names = {s.name for s in adapter.list_skills()}
        assert "academic-search" in names, (
            f"shipped academic-search 应被 adapter 装载,实际名称集合: {sorted(names)}"
        )
    finally:
        inproc_mod._skill_adapter_singleton = None


# ---------------------------------------------------------------------------
# 2. shipped 目录不应出现在 ScriptRunner 的 allowed_roots
# ---------------------------------------------------------------------------


def test_shipped_dir_not_in_script_runner_allowed_roots(tmp_path, monkeypatch):
    """ScriptRunner 的 allowed_roots 仅含用户根,不含 shipped/。"""
    import backend.adapters.out.skill.inproc as inproc_mod
    from backend.adapters.out.skill.inproc import InprocSkillAdapter
    from backend.skills.skill_md.loader import _discover_shipped_dir

    user_root = tmp_path / "user-skills"
    user_root.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(user_root))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    inproc_mod._skill_adapter_singleton = None

    try:
        adapter = InprocSkillAdapter()
        if adapter._script_runner is None:
            pytest.skip("adapter init 未构造 script_runner（init-time 容错跳过）")

        allowed = [Path(p).resolve() for p in adapter._script_runner._allowed_roots]
        shipped = _discover_shipped_dir()
        if shipped is None:
            pytest.skip("shipped 目录在本仓库不存在,无法断言排除")

        shipped_resolved = shipped.resolve()
        assert shipped_resolved not in allowed, (
            f"shipped 目录 {shipped_resolved} 不应出现在 ScriptRunner.allowed_roots"
        )
        # 用户根应被包含
        assert user_root.resolve() in allowed, (
            f"用户根 {user_root} 应在 ScriptRunner.allowed_roots 中"
        )

        # 同时,shipped 技能仍应在 registry 中（双重约束）
        names = {s.name for s in adapter.list_skills()}
        assert "academic-search" in names
    finally:
        inproc_mod._skill_adapter_singleton = None


# ---------------------------------------------------------------------------
# 3. 运行时上下文 helper 不泄漏密钥
# ---------------------------------------------------------------------------


_SECRETS = (
    "SAGE_LOCAL_AUTH_TOKEN",
    "SAGE_BACKEND_OWNERSHIP_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
)


def test_runtime_context_helper_exists_and_is_non_secret(monkeypatch):
    """``get_runtime_context()`` 返回 dict，含 ``python_path``/``env`` 键,
    且 env 字典不暴露任何已知密钥。"""
    fake_python = "/opt/sage/venv/bin/python"
    monkeypatch.setenv("SAGE_RUNTIME_PYTHON", fake_python)

    # 同时塞几个密钥,确保 helper 不过滤性转发
    for key in _SECRETS:
        monkeypatch.setenv(key, "super-secret-value")

    from backend.tools.skill_runtime_context import get_runtime_context

    ctx = get_runtime_context()
    assert isinstance(ctx, dict), f"runtime context 应为 dict,实际 {type(ctx)}"
    assert "python_path" in ctx
    assert "env" in ctx

    # python_path 必须是注入的 fake 路径;收紧为严格等值,
    # 避免 Task 3 实现返回 None 的退化实现也能过测。
    assert ctx["python_path"] == fake_python, (
        f"runtime context.python_path 应等于注入的 SAGE_RUNTIME_PYTHON,实际: {ctx['python_path']!r}"
    )

    # env 字段是 dict,不泄漏任何密钥
    env = ctx["env"]
    assert isinstance(env, dict)
    for key in _SECRETS:
        assert key not in env, f"runtime context.env 不应包含密钥 {key}"


def test_runtime_context_returns_none_path_when_env_absent(monkeypatch):
    """SAGE_RUNTIME_PYTHON 缺失 → python_path 为 None,且不回落到其他变量。"""
    monkeypatch.delenv("SAGE_RUNTIME_PYTHON", raising=False)
    # 故意设置一个诱惑变量,确保 helper 不走 fallback
    monkeypatch.setenv("CONDA_PREFIX", "/opt/conda/envs/sage-backend")

    from backend.tools.skill_runtime_context import get_runtime_context

    ctx = get_runtime_context()
    # python_path 必须不来自 CONDA_PREFIX 或其他推断
    assert ctx.get("python_path") is None


# ---------------------------------------------------------------------------
# 4. 外部技能契约：storage-analyzer 形状
# ---------------------------------------------------------------------------


def _write_storage_analyzer_skill(root: Path) -> Path:
    """在 root 下写一个 storage-analyzer SKILL.md（no requires,有 script）。"""
    root.mkdir(parents=True, exist_ok=True)
    skill_md = root / "SKILL.md"
    skill_md.write_text(
        """---
name: storage-analyzer
description: 扫描本地目录并输出存储占用报告。
when_to_use: 分析磁盘占用，查找大文件，清理存储
user-invocable: true
user-invocable-name: /storage-analyzer
---

# Storage Analyzer

使用方式：运行 `python3 scripts/scan.py <dir>` 扫描指定目录。
""",
        encoding="utf-8",
    )
    # 写一个占位 script,确保 script 目录存在
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    scan_py = scripts_dir / "scan.py"
    scan_py.write_text("# placeholder\n", encoding="utf-8")
    scan_py.chmod(scan_py.stat().st_mode | stat.S_IXUSR)
    return skill_md


def test_external_skill_contract_discoverable_and_auto_activates(
    tmp_path, monkeypatch
):
    """storage-analyzer 形状的外部技能应在 SAGE_SKILLS_DIR 下被发现、
    通过 when_to_use 自动激活、出现在 slash 列表,且没有 requires 时
    不发生隐式 Python 门控。"""
    import backend.adapters.out.skill.inproc as inproc_mod
    from backend.adapters.out.skill.inproc import InprocSkillAdapter

    skills_root = tmp_path / "external-skills"
    _write_storage_analyzer_skill(skills_root / "storage-analyzer")

    monkeypatch.setenv("SAGE_SKILLS_DIR", str(skills_root))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    inproc_mod._skill_adapter_singleton = None

    try:
        adapter = InprocSkillAdapter()

        # 1) discoverable
        names = {s.name for s in adapter.list_skills()}
        assert "storage-analyzer" in names, (
            f"storage-analyzer 应被发现,实际: {sorted(names)}"
        )

        # 2) auto-activation uses when_to_use
        result = adapter.auto_activate("帮我分析磁盘占用")
        assert "storage-analyzer" in result.names, (
            f"when_to_use 应命中'磁盘占用',实际命中: {result.names}"
        )

        # 3) slash listing includes it
        slash_cmds = adapter.list_slash_commands()
        assert "/storage-analyzer" in slash_cmds, (
            f"/storage-analyzer 应出现在 slash 列表,实际: {slash_cmds}"
        )

        # 4) 没有 requires.bins → 不因缺 python3 而被门控掉
        # 通过 list_skills 已能看见 → 门控未拦。这里额外断言:
        # 即使 PATH 里没有 python3,技能仍然可用(即 requires 为空时
        # 不做隐式 Python 探测)。
        monkeypatch.setenv("PATH", "/empty-path")
        inproc_mod._skill_adapter_singleton = None
        adapter_no_python = InprocSkillAdapter()
        names2 = {s.name for s in adapter_no_python.list_skills()}
        assert "storage-analyzer" in names2, (
            "无 requires.bins 时不应因缺 python3 而被隐式门控"
        )
    finally:
        inproc_mod._skill_adapter_singleton = None
