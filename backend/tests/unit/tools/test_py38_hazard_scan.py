"""R161 — py38 运行期地雷扫描器单元测试。

逐规则验证 scan_file 的命中（R1~R12）、行级 `# py38-ok` 豁免、
干净代码零命中。源码以 tmp 文件落盘后扫描，断言 (rel, lineno, msg)
命中。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.py38_hazard_scan import scan_file

pytestmark = pytest.mark.unit


def _scan(tmp_path, source, name="sample.py"):
    p = tmp_path / name
    p.write_text(source, encoding="utf-8")
    return scan_file(p, Path(name))


def _one_hit(tmp_path, source):
    hits = _scan(tmp_path, source)
    assert len(hits) == 1, f"expected 1 hit, got {hits}"
    return hits[0]


# ---------------------------------------------------------------------------
# 逐规则
# ---------------------------------------------------------------------------


def test_r1_isinstance_union(tmp_path):
    hit = _one_hit(tmp_path, "isinstance(x, int | str)\n")
    assert "isinstance" in hit[2]
    assert hit[1] == 1


def test_r2_asyncio_to_thread(tmp_path):
    hit = _one_hit(tmp_path, "asyncio.to_thread(func)\n")
    assert "asyncio.to_thread" in hit[2]


def test_r3_zip_strict(tmp_path):
    hit = _one_hit(tmp_path, "zip(a, b, strict=True)\n")
    assert "strict" in hit[2]


def test_r4_path_hardlink_to(tmp_path):
    hit = _one_hit(tmp_path, "p.hardlink_to(other)\n")
    assert "hardlink_to" in hit[2]


def test_r5_path_is_relative_to(tmp_path):
    hit = _one_hit(tmp_path, "p.is_relative_to(base)\n")
    assert "is_relative_to" in hit[2]


def test_r6_read_text_newline_kwarg(tmp_path):
    hit = _one_hit(tmp_path, "p.read_text(newline='')\n")
    assert "read_text" in hit[2]


def test_r12_datetime_utc_attribute(tmp_path):
    hit = _one_hit(tmp_path, "datetime.UTC\n")
    assert "UTC" in hit[2]


def test_r7_str_removeprefix(tmp_path):
    hit = _one_hit(tmp_path, "s.removeprefix('x')\n")
    assert "removeprefix" in hit[2]


def test_r7_free_function_not_flagged(tmp_path):
    # 同名自由函数调用（接收者不是 Name/Attribute）不误报
    hits = _scan(tmp_path, "removeprefix(s, 'x')\n")
    assert hits == []


def test_r8_import_zoneinfo_and_graphlib(tmp_path):
    hits = _scan(tmp_path, "import zoneinfo\nimport graphlib\n")
    assert len(hits) == 2
    hits_from = _scan(tmp_path, "from zoneinfo import ZoneInfo\n")
    assert len(hits_from) == 1


def test_r9_functools_cache(tmp_path):
    hit = _one_hit(tmp_path, "functools.cache\n")
    assert "functools.cache" in hit[2]


def test_r10_dataclass_slots_and_kw_only(tmp_path):
    source = (
        "from dataclasses import dataclass\n"
        "@dataclass(slots=True)\n"
        "class A:\n"
        "    pass\n"
    )
    hit = _one_hit(tmp_path, source)
    assert "dataclass" in hit[2]


def test_r10_kw_only_also_flagged(tmp_path):
    source = (
        "from dataclasses import dataclass\n"
        "@dataclass(kw_only=True)\n"
        "class B:\n"
        "    pass\n"
    )
    assert len(_scan(tmp_path, source)) == 1


# ---------------------------------------------------------------------------
# 豁免与零误报
# ---------------------------------------------------------------------------


def test_line_exempt_mark_suppresses_hit(tmp_path):
    source = "p.is_relative_to(base)  # py38-ok 已降级处理\n"
    hits = _scan(tmp_path, source)
    assert hits == []


def test_exempt_only_applies_to_marked_line(tmp_path):
    source = "p.is_relative_to(base)\np.is_relative_to(other)  # py38-ok\n"
    hits = _scan(tmp_path, source)
    assert len(hits) == 1  # 只有未标记行保留


def test_clean_code_zero_hits(tmp_path):
    source = (
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        "def main(p):\n"
        "    return Path(p).read_text(encoding='utf-8')\n"
    )
    assert _scan(tmp_path, source) == []


def test_syntax_error_propagates(tmp_path):
    source = "def broken(:" + chr(10)  # py39+ 语法，py38 解析必炸
    p = tmp_path / "bad.py"
    p.write_text(source, encoding="utf-8")
    with pytest.raises(SyntaxError):
        scan_file(p, Path("bad.py"))
