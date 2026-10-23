"""R122 — SKILL.md 安全校验单元测试。

覆盖：validate_base_dir 的根包含判定（含前缀兄弟目录、`..` 遍历解析、
多根任一命中、空根列表）、sanitize_for_logging 的控制字符剥离/截断/
非 str 强转。
"""

from __future__ import annotations

import pytest

from backend.skills.skill_md.validation import (
    SkillMdSecurityError,
    sanitize_for_logging,
    validate_base_dir,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# validate_base_dir
# ---------------------------------------------------------------------------


def test_base_under_allowed_root_passes(tmp_path):
    root = tmp_path / "skills"
    base = root / "my-skill"
    base.mkdir(parents=True)
    result = validate_base_dir(base, [root])
    assert result == base.resolve()


def test_base_outside_roots_rejected(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    outsider = tmp_path / "elsewhere"
    outsider.mkdir()
    with pytest.raises(SkillMdSecurityError) as excinfo:
        validate_base_dir(outsider, [root])
    # 消息含双方路径组件（Windows 下分隔符被 repr 转义，故按组件断言）
    message = str(excinfo.value)
    assert "elsewhere" in message
    assert "skills" in message


def test_empty_allowed_roots_rejected(tmp_path):
    with pytest.raises(SkillMdSecurityError, match="no allowed_roots"):
        validate_base_dir(tmp_path, [])


def test_nonexistent_paths_resolve_without_strict(tmp_path):
    # 目录尚未创建（如安装期）也应可校验：resolve(strict=False)
    root = tmp_path / "skills"
    base = root / "not-yet-installed"
    result = validate_base_dir(base, [root])
    assert result == (tmp_path / "skills" / "not-yet-installed").resolve()


def test_prefix_sibling_directory_not_confused_with_root(tmp_path):
    # /root2 与 /root 前缀重合但非包含——遍历防御的经典误判点
    root = tmp_path / "root"
    sibling_base = tmp_path / "root2" / "skill"
    sibling_base.mkdir(parents=True)
    root.mkdir()
    with pytest.raises(SkillMdSecurityError):
        validate_base_dir(sibling_base, [root])


def test_dotdot_escape_rejected(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    sneaky = root / ".." / "escape"
    with pytest.raises(SkillMdSecurityError):
        validate_base_dir(sneaky, [root])


def test_any_of_multiple_roots_accepts(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    base = root_b / "skill"
    base.mkdir()
    assert validate_base_dir(base, [root_a, root_b]) == base.resolve()


# ---------------------------------------------------------------------------
# sanitize_for_logging
# ---------------------------------------------------------------------------


def test_control_chars_replaced_with_question_marks():
    dirty = "a\x00b\x07c\x1fd\x7f"
    assert sanitize_for_logging(dirty) == "a?b?c?d?"


def test_tab_and_newline_preserved():
    assert sanitize_for_logging("line1\nline2\tend") == "line1\nline2\tend"


def test_long_text_truncated_with_total_length():
    text = "x" * 250
    out = sanitize_for_logging(text, max_len=200)
    assert out == "x" * 200 + "...(truncated, total 250 chars)"


def test_custom_max_len():
    assert sanitize_for_logging("abcdef", max_len=3) == "abc...(truncated, total 6 chars)"


def test_non_string_input_coerced():
    assert sanitize_for_logging(12345) == "12345"
    assert sanitize_for_logging(None) == "None"


def test_short_text_untouched():
    assert sanitize_for_logging("普通文本", max_len=200) == "普通文本"
