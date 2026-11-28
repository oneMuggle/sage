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

_PREFIX = "/api/v1/presentation"


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
        self.render_svgs_calls: list[tuple[list[str], Path]] = []
        self.render_project_calls: list[tuple[Path, Path]] = []

    def check_environment(self) -> dict:
        if self._env_error is not None:
            raise self._env_error
        return {"skill_root": "/fake/skill", "python": "/fake/python"}

    def render_from_svgs(self, svg_slides, output_path: Path) -> RenderResult:
        if self._render_error is not None:
            raise self._render_error
        self.render_svgs_calls.append((list(svg_slides), Path(output_path)))
        return self._result

    def render_project(self, project_dir: Path, output_path: Path) -> RenderResult:
        if self._render_error is not None:
            raise self._render_error
        self.render_project_calls.append((Path(project_dir), Path(output_path)))
        return self._result


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    def _install(service: FakeService) -> TestClient:
        monkeypatch.setattr(routes, "_service", service)
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
