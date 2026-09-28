"""R71 — prompt 模板库路由单元测试。

直接调用路由函数（同步）。SettingsRepository 打桩为内存 KV。覆盖：
list/create（含 100 条上限 400）/update（命中与 404）/delete（命中与
404）/reorder（重排 + 缺失 id 尾部追加 + 多余 id 忽略）/export 信封/
import（版本守卫、新增、同名 skip 冲突清单、overwrite 保 id、非法条目
跳过、长度超限 failed、总量上限）、KV 不可达按空库降级、载荷校验。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.api import prompt_routes as pr

pytestmark = pytest.mark.unit


class _FakeKV:
    """SettingsRepository 替身：内存 KV，可注入读取失败。"""

    store: dict = {}
    fail_read: bool = False

    def get_json(self, key):
        if _FakeKV.fail_read:
            raise RuntimeError("kv down")
        return _FakeKV.store.get(key)

    def set_json(self, key, value):
        _FakeKV.store[key] = value


@pytest.fixture()
def kv(monkeypatch):
    _FakeKV.store = {}
    _FakeKV.fail_read = False
    monkeypatch.setattr(pr, "SettingsRepository", _FakeKV)
    return _FakeKV


def _tpl_in(name="T1", content="hello", description=""):
    return pr.PromptTemplateIn(name=name, content=content, description=description)


def _seed(kv, templates):
    kv.store["prompt_templates"] = templates


# ---------------------------------------------------------------------------
# list / create / delete / update
# ---------------------------------------------------------------------------


def test_list_empty(kv):
    assert pr.list_templates() == {"templates": []}


def test_create_and_list(kv):
    out = pr.create_template(_tpl_in(name="  T1  ", description=" d "))
    tpl = out["template"]
    assert tpl["name"] == "T1"  # strip
    assert tpl["description"] == "d"
    assert tpl["id"].startswith("pt-")
    assert tpl["created_at"] == tpl["updated_at"]
    assert len(pr.list_templates()["templates"]) == 1


def test_create_at_cap_400(kv):
    _seed(kv, [{"id": f"pt-{i}", "name": f"N{i}"} for i in range(100)])
    resp = pr.create_template(_tpl_in())
    assert resp.status_code == 400
    assert "100" in json.loads(resp.body)["error"]


def test_update_hit(kv):
    _seed(kv, [{"id": "pt-1", "name": "old", "content": "c0",
                "description": "", "updated_at": 0}])
    out = pr.update_template("pt-1", pr.PromptTemplateUpdate(name="new", content="c1"))
    assert out["template"]["name"] == "new"
    assert out["template"]["content"] == "c1"
    assert kv.store["prompt_templates"][0]["updated_at"] > 0


def test_update_miss_404(kv):
    resp = pr.update_template("ghost", pr.PromptTemplateUpdate(content="x"))
    assert resp.status_code == 404
    assert "ghost" in json.loads(resp.body)["error"]


def test_delete_hit_and_miss(kv):
    _seed(kv, [{"id": "pt-1", "name": "N"}])
    assert pr.delete_template("pt-1") == {"ok": True}
    assert kv.store["prompt_templates"] == []
    resp = pr.delete_template("pt-1")
    assert resp.status_code == 404


def test_list_sorts_by_updated_at_desc(kv):
    # win7 行为基线：list 按更新时间新→旧（main 侧为存储序 + reorder
    # 端点，见 R42；win7 前端无拖拽排序 UI，行为保持 updated_at 排序）
    _seed(kv, [
        {"id": "old", "name": "A", "updated_at": 100},
        {"id": "new", "name": "B", "updated_at": 200},
    ])
    out = pr.list_templates()["templates"]
    assert [t["id"] for t in out] == ["new", "old"]


def test_export_envelope(kv):
    _seed(kv, [{"id": "pt-1", "name": "N"}])
    out = pr.export_templates()
    assert out["app"] == "sage"
    assert out["kind"] == "prompt_templates"
    assert out["version"] == 1
    assert out["templates"][0]["id"] == "pt-1"
    assert "exported_at" in out


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def test_import_bad_version_400(kv):
    body = pr.ImportEnvelope(version=2, templates=[])
    resp = pr.import_templates(body)
    assert resp.status_code == 400


def test_import_new_names(kv):
    body = pr.ImportEnvelope(templates=[
        {"name": "A", "content": "ca"},
        {"name": "B", "content": "cb", "description": "d"},
    ])
    out = pr.import_templates(body)
    assert out["imported"] == 2
    assert out["skipped"] == 0
    assert kv.store["prompt_templates"][0]["name"] == "A"


def test_import_conflict_skip_lists_names(kv):
    _seed(kv, [{"id": "pt-1", "name": "A", "content": "old"}])
    body = pr.ImportEnvelope(templates=[{"name": "A", "content": "new"}])
    out = pr.import_templates(body)
    assert out["conflicts"] == ["A"]
    assert out["skipped"] == 1
    assert kv.store["prompt_templates"][0]["content"] == "old"  # 保留现有


def test_import_conflict_overwrite_keeps_id(kv):
    _seed(kv, [{"id": "pt-keep", "name": "A", "content": "old"}])
    body = pr.ImportEnvelope(
        templates=[{"name": "A", "content": "new", "description": "d"}],
        conflict="overwrite",
    )
    out = pr.import_templates(body)
    assert out["imported"] == 1
    tpl = kv.store["prompt_templates"][0]
    assert tpl["id"] == "pt-keep"  # 保 id：斜杠映射不断链
    assert tpl["content"] == "new"


def test_import_invalid_entries_counted(kv):
    body = pr.ImportEnvelope(templates=[
        "not-a-dict",
        {"name": "", "content": "x"},  # 空名
        {"name": "ok", "content": "   "},  # 空内容
        {"name": "ok2", "content": "c"},
    ])
    out = pr.import_templates(body)
    assert out["imported"] == 1
    assert out["skipped"] == 2
    assert out["failed"] == 1  # 非 dict 条目计入 failed


def test_import_length_overflow_failed_with_error(kv):
    body = pr.ImportEnvelope(templates=[
        {"name": "x" * 61, "content": "c"},
        {"name": "ok", "content": "c"},
    ])
    out = pr.import_templates(body)
    assert out["failed"] == 1
    assert len(out["errors"]) == 1
    assert out["imported"] == 1


def test_import_cap_skips_beyond_100(kv):
    _seed(kv, [{"id": f"pt-{i}", "name": f"N{i}"} for i in range(100)])
    body = pr.ImportEnvelope(templates=[{"name": f"X{i}", "content": "c"} for i in range(3)])
    out = pr.import_templates(body)
    assert out["imported"] == 0
    assert out["skipped"] == 3
    assert len(kv.store["prompt_templates"]) == 100


# ---------------------------------------------------------------------------
# 降级与载荷校验
# ---------------------------------------------------------------------------


def test_load_kv_down_degrades_to_empty(kv, monkeypatch):
    _FakeKV.fail_read = True
    assert pr.list_templates() == {"templates": []}


def test_payload_validation_bounds():
    with pytest.raises(ValidationError):
        pr.PromptTemplateIn(name="", content="c")
    with pytest.raises(ValidationError):
        pr.PromptTemplateIn(name="x" * 61, content="c")
    with pytest.raises(ValidationError):
        pr.PromptTemplateIn(name="n", content="x" * 8001)
    with pytest.raises(ValidationError):
        pr.PromptTemplateIn(name="n", content="c", description="d" * 301)
    ok = pr.PromptTemplateIn(name="n", content="c")
    assert ok.description == ""
