"""观察层 v2（无障碍树快照 + ref 协议）单元测试。

真实行为测试：直接检查构造出的注入 JS 与解析后的 content 结构，
不做"仅断言 mock 被调用"的空转测试。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from backend.tools.browser_observe import (
    SNAPSHOT_CANVAS_TEXT_HINT,
    SNAPSHOT_TEXT_CAP,
    build_ref_expression,
    build_snapshot_expression,
    parse_snapshot_payload,
)

pytestmark = [pytest.mark.unit]


def _element(ref: str, role: str = "button", name: str = "OK", **extra: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "ref": ref,
        "role": role,
        "name": name,
        "disabled": False,
        "in_viewport": True,
    }
    item.update(extra)
    return item


def _payload(
    elements: List[Dict[str, Any]],
    text: str = "",
    viewport: Optional[Dict[str, int]] = None,
) -> str:
    return json.dumps(
        {
            "url": "https://example.test/",
            "title": "Example",
            "viewport": viewport or {"width": 1024, "height": 768, "scroll_y": 0},
            "elements": elements,
            "elements_total": len(elements),
            "text": text,
        }
    )


# ---------------------------------------------------------------------------
# build_snapshot_expression
# ---------------------------------------------------------------------------


def test_interactive_expression_contains_collection_and_ref_protocol():
    expression = build_snapshot_expression()

    # 候选选择器（JSON 编码后引号带反斜杠，按无引号 token 断言）
    for token in (
        "a[href]",
        "area[href]",
        "summary",
        "label[for]",
        "role=checkbox",
        "role=switch",
        "contenteditable",
    ):
        assert token in expression

    # ref 注册表与元素属性
    assert "window.__SAGE_REFS__" in expression
    assert "data-sage-ref-name" in expression
    assert "data-sage-ref" in expression

    # 可见性过滤与视口信息
    assert "getClientRects" in expression
    assert "closest('[hidden],[aria-hidden=\"true\"]')" in expression
    assert "innerWidth" in expression
    assert "innerHeight" in expression
    assert "scrollY" in expression


def test_text_mode_expression_has_no_ref_registry():
    expression = build_snapshot_expression(mode="text")
    assert "window.__SAGE_REFS__" not in expression
    assert "data-sage-ref" not in expression
    assert "getClientRects" not in expression
    assert "innerText" in expression
    assert f"slice(0,{SNAPSHOT_TEXT_CAP})" in expression.replace(" ", "")


def test_expression_injects_max_collect_and_offscreen_flag():
    assert "var MAX_COLLECT = 37;" in build_snapshot_expression(max_collect=37)
    assert "var INCLUDE_OFFSCREEN = false;" in build_snapshot_expression()
    assert "var INCLUDE_OFFSCREEN = true;" in build_snapshot_expression(include_offscreen=True)


def test_invalid_mode_falls_back_to_interactive_expression():
    expression = build_snapshot_expression(mode="dance")
    assert "window.__SAGE_REFS__" in expression
    assert 'var MODE = "interactive";' in expression


# ---------------------------------------------------------------------------
# parse_snapshot_payload
# ---------------------------------------------------------------------------


def test_parse_interactive_returns_elements_total_and_viewport():
    payload = _payload(
        [
            _element("e1", name="Login"),
            _element(
                "e2",
                role="textbox",
                name="Search",
                type="search",
                value="",
                placeholder="查找",
            ),
            _element("e3", role="link", name="Home", href="/home"),
        ],
        text="正文" * 200,
    )
    content = parse_snapshot_payload(payload)

    assert content["mode"] == "interactive"
    assert content["elements_total"] == 3
    assert [item["ref"] for item in content["elements"]] == ["e1", "e2", "e3"]
    assert content["elements"][1]["placeholder"] == "查找"
    assert content["elements"][2]["href"] == "/home"
    assert content["viewport"] == {"width": 1024, "height": 768, "scroll_y": 0}
    assert content["truncated"] is False
    assert "text" not in content
    assert "hint" not in content


def test_parse_query_filters_by_role_or_name_case_insensitively():
    elements = [
        _element("e1", name="Search box"),
        _element("e2", role="link", name="Home"),
        _element("e3", role="button", name="Search"),
    ]
    content = parse_snapshot_payload(_payload(elements, text="x" * 400), query="search")
    assert content["elements_total"] == 2
    assert {item["ref"] for item in content["elements"]} == {"e1", "e3"}

    by_role = parse_snapshot_payload(_payload(elements, text="x" * 400), query="LINK")
    assert [item["ref"] for item in by_role["elements"]] == ["e2"]


def test_parse_max_nodes_truncates_and_hints_query():
    elements = [_element(f"e{index}") for index in range(1, 4)]
    content = parse_snapshot_payload(_payload(elements, text="x" * 400), max_nodes=2)

    assert content["truncated"] is True
    assert len(content["elements"]) == 2
    assert content["elements_total"] == 3
    assert "query" in content["hint"]
    assert "共 3 个交互元素，已返回前 2 个" in content["hint"]


def test_parse_max_nodes_low_and_high_are_clamped():
    elements = [_element(f"e{index}") for index in range(1, 4)]

    low = parse_snapshot_payload(_payload(elements, text="x" * 400), max_nodes=0)
    assert len(low["elements"]) == 1  # 下限 1

    high = parse_snapshot_payload(_payload(elements, text="x" * 400), max_nodes=10 ** 6)
    assert len(high["elements"]) == 3
    assert high["truncated"] is False


def test_parse_canvas_hint_when_few_elements_and_short_text():
    content = parse_snapshot_payload(_payload([_element("e1")], text="hi"))
    assert "Canvas" in content["hint"]
    assert "browser_screenshot" in content["hint"]


def test_parse_no_canvas_hint_when_text_is_long_enough():
    content = parse_snapshot_payload(
        _payload([_element("e1")], text="x" * (SNAPSHOT_CANVAS_TEXT_HINT + 1))
    )
    assert "hint" not in content


def test_parse_text_mode_keeps_legacy_shape():
    content = parse_snapshot_payload(_payload([], text="body text"), mode="text")
    assert content == {
        "url": "https://example.test/",
        "title": "Example",
        "text": "body text",
        "truncated": False,
    }


def test_parse_full_mode_returns_elements_and_text():
    text = "x" * 400
    content = parse_snapshot_payload(_payload([_element("e1")], text=text), mode="full")
    assert content["mode"] == "full"
    assert content["elements"][0]["ref"] == "e1"
    assert content["text"] == text
    assert content["truncated_text"] is False


@pytest.mark.parametrize(
    "payload",
    ["not json", ["a", "list"], None, 42],
    ids=["bad-json", "list", "none", "int"],
)
def test_parse_invalid_payload_reports_error(payload: Any):
    assert parse_snapshot_payload(payload) == {"error": "页面快照返回异常（非 JSON）"}


def test_parse_missing_elements_in_interactive_mode_reports_error():
    payload = json.dumps({"url": "u", "title": "t", "text": "x" * 400})
    assert parse_snapshot_payload(payload) == {"error": "页面快照返回异常（非 JSON）"}


def test_parse_accepts_dict_payload_directly():
    content = parse_snapshot_payload(
        {
            "url": "u",
            "title": "t",
            "viewport": {"width": 1, "height": 1, "scroll_y": 0},
            "elements": [_element("e1")],
            "text": "x" * 400,
        }
    )
    assert content["elements"][0]["ref"] == "e1"
    assert content["elements_total"] == 1


# ---------------------------------------------------------------------------
# build_ref_expression
# ---------------------------------------------------------------------------


def test_build_ref_expression_wraps_stale_guards_and_escapes_ref():
    action = "(function(){return{ok:true,info:'x'};})()"
    expression = build_ref_expression(action, 'e"1')

    assert "window.__SAGE_REFS__" in expression
    assert "isConnected" in expression
    assert "stale-ref" in expression
    assert "data-sage-ref-name" in expression
    # ref 以 JSON 字符串字面量注入（引号被正确转义）
    assert json.dumps('e"1') in expression
    assert expression.rstrip().endswith("})()")
