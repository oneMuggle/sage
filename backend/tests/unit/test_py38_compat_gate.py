# ruff: noqa: UP006, UP007, UP035
"""Unit and repository-wide contract tests for scripts/check_py38_compat.py (L4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_py38_compat.py"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("check_py38_compat", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_py38_compat"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_detects_missing_future_annotations() -> None:
    gate = _load_gate_module()
    bad_src = "def f(x: int | None) -> list[str]:\n    return []\n"
    issues = gate.check_source(bad_src, filename="sample_no_future.py")
    assert len(issues) == 2
    assert all("missing `from __future__ import annotations`" in i for i in issues)


def test_allows_future_annotations_for_regular_functions() -> None:
    gate = _load_gate_module()
    ok_src = (
        "from __future__ import annotations\n\n"
        "def f(x: int | None) -> list[str]:\n"
        "    return []\n"
    )
    assert gate.check_source(ok_src, filename="sample_ok.py") == []


def test_detects_runtime_isinstance_union() -> None:
    gate = _load_gate_module()
    bad_src = (
        "from __future__ import annotations\n\n"
        "def f(x: object) -> bool:\n"
        "    return isinstance(x, int | str)\n"
    )
    issues = gate.check_source(bad_src, filename="sample_isinstance.py")
    assert len(issues) == 1
    assert "isinstance() uses PEP 604 `|` union at runtime" in issues[0]


def test_detects_pydantic_and_fastapi_runtime_annotations() -> None:
    gate = _load_gate_module()
    bad_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class ItemRequest(BaseModel):\n"
        "    tags: list[str]\n\n"
        "@router.post('/items')\n"
        "def create_item(q: str | None = None) -> dict[str, int]:\n"
        "    return {}\n"
    )
    issues = gate.check_source(bad_src, filename="sample_api.py")
    assert len(issues) == 3
    assert any("Pydantic model `ItemRequest`" in i for i in issues)
    assert any("FastAPI route `create_item` param `q`" in i for i in issues)
    assert any("FastAPI route `create_item` return annotation" in i for i in issues)


<<<<<<< HEAD


def test_detects_bare_model_rebuild_without_guard() -> None:
    """裸 `.model_rebuild()` 必须报 —— win7 垫片不注入它，py38 通道导入期就崩。"""
    gate = _load_gate_module()
    bad_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class M(BaseModel):\n"
        "    x: int = 0\n\n"
        "M.model_rebuild()\n"
    )
    issues = gate.check_source(bad_src, filename="sample_rebuild.py")
    hits = [i for i in issues if "bare `.model_rebuild()`" in i]
    assert len(hits) == 1, issues


def test_allows_guarded_model_rebuild() -> None:
    """hasattr 双版本守卫必须豁免（project_ai_routes.py / office/models.py 的形态）。"""
    gate = _load_gate_module()
    ok_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class M(BaseModel):\n"
        "    x: int = 0\n\n"
        'if hasattr(M, "model_rebuild"):\n'
        "    M.model_rebuild()\n"
        "else:\n"
        "    M.update_forward_refs()\n"
    )
    assert gate.check_source(ok_src, filename="sample_guarded.py") == []


def test_allows_for_loop_rebuild_guard() -> None:
    """`for _cls in (...)` 循环守卫体必须豁免（office/models.py 末尾的形态）。"""
    gate = _load_gate_module()
    ok_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class S(BaseModel):\n"
        '    x: "T" = None\n\n'
        "class T(BaseModel):\n"
        "    y: int = 0\n\n"
        "for _cls in (S, T):\n"
        '    if hasattr(_cls, "update_forward_refs"):\n'
        "        _cls.update_forward_refs()\n"
        '    elif hasattr(_cls, "model_rebuild"):\n'
        "        _cls.model_rebuild()\n"
    )
    assert gate.check_source(ok_src, filename="sample_loop_guard.py") == []


def test_rejects_guard_for_a_different_model() -> None:
    """守卫对象与调用对象不一致时仍要报 —— 防止「加了个不相干的守卫」蒙混过关。"""
    gate = _load_gate_module()
    bad_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class A(BaseModel):\n"
        "    x: int = 0\n\n"
        "class B(BaseModel):\n"
        "    y: int = 0\n\n"
        'if hasattr(A, "model_rebuild"):\n'
        "    B.model_rebuild()\n"
    )
    issues = gate.check_source(bad_src, filename="sample_mismatch.py")
    hits = [i for i in issues if "bare `.model_rebuild()`" in i]
    assert len(hits) == 1, issues


def test_detects_pydantic_forward_ref_to_later_class() -> None:
    """pydantic 字段引用本文件更晚定义的类必须报（v1 创建期解析 → ConfigError）。"""
    gate = _load_gate_module()
    bad_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class Outer(BaseModel):\n"
        '    inner: "Inner"\n\n'
        "class Inner(BaseModel):\n"
        "    v: int = 0\n"
    )
    issues = gate.check_source(bad_src, filename="sample_fwdref.py")
    hits = [i for i in issues if "forward-references `Inner`" in i]
    assert len(hits) == 1, issues


def test_allows_forward_ref_when_class_defined_earlier() -> None:
    """被引用类定义在使用点之前是合法解法（win7 对 WordIndexSpec 用的就是这个）。"""
    gate = _load_gate_module()
    ok_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class Early(BaseModel):\n"
        "    v: int = 0\n\n"
        "class Uses(BaseModel):\n"
        "    e: Early\n"
    )
    assert gate.check_source(ok_src, filename="sample_earlier.py") == []


def test_allows_forward_ref_covered_by_update_forward_refs() -> None:
    """末尾守卫循环/显式 update_forward_refs() 覆盖的类必须豁免。"""
    gate = _load_gate_module()
    ok_src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class G(BaseModel):\n"
        '    late: "Late2"\n\n'
        "class Late2(BaseModel):\n"
        "    v: int = 0\n\n"
        "G.update_forward_refs()\n"
    )
    assert gate.check_source(ok_src, filename="sample_guarded_fwd.py") == []


def test_ignores_forward_refs_in_non_pydantic_classes() -> None:
    """普通类 / abc / BaseHTTPRequestHandler 的前向引用不在创建期解析，不该报。

    回归：browser_launcher.py 的 `BrowserCapability.launcher` 与
    mock_server.py 的 `MockLLMHandler.state` 曾被误报。
    """
    gate = _load_gate_module()
    plain_src = (
        "from __future__ import annotations\n"
        "import abc\n\n"
        "class Capability:\n"
        "    launcher: Launcher\n\n"
        "class Launcher(abc.ABC):\n"
        "    @abc.abstractmethod\n"
        "    def run(self) -> None: ...\n"
    )
    assert gate.check_source(plain_src, filename="sample_plain.py") == []

    handler_src = (
        "from __future__ import annotations\n"
        "from http.server import BaseHTTPRequestHandler\n\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_POST(self) -> None:\n"
        "        state: Server = self.server.mock_state\n"
        "        state.record()\n\n"
        "class Server:\n"
        "    def record(self) -> None: ...\n"
    )
    assert gate.check_source(handler_src, filename="sample_handler.py") == []


def test_ignores_method_parameter_annotations() -> None:
    """方法参数注解不是 pydantic 字段，不该被规则 B 命中。

    回归：download_tool.py 的 `HttpDownloadTool._consume(ctx: _DownloadContext)`
    曾被误报成字段前向引用。
    """
    gate = _load_gate_module()
    src = (
        "from __future__ import annotations\n"
        "from pydantic import BaseModel\n\n"
        "class Tool(BaseModel):\n"
        '    name: str = ""\n\n'
        "    def _consume(self, ctx: Ctx, url: str) -> None:\n"
        "        return None\n\n"
        "class Ctx(BaseModel):\n"
        '    path: str = ""\n'
    )
    issues = gate.check_source(src, filename="sample_param.py")
    assert [i for i in issues if "forward-references" in i] == [], issues


def test_ignores_runtime_api_names_inside_docstrings() -> None:
    """docstring 里讨论 `model_rebuild()` 不该报（_strip_strings 已抹掉字符串）。"""
    gate = _load_gate_module()
    src = (
        "from __future__ import annotations\n\n"
        "def helper() -> None:\n"
        '    """Do NOT call M.model_rebuild() directly; use the hasattr guard.\n\n'
        "    The win7 shim injects model_dump but not model_rebuild().\n"
        '    """\n'
        "    return None\n"
    )
    assert gate.check_source(src, filename="sample_docstring.py") == []


def test_detects_removed_pydantic_field_kwargs() -> None:
    """pydantic v2 已移除的 Field kwargs 必须报。

    回归背景：#2550 在 legacy_memory_routes.py 写了
    ``Field(regex="^(up|down)$")``，使 ``backend.main`` 在 pydantic 2.x 下
    导入期就抛 ``PydanticUserError``；又因 setup_test_db 是 autouse，整个套件在
    setup 期全 E。而 py38 通道钉 pydantic 1.10.13（regex= 合法）、唯一能跑 v2 的
    job 是 SKIPPED —— 两个 CI 通道都看不见，只能靠这条静态规则兜底。
    """
    gate = _load_gate_module()
    cases = (
        ("regex", "pattern"),
        ("min_items", "min_length"),
        ("max_items", "max_length"),
        ("unique_items", "field_validator"),
        ("allow_mutation", "frozen"),
        ("const", "Literal"),
    )
    for kwarg, replacement in cases:
        src = (
            "from __future__ import annotations\n"
            "from pydantic import Field\n\n"
            "class M(BaseModel):\n"
            "    f: str = Field(" + kwarg + '="x")\n'
        )
        issues = [i for i in gate.check_source(src, filename="t.py") if "pydantic v2 removed" in i]
        assert len(issues) == 1, (kwarg, issues)
        assert "Field(" + kwarg + "=...)" in issues[0]
        assert replacement in issues[0]


def test_detects_removed_field_kwargs_across_lines() -> None:
    """跨行写法也要抓到 —— 这正是用 AST 而非正则的理由。"""
    gate = _load_gate_module()
    src = (
        "from __future__ import annotations\n"
        "from pydantic import Field\n\n"
        "class M(BaseModel):\n"
        "    f: str = Field(\n"
        "        " + "regex" + '="x",\n'
        "    )\n"
    )
    issues = [i for i in gate.check_source(src, filename="t.py") if "pydantic v2 removed" in i]
    assert len(issues) == 1, issues


def test_allows_v2_style_field_kwargs() -> None:
    """修复后的正确写法（pattern= / min_length= / max_length=）不得误报。"""
    gate = _load_gate_module()
    src = (
        "from __future__ import annotations\n"
        "from pydantic import Field\n\n"
        "class M(BaseModel):\n"
        '    a: str = Field(pattern="^(up|down)$")\n'
        "    b: str = Field(min_length=1)\n"
        "    c: str = Field(max_length=10)\n"
    )
    assert [i for i in gate.check_source(src, filename="t.py") if "pydantic v2 removed" in i] == []


def test_ignores_removed_kwarg_names_outside_field_calls() -> None:
    """dict 键 / 普通函数 kwarg / **kwargs 展开都不算 Field 参数，不该误报。"""
    gate = _load_gate_module()
    samples = (
        'CFG = {"min_items": 1, "regex": "x"}\n',
        "def g(regex=None, min_items=1):\n    return regex\n",
        "from pydantic import Field\n\n"
        "class M(BaseModel):\n"
        '    f: str = Field(**{"regex": "x"})\n',
    )
    for src in samples:
        hits = [i for i in gate.check_source(src, filename="t.py") if "pydantic v2 removed" in i]
        assert hits == [], (src, hits)

=======
>>>>>>> origin/main
def test_repository_passes_py38_compat_gate() -> None:
    gate = _load_gate_module()
    targets = [REPO_ROOT / "backend", REPO_ROOT / "packages" / "sage-core"]
    violations = gate.check_paths(targets)
    assert violations == [], "Python 3.8 compatibility violations:\n" + "\n".join(violations)
