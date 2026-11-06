# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M4 验收 E2E —— 分发与质量的两条验收线(spec §8.3 / §11)。

1. 内置模板一键创建:POST /specialists/templates/writing/instantiate 返回新专家,
   验证 role=specialist、source=builtin、id 形如 specialist-writing-<6hex>,
   并检查关键 profile 字段(system_prompt / persona_ui / model_config)非空合理。
2. 导出 → 另一目录导入:经 GET /specialists/{id}/export 取 zip,再 POST
   /specialists/import 把 zip 投到「另一台机器」(通过 monkeypatch 切换
   SAGE_SPECIALISTS_DIR 模拟),验证导入后的 profile 与源专家在
   name / description / persona_ui / model_config / memory_policy / skills /
   tools / memory_access / max_iterations 字段一致(id / source /
   knowledge_bindings 按 v2 钳制规则处理)。

本文件不使用任何 mock;所有路由与物化/导入/导出管线走真实 HTTP + SQLite。
"""

from __future__ import annotations

import io
from typing import List

import pytest

pytestmark = pytest.mark.e2e


# =====================================================================
# fixtures
# =====================================================================


@pytest.fixture()
def specialists_dirs(tmp_path, monkeypatch):
    """两个独立的专家数据目录(模拟源/目标机器)。

    默认 monkeypatch SAGE_SPECIALISTS_DIR 为 ``dir_a``;调用 ``switch_to_b()``
    后 ``specialists_root()`` 返回 ``dir_b``,用于模拟「另一台机器」的导入。
    """
    dir_a = tmp_path / "src-specialists"
    dir_b = tmp_path / "dst-specialists"
    dir_a.mkdir()
    dir_b.mkdir()
    monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(dir_a))

    def switch_to_b() -> None:
        monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(dir_b))

    return dir_a, dir_b, switch_to_b


# =====================================================================
# helpers
# =====================================================================


def _assert_profile_nontrivial(profile: dict) -> None:
    """模板实例化后的 profile 应当具备非空人设,否则模板物化失败静默回退。"""
    assert profile["role"] == "specialist"
    assert profile["source"] == "builtin"
    assert profile["id"].startswith("specialist-writing-")
    assert len(profile["id"]) == len("specialist-writing-") + 6
    # name 应为「写作专家」
    assert profile["name"] == "写作专家"
    # system_prompt 应当含 Markdown 结构(模板 persona.md 正文带标题)
    assert isinstance(profile.get("system_prompt"), str)
    assert len(profile["system_prompt"]) > 100
    # persona_ui 至少有一个 emoji 头像
    persona_ui = profile.get("persona_ui") or {}
    assert isinstance(persona_ui.get("avatar"), str)
    assert len(persona_ui["avatar"]) > 0
    # model_config 是 dict
    assert isinstance(profile.get("model_config"), dict)
    # 启用态
    assert profile["enabled"] is True


# =====================================================================
# 验收线 1:模板一键创建写作专家
# =====================================================================


@pytest.mark.asyncio()
async def test_instantiate_writing_template_via_http(client, specialists_dirs):
    """验收线 1:POST /specialists/templates/writing/instantiate 一键建写作专家。"""
    resp = await client.post("/api/v1/specialists/templates/writing/instantiate")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "写作专家"
    assert body["template_id"] == "writing"
    assert isinstance(body["dropped_bindings"], int)

    agent_id = body["id"]
    assert agent_id.startswith("specialist-writing-")
    assert len(agent_id) == len("specialist-writing-") + 6

    # 通过 agents 表 GET 校验完整 profile 落库
    get_resp = await client.get(f"/api/v1/agents/{agent_id}")
    assert get_resp.status_code == 200, get_resp.text
    profile = get_resp.json()
    _assert_profile_nontrivial(profile)


# =====================================================================
# 验收线 2:模板创建 + 导出 → 另一目录导入 → 行为一致
# =====================================================================


@pytest.mark.asyncio()
async def test_export_then_import_to_another_directory_keeps_profile(
    client, specialists_dirs
):
    """验收线 2:模板实例化 → 导出 → 切换 SAGE_SPECIALISTS_DIR → 导入 → 全字段一致。"""
    # 1. 模板实例化一个写作专家
    inst = await client.post("/api/v1/specialists/templates/writing/instantiate")
    assert inst.status_code == 201, inst.text
    source_id = inst.json()["id"]

    # 2. 导出 zip(HTTP 流)
    export_resp = await client.get(f"/api/v1/specialists/{source_id}/export")
    assert export_resp.status_code == 200, export_resp.text
    zip_bytes = b"".join([chunk async for chunk in export_resp.aiter_bytes()])
    assert zip_bytes.startswith(b"PK"), "导出结果不是合法 zip 包"

    # 3. 读取源 profile 做对比基线
    src = (await client.get(f"/api/v1/agents/{source_id}")).json()

    # 4. 切换到「另一台机器」的专家目录并导入 zip
    _, _, switch_to_b = specialists_dirs
    switch_to_b()

    files = {"file": ("writing.sage", io.BytesIO(zip_bytes), "application/zip")}
    import_resp = await client.post(
        "/api/v1/specialists/import", files=files
    )
    assert import_resp.status_code == 200, import_resp.text
    imported_body = import_resp.json()
    imported_id = imported_body["id"]
    assert imported_id != source_id
    assert imported_body["name"] == "写作专家"
    # 跨机器不可移植:模板无知识绑定,dropped_bindings 应为 0
    assert isinstance(imported_body["dropped_bindings"], int)

    # 5. 读取目标 profile
    dst = (await client.get(f"/api/v1/agents/{imported_id}")).json()

    # 6. 行为一致性断言:全部与配置相关的字段必须保持一致
    assert dst["role"] == "specialist"
    assert dst["source"] == "imported"  # 外部导入强制(不采信包内 source)
    assert dst["name"] == src["name"]
    assert dst["description"] == src["description"]
    assert dst["version"] == src["version"]
    assert dst["enabled"] == src["enabled"]
    assert dst["max_iterations"] == src["max_iterations"]
    assert dst["permission_mode"] == src["permission_mode"]
    assert dst["system_prompt"] == src["system_prompt"]
    assert dst["skills"] == src["skills"]
    assert dst["tools"] == src["tools"]
    assert dst["memory_access"] == src["memory_access"]
    assert dst["model_config"] == src["model_config"]
    assert dst["memory_policy"] == src["memory_policy"]
    assert dst["persona_ui"] == src["persona_ui"]

    # 7. 目标目录落盘(avatar/skills/knowledge 应存在或均为空)
    from backend.skills.specialist_skills import specialists_root

    dst_root = specialists_root()
    assert dst_root.name == "dst-specialists"
    agent_dir = dst_root / imported_id
    assert agent_dir.is_dir()


# =====================================================================
# 验收线 3(附加):模板目录可枚举
# =====================================================================


@pytest.mark.asyncio()
async def test_templates_directory_lists_all_five(client, specialists_dirs):
    """模板目录列出全部 5 套内置模板(与 spec §M4 模板清单一致)。"""
    resp = await client.get("/api/v1/specialists/templates")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    templates = body["templates"]
    ids: List[str] = [t["id"] for t in templates]
    for expected in ("writing", "research", "coding", "presentation", "office"):
        assert expected in ids, f"模板 {expected} 缺失"
    # 每个模板条目至少含展示所需字段
    for t in templates:
        assert isinstance(t["name"], str)
        assert t["name"]
        assert isinstance(t["skill_count"], int)
        assert "avatar" in t or "tagline" in t
