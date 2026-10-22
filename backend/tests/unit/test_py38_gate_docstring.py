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


def test_docstring_mention_is_not_a_violation(tmp_path) -> None:
    """文档里写 `Path.is_relative_to()` 是在说明「我们没用它」，不是调用。"""
    gate = _load_gate_module()
    src = (
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def is_within(a, b):\n"
        '    """\n'
        "    Equivalent to ``Path.is_relative_to()`` but available on 3.8+.\n"
        "\n"
        "    Also mentions .removesuffix( and .with_stem( in prose.\n"
        '    """\n'
        "    try:\n"
        "        a.relative_to(b)\n"
        "    except ValueError:\n"
        "        return False\n"
        "    return True\n"
    )
    target = tmp_path / "doc_prose.py"
    target.write_text(src, encoding="utf-8")
    issues = gate.check_runtime_apis(target, tmp_path)
    assert issues == [], issues


def test_real_call_is_still_a_violation(tmp_path) -> None:
    """去字符串不能把真调用一起放过。"""
    gate = _load_gate_module()
    src = (
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def f(a, b):\n"
        "    return a.is_relative_to(b)\n"
    )
    target = tmp_path / "real_call.py"
    target.write_text(src, encoding="utf-8")
    issues = gate.check_runtime_apis(target, tmp_path)
    assert len(issues) == 1
    assert "Path.is_relative_to" in issues[0][1]
