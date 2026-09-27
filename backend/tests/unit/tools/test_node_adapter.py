"""R169 — Node.js 运行时适配器单元测试。

覆盖：PATH 发现（版本解析/去重/工具链）、include_paths 注入、
_mark_default 默认标记、build_command（argv + stdin_payload）、
inspect 的 platform 解析、discover_manifests（package.json engines/
scripts + tsconfig）、diagnose 的 NODE_RUNTIME_MISSING 与 SATISFIED。
fake safe_run 按 argv 分派；PATH 指向 tmp 目录放假可执行文件。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.domain.runtime import (
    ExecutionRequest,
    ProbeRequest,
    RuntimeInfo,
    RuntimeSource,
)
from backend.tools.adapters.node_adapter import (
    NodeAdapter,
    _mark_default,
    _pick_default,
)

pytestmark = pytest.mark.unit


class _FakeCtx:
    def __init__(self, root, responses):
        self.workspace_root = root

        def safe_run(argv, **kwargs):
            key = argv[1] if len(argv) > 1 else ""
            if key == "-v":
                return responses["node_v"]
            if key == "--version":
                tool = argv[0]
                return responses.get(f"tool:{tool}", responses["tool_default"])
            if key == "-e":
                return responses["platform"]
            return SafeRunNone()

        self.safe_run = safe_run


class SafeRunNone:
    exit_code = 1
    stdout = ""
    stderr = ""
    duration_seconds = 0.0
    timed_out = False
    output_truncated = False
    error = "unhandled"


@pytest.fixture()
def fake_env(tmp_path, monkeypatch):
    """在 tmp PATH 目录放假 node 可执行文件，fake safe_run 返回版本。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    node = bin_dir / "node.exe"
    node.write_bytes(b"")
    node.chmod(0o755)  # Linux CI 需要 X_OK；Windows 下 X_OK 恒真不受影响
    monkeypatch.setenv("PATH", str(bin_dir))

    responses = {
        "node_v": SimpleNamespace(
            exit_code=0, stdout="v20.5.0\n", stderr="", timed_out=False
        ),
        "platform": SimpleNamespace(
            exit_code=0,
            stdout='{"platform": "win32"}\n',
            stderr="",
            timed_out=False,
        ),
        "tool_default": SimpleNamespace(
            exit_code=1, stdout="", stderr="", timed_out=False
        ),
    }
    ctx = SimpleNamespace(workspace_root=tmp_path)
    ctx.safe_run = lambda argv, **kw: _dispatch_fake(argv, responses)
    monkeypatch.setattr(os, "environ", os.environ)
    return {"bin_dir": bin_dir, "responses": responses, "ctx": ctx}


import os  # noqa: E402


def _dispatch_fake(argv, responses):
    key = argv[1] if len(argv) > 1 else ""
    if key == "-v":
        return responses["node_v"]
    if key == "--version":
        return responses.get(f"tool:{argv[0]}", responses["tool_default"])
    if key == "-e":
        return responses["platform"]
    return SimpleNamespace(exit_code=1, stdout="", stderr="", timed_out=False)


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


def test_discover_finds_node_via_path(fake_env):
    adapter = NodeAdapter()
    results = adapter.discover(ProbeRequest(), fake_env["ctx"])
    nodes = [r for r in results if r.name == "Node.js"]
    assert len(nodes) == 1
    assert nodes[0].version == "20.5.0"
    assert nodes[0].source == RuntimeSource.SYSTEM
    assert nodes[0].is_default is True
    assert nodes[0].capabilities.can_execute is True


def test_discover_nonzero_exit_skips(fake_env):
    fake_env["responses"]["node_v"] = SimpleNamespace(
        exit_code=1, stdout="", stderr="", timed_out=False
    )
    results = NodeAdapter().discover(ProbeRequest(), fake_env["ctx"])
    assert all(r.name != "Node.js" for r in results)


def test_discover_no_version_match_skips(fake_env):
    fake_env["responses"]["node_v"] = SimpleNamespace(
        exit_code=0, stdout="garbage", stderr="", timed_out=False
    )
    results = NodeAdapter().discover(ProbeRequest(), fake_env["ctx"])
    assert all(r.name != "Node.js" for r in results)


def test_include_paths_direct_injection(fake_env, tmp_path):
    extra = tmp_path / "extra-node"
    extra.write_bytes(b"")
    adapter = NodeAdapter()
    results = adapter.discover(
        ProbeRequest(include_paths=(str(extra),)),
        fake_env["ctx"],
    )
    # include_paths 直接注入候选；与 PATH 中的 node.exe 同名 "Node.js"，
    # _mark_default 按名去重后只保留首个命中
    assert [r.path for r in results] == [
        str(fake_env["bin_dir"] / "node.exe")
    ]


def test_mark_default_first_node_only():
    base = {"language": "javascript", "name": "Node.js", "version": "1"}
    r1 = RuntimeInfo(path="p", **base, source=RuntimeSource.SYSTEM)
    r2 = RuntimeInfo(path="p2", **{**base, "name": "Node.js 2"}, source=RuntimeSource.TOOLCHAIN)
    npm = {"language": "javascript", "name": "npm", "path": "q", "version": "2"}
    r3 = RuntimeInfo(**npm, source=RuntimeSource.TOOLCHAIN)
    marked = _mark_default([r1, r2, r3])
    assert [m.is_default for m in marked] == [True, False, False]


# ---------------------------------------------------------------------------
# build_command / inspect
# ---------------------------------------------------------------------------


def test_build_command_uses_stdin_payload():
    adapter = NodeAdapter()
    runtime = RuntimeInfo(language="javascript", name="n", path="/node", version="20")
    request = ExecutionRequest(language="javascript", runtime_path="/node", code="console.log(1)")
    cmd = adapter.build_command(request, runtime, ctx=None)
    assert cmd.argv == ["/node", "-"]
    assert cmd.stdin_payload == "console.log(1)"


def test_inspect_parses_platform(fake_env):
    adapter = NodeAdapter()
    runtime = RuntimeInfo(language="javascript", name="n", path="/node", version="20")
    out = adapter.inspect(runtime, fake_env["ctx"])
    assert out.raw["platform"] == "win32"


def test_inspect_invalid_json_keeps_platform_none(fake_env, monkeypatch):
    fake_env["responses"]["platform"] = SimpleNamespace(
        exit_code=0, stdout="not-json", stderr="", timed_out=False
    )
    adapter = NodeAdapter()
    runtime = RuntimeInfo(language="javascript", name="n", path="/node", version="20")
    out = adapter.inspect(runtime, fake_env["ctx"])
    assert out.raw.get("platform") is None


# ---------------------------------------------------------------------------
# discover_manifests / diagnose
# ---------------------------------------------------------------------------


def test_manifests_package_json_and_tsconfig(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"engines": {"node": ">=18"}, "scripts": {"build": "tsc", "lint": "eslint"}}),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    adapter = NodeAdapter()
    manifests = adapter.discover_manifests(tmp_path)
    kinds = [m.kind for m in manifests]
    assert kinds == ["package.json", "tsconfig"]
    pkg = manifests[0]
    assert pkg.requires == ("build", "lint")  # scripts 键排序
    assert pkg.extras["engines_node"] == ">=18"


def test_manifests_malformed_package_json_tolerated(tmp_path):
    # 坏 JSON 不抛错：manifest 仍在，requires/extras 退化为空
    (tmp_path / "package.json").write_text("{broken", encoding="utf-8")
    manifests = NodeAdapter().discover_manifests(tmp_path)
    assert len(manifests) == 1
    assert manifests[0].requires == ()
    assert manifests[0].extras == {}


def test_diagnose_missing_node_runtime(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    diagnosis = NodeAdapter().diagnose(tmp_path, runtimes=[], ctx=None)
    assert diagnosis.level.value == "unsatisfied"
    assert diagnosis.diagnostics[0].code == "NODE_RUNTIME_MISSING"


def test_diagnose_with_node_satisfied(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    runtime = RuntimeInfo(
        language="javascript", name="Node.js", path="/node", version="20",
        source=RuntimeSource.SYSTEM, is_default=True,
    )
    diagnosis = NodeAdapter().diagnose(tmp_path, runtimes=[runtime], ctx=None)
    assert diagnosis.level.value == "satisfied"
    assert diagnosis.recommended_runtime == "/node"


def test_pick_default_prefers_marked():
    r1 = RuntimeInfo(language="j", name="npm", path="q", version="2", source=RuntimeSource.TOOLCHAIN)
    r2 = RuntimeInfo(language="j", name="Node.js", path="p", version="1",
                     source=RuntimeSource.SYSTEM, is_default=True)
    assert _pick_default([r1, r2]) is r2
    assert _pick_default([]) is None
