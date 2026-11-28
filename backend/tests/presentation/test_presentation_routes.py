"""Presentation 路由测试 —— 通过 FastAPI TestClient 打真实挂载的路由。

认证由 conftest 的 autouse fixture 注入 X-Sage-Local-Authorization 请求头；
这里只 monkeypatch 模块级 `_service`，避免真的触发子进程。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import presentation_routes as routes
from backend.main import app
from backend.services.ppt_master_adapter import PptMasterEnvError
from backend.services.presentation_service import PresentationInputError, RenderResult
from backend.services.presentation_template_registry import TemplateEntry

_PREFIX = "/api/v1/presentation"


def _template(kind: str, template_id: str) -> TemplateEntry:
    return TemplateEntry(
        kind=kind,
        template_id=template_id,
        name=template_id,
        summary=f"{template_id} 摘要",
        primary_color="#123456",
        canvas_format="16:9",
        page_count=None,
        page_types=("cover",),
        root_path=f"/fake/templates/{kind}s/{template_id}",
    )


class FakeService:
    def __init__(
        self,
        result: RenderResult | None = None,
        render_error: Exception | None = None,
        env_error: Exception | None = None,
    ) -> None:
        self._result = result or RenderResult(success=True, quality_passed=True)
        self._render_error = render_error
        self._env_error = env_error
        self.render_svgs_calls: list[tuple[list[str], Path, list[Path]]] = []
        self.render_project_calls: list[tuple[Path, Path, list[Path]]] = []

    def check_environment(self) -> dict:
        if self._env_error is not None:
            raise self._env_error
        return {"skill_root": "/fake/skill", "python": "/fake/python"}

    def render_from_svgs(self, svg_slides, output_path: Path, template_roots=()) -> RenderResult:
        if self._render_error is not None:
            raise self._render_error
        self.render_svgs_calls.append(
            (list(svg_slides), Path(output_path), [Path(r) for r in template_roots])
        )
        return self._result

    def render_project(
        self, project_dir: Path, output_path: Path, template_roots=()
    ) -> RenderResult:
        if self._render_error is not None:
            raise self._render_error
        self.render_project_calls.append(
            (Path(project_dir), Path(output_path), [Path(r) for r in template_roots])
        )
        return self._result


class FakeRegistry:
    def __init__(
        self,
        entries: list[TemplateEntry] | None = None,
        list_error: Exception | None = None,
        refresh_error: Exception | None = None,
        refresh_count: int = 0,
        resolve_error: Exception | None = None,
        resolve_result: list[Path] | None = None,
    ) -> None:
        self._entries = entries or []
        self._list_error = list_error
        self._refresh_error = refresh_error
        self._refresh_count = refresh_count
        self._resolve_error = resolve_error
        self._resolve_result = resolve_result or []
        self.ensure_fresh_calls = 0
        self.list_calls: list[str | None] = []
        self.refresh_calls = 0
        self.resolve_calls: list[list[str]] = []

    def ensure_fresh(self) -> None:
        self.ensure_fresh_calls += 1

    def list_templates(self, kind=None) -> list[TemplateEntry]:
        self.list_calls.append(kind)
        if self._list_error is not None:
            raise self._list_error
        return [e for e in self._entries if kind is None or e.kind == kind]

    def refresh(self) -> int:
        self.refresh_calls += 1
        if self._refresh_error is not None:
            raise self._refresh_error
        return self._refresh_count

    def resolve_roots(self, template_ids):
        self.resolve_calls.append(list(template_ids))
        if self._resolve_error is not None:
            raise self._resolve_error
        return list(self._resolve_result)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    def _install(service: FakeService, registry: FakeRegistry | None = None) -> TestClient:
        monkeypatch.setattr(routes, "_service", service)
        monkeypatch.setattr(routes, "_registry", registry or FakeRegistry())
        return TestClient(app)

    return _install


# --------------------------------------------------------------------------- #
# /environment
# --------------------------------------------------------------------------- #
def test_environment_ready(client):
    resp = client(FakeService()).get(f"{_PREFIX}/environment")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["skill_root"] == "/fake/skill"


def test_environment_not_ready(client):
    resp = client(FakeService(env_error=PptMasterEnvError("no skill"))).get(
        f"{_PREFIX}/environment"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    assert "no skill" in body["error"]


# --------------------------------------------------------------------------- #
# /render-svgs
# --------------------------------------------------------------------------- #
def test_render_svgs_success(client, tmp_path: Path):
    out = tmp_path / "deck.pptx"
    service = FakeService(
        result=RenderResult(
            success=True,
            output_path=out,
            quality_passed=True,
            summary={"total": 1},
            message="生成成功",
        )
    )
    resp = client(service).post(
        f"{_PREFIX}/render-svgs",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "svg_slides": ["<svg>1</svg>", "<svg>2</svg>"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["output_path"] == str(out)
    assert service.render_svgs_calls[0][0] == ["<svg>1</svg>", "<svg>2</svg>"]


def test_render_svgs_quality_failure_is_200(client, tmp_path: Path):
    service = FakeService(
        result=RenderResult(
            success=False,
            quality_passed=False,
            blocking_errors=[{"code": "E1"}],
            message="质量门禁未通过",
        )
    )
    resp = client(service).post(
        f"{_PREFIX}/render-svgs",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "svg_slides": ["<svg/>"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["blocking_errors"] == [{"code": "E1"}]


def test_render_svgs_bad_workspace_is_400(client, tmp_path: Path):
    resp = client(FakeService()).post(
        f"{_PREFIX}/render-svgs",
        json={
            "workspace_path": str(tmp_path / "missing"),
            "filename": "deck.pptx",
            "svg_slides": ["<svg/>"],
        },
    )
    assert resp.status_code == 400


def test_render_svgs_empty_slides_is_422(client, tmp_path: Path):
    resp = client(FakeService()).post(
        f"{_PREFIX}/render-svgs",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "svg_slides": [],
        },
    )
    assert resp.status_code == 422


def test_render_svgs_input_error_is_400(client, tmp_path: Path):
    service = FakeService(render_error=PresentationInputError("bad svg"))
    resp = client(service).post(
        f"{_PREFIX}/render-svgs",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "svg_slides": ["<svg/>"],
        },
    )
    assert resp.status_code == 400
    assert "bad svg" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# /render-project
# --------------------------------------------------------------------------- #
def test_render_project_success(client, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    service = FakeService(result=RenderResult(success=True, quality_passed=True))
    resp = client(service).post(
        f"{_PREFIX}/render-project",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "project_path": str(project),
        },
    )
    assert resp.status_code == 200
    assert service.render_project_calls[0][0] == project


def test_render_project_outside_workspace_is_400(client, tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    resp = client(FakeService()).post(
        f"{_PREFIX}/render-project",
        json={
            "workspace_path": str(workspace),
            "filename": "deck.pptx",
            "project_path": str(outside),
        },
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# 模板：选择 -> 解析根路径 -> 传给 service
# --------------------------------------------------------------------------- #
def test_render_svgs_passes_resolved_template_roots(client, tmp_path: Path):
    root = tmp_path / "brands" / "acme"
    root.mkdir(parents=True)
    registry = FakeRegistry(resolve_result=[root])
    service = FakeService(
        result=RenderResult(success=True, quality_passed=True, templates_applied=["acme"])
    )
    resp = client(service, registry).post(
        f"{_PREFIX}/render-svgs",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "svg_slides": ["<svg/>"],
            "template_ids": ["brand:acme"],
        },
    )
    assert resp.status_code == 200
    assert registry.resolve_calls == [["brand:acme"]]
    assert service.render_svgs_calls[0][2] == [root]
    assert resp.json()["templates_applied"] == ["acme"]


def test_render_svgs_unknown_template_is_400(client, tmp_path: Path):
    registry = FakeRegistry(resolve_error=PresentationInputError("未知模板：brand:nope"))
    resp = client(FakeService(), registry).post(
        f"{_PREFIX}/render-svgs",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "svg_slides": ["<svg/>"],
            "template_ids": ["brand:nope"],
        },
    )
    assert resp.status_code == 400
    assert "未知模板" in resp.json()["detail"]


def test_render_project_passes_resolved_template_roots(client, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    root = tmp_path / "layouts" / "brief"
    root.mkdir(parents=True)
    registry = FakeRegistry(resolve_result=[root])
    service = FakeService()
    resp = client(service, registry).post(
        f"{_PREFIX}/render-project",
        json={
            "workspace_path": str(tmp_path),
            "filename": "deck.pptx",
            "project_path": str(project),
            "template_ids": ["layout:brief"],
        },
    )
    assert resp.status_code == 200
    assert service.render_project_calls[0][2] == [root]


# --------------------------------------------------------------------------- #
# /templates 与 /templates/refresh
# --------------------------------------------------------------------------- #
def test_list_templates_available(client):
    registry = FakeRegistry(entries=[_template("brand", "acme"), _template("style", "clean")])
    resp = client(FakeService(), registry).get(f"{_PREFIX}/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert [t["template_id"] for t in body["templates"]] == ["acme", "clean"]
    assert body["templates"][0]["page_types"] == ["cover"]
    assert registry.ensure_fresh_calls == 1
    assert registry.list_calls == [None]


def test_list_templates_filters_by_kind(client):
    registry = FakeRegistry(entries=[_template("brand", "acme"), _template("style", "clean")])
    resp = client(FakeService(), registry).get(f"{_PREFIX}/templates?kind=style")
    assert resp.status_code == 200
    assert [t["template_id"] for t in resp.json()["templates"]] == ["clean"]
    assert registry.list_calls == ["style"]


def test_list_templates_env_missing_is_200_unavailable(client):
    registry = FakeRegistry(list_error=PptMasterEnvError("no skill"))
    resp = client(FakeService(), registry).get(f"{_PREFIX}/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "no skill" in body["error"]


def test_list_templates_bad_kind_is_400(client):
    registry = FakeRegistry(list_error=PresentationInputError("未知模板种类：foo"))
    resp = client(FakeService(), registry).get(f"{_PREFIX}/templates?kind=foo")
    assert resp.status_code == 400
    assert "未知模板种类" in resp.json()["detail"]


def test_refresh_templates_returns_count(client):
    registry = FakeRegistry(refresh_count=7)
    resp = client(FakeService(), registry).post(f"{_PREFIX}/templates/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"available": True, "count": 7, "error": None}
    assert registry.refresh_calls == 1


def test_refresh_templates_env_missing_is_200_unavailable(client):
    registry = FakeRegistry(refresh_error=PptMasterEnvError("no skill"))
    resp = client(FakeService(), registry).post(f"{_PREFIX}/templates/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["count"] == 0
