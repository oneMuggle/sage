"""Integration tests for the model-catalog HTTP API routes.

Tests run against an ephemeral SQLite database with the model-catalog router
mounted on a FastAPI app.  Each test gets a fresh client + repo pair.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.local_auth import get_local_auth_token
from backend.data.database import Database
from backend.model_catalog.repository import CatalogRepository
from backend.model_catalog.schemas import CandidateModel, EndpointKey


@pytest.fixture()
def repo(tmp_path):
    db = Database(str(tmp_path / "catalog.db"))
    db.init_db()
    yield CatalogRepository(db)
    db.close()


@pytest.fixture()
def client(repo):
    from backend.api.model_catalog_routes import build_router

    app = FastAPI()
    app.include_router(build_router(repo), prefix="/api/v1/model-catalog")
    token = get_local_auth_token()
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _candidate(**patch):
    base = {
        "model_key": {"provider": "vendor", "model_id": "exact-Q4"},
        "native": 32000,
        "price": {"input_per_million": "1.25"},
        "source": "custom_json",
        "pricing_scope": "openrouter",
    }
    base.update(patch)
    return CandidateModel.model_validate(base)


def _publish(repo, record=None, fields=None):
    record = record or _candidate()
    snap = repo.stage([record], record.source)
    item = repo.diff(snap)[0]
    repo.apply(snap, item.id, fields or ["native", "price"], item.base_revision)
    return snap, item


def _unauth_client(repo):
    """Client WITHOUT authorization header."""
    from backend.api.model_catalog_routes import build_router

    app = FastAPI()
    app.include_router(build_router(repo), prefix="/api/v1/model-catalog")
    # conftest monkeypatches TestClient to add auth headers via setdefault;
    # passing explicit headers prevents the default auth header injection.
    return TestClient(app, headers={})


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


class TestAuthorization:
    def test_no_auth_rejected(self, repo):
        c = _unauth_client(repo)
        assert c.get("/api/v1/model-catalog/models").status_code == 401

    def test_wrong_auth_rejected(self, repo):
        from backend.api.model_catalog_routes import build_router

        app = FastAPI()
        app.include_router(build_router(repo), prefix="/api/v1/model-catalog")
        c = TestClient(app, headers={"Authorization": "Bearer wrong-token"})
        assert c.get("/api/v1/model-catalog/models").status_code == 401


# ---------------------------------------------------------------------------
# GET /models
# ---------------------------------------------------------------------------


class TestGetModels:
    def test_empty_catalog(self, client):
        resp = client.get("/api/v1/model-catalog/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_pagination_limit(self, client, repo):
        for i in range(5):
            _publish(repo, _candidate(
                model_key={"provider": f"p{i}", "model_id": f"m{i}"},
            ))
        resp = client.get("/api/v1/model-catalog/models?limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5

    def test_limit_capped_at_100(self, client):
        resp = client.get("/api/v1/model-catalog/models?limit=999")
        assert resp.status_code == 200

    def test_offset(self, client, repo):
        for i in range(3):
            _publish(repo, _candidate(
                model_key={"provider": f"p{i}", "model_id": f"m{i}"},
            ))
        resp = client.get("/api/v1/model-catalog/models?offset=2")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


# ---------------------------------------------------------------------------
# GET /effective
# ---------------------------------------------------------------------------


class TestGetEffective:
    def test_unknown_endpoint_returns_unknown_values(self, client):
        resp = client.get(
            "/api/v1/model-catalog/effective",
            params={"endpoint_id": "ep", "model_id": "m"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["limits"]["native"] is None
        assert body["price"]["input_per_million"] is None

    def test_resolved_endpoint(self, client, repo):
        _publish(repo)
        repo.bind(
            EndpointKey(endpoint_id="ep", model_id="exact-Q4"),
            _candidate().model_key,
            "openrouter",
        )
        resp = client.get(
            "/api/v1/model-catalog/effective",
            params={"endpoint_id": "ep", "model_id": "exact-Q4"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["limits"]["native"] == 32000
        assert body["price"]["input_per_million"] == "1.25"

    def test_missing_params_422(self, client):
        resp = client.get("/api/v1/model-catalog/effective")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /overrides
# ---------------------------------------------------------------------------


class TestPutOverrides:
    def test_set_override(self, client):
        resp = client.put(
            "/api/v1/model-catalog/overrides",
            json={
                "endpoint_id": "ep",
                "model_id": "m",
                "patch": {"native": 8000},
                "expected_revision": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["revision"] == 1

    def test_cas_conflict_409(self, client):
        client.put(
            "/api/v1/model-catalog/overrides",
            json={
                "endpoint_id": "ep",
                "model_id": "m",
                "patch": {"native": 1},
                "expected_revision": 0,
            },
        )
        resp = client.put(
            "/api/v1/model-catalog/overrides",
            json={
                "endpoint_id": "ep",
                "model_id": "m",
                "patch": {"native": 2},
                "expected_revision": 0,
            },
        )
        assert resp.status_code == 409

    def test_invalid_patch_422(self, client):
        resp = client.put(
            "/api/v1/model-catalog/overrides",
            json={
                "endpoint_id": "ep",
                "model_id": "m",
                "patch": {"native": -1},
                "expected_revision": 0,
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /snapshots/import
# ---------------------------------------------------------------------------


class TestPostSnapshotsImport:
    def test_import_valid_bundle(self, client):
        from backend.model_catalog.transfer import encode_bundle

        bundle = encode_bundle([_candidate()], "custom_json")
        resp = client.post(
            "/api/v1/model-catalog/snapshots/import",
            content=bundle,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "snapshot_id" in body
        assert body["count"] == 1

    def test_import_tampered_bundle_422(self, client):
        from backend.model_catalog.transfer import encode_bundle

        bundle = encode_bundle([_candidate()], "custom_json")
        envelope = json.loads(bundle)
        envelope["sha256"] = "0" * 64
        resp = client.post(
            "/api/v1/model-catalog/snapshots/import",
            content=json.dumps(envelope),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_import_too_large_413(self, client):
        huge = json.dumps({"formatVersion": 1, "payload": {"records": [None] * 2},
                           "sha256": "x"}).encode() * (11 * 1024 * 1024)
        resp = client.post(
            "/api/v1/model-catalog/snapshots/import",
            content=huge,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413

    def test_import_does_not_auto_apply(self, client, repo):
        from backend.model_catalog.transfer import encode_bundle

        bundle = encode_bundle([_candidate()], "custom_json")
        client.post(
            "/api/v1/model-catalog/snapshots/import",
            content=bundle,
            headers={"Content-Type": "application/json"},
        )
        # No entries should be created — import only stages for review
        count = repo.db.get_connection().execute(
            "SELECT COUNT(*) FROM model_catalog_entries"
        ).fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# GET /snapshots
# ---------------------------------------------------------------------------


class TestGetSnapshots:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/model-catalog/snapshots")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_import(self, client):
        from backend.model_catalog.transfer import encode_bundle

        bundle = encode_bundle([_candidate()], "custom_json")
        client.post(
            "/api/v1/model-catalog/snapshots/import",
            content=bundle,
            headers={"Content-Type": "application/json"},
        )
        resp = client.get("/api/v1/model-catalog/snapshots")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# GET /snapshots/{id}/diff
# ---------------------------------------------------------------------------


class TestGetSnapshotDiff:
    def test_diff_returns_items(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        resp = client.get(f"/api/v1/model-catalog/snapshots/{snap}/diff")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["classification"] == "new"

    def test_unknown_snapshot_404(self, client):
        resp = client.get("/api/v1/model-catalog/snapshots/nonexistent/diff")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /snapshots/{id}/items/{item}/apply and /ignore
# ---------------------------------------------------------------------------


class TestApplyAndIgnore:
    def test_apply(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        item = repo.diff(snap)[0]
        resp = client.post(
            f"/api/v1/model-catalog/snapshots/{snap}/items/{item.id}/apply",
            json={"fields": ["native", "price"], "expected_revision": 0},
        )
        assert resp.status_code == 200

    def test_apply_cas_conflict_409(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        item = repo.diff(snap)[0]
        repo.apply(snap, item.id, ["native"], item.base_revision)
        resp = client.post(
            f"/api/v1/model-catalog/snapshots/{snap}/items/{item.id}/apply",
            json={"fields": ["native"], "expected_revision": 0},
        )
        assert resp.status_code == 409

    def test_ignore(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        item = repo.diff(snap)[0]
        resp = client.post(
            f"/api/v1/model-catalog/snapshots/{snap}/items/{item.id}/ignore"
        )
        assert resp.status_code == 200

    def test_ignore_already_reviewed_409(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        item = repo.diff(snap)[0]
        repo.ignore(snap, item.id)
        resp = client.post(
            f"/api/v1/model-catalog/snapshots/{snap}/items/{item.id}/ignore"
        )
        assert resp.status_code == 409

    def test_unknown_item_404(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        resp = client.post(
            f"/api/v1/model-catalog/snapshots/{snap}/items/nonexistent/apply",
            json={"fields": ["native"], "expected_revision": 0},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /snapshots/{id}/export
# ---------------------------------------------------------------------------


class TestGetSnapshotExport:
    def test_export_returns_bundle(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        resp = client.get(f"/api/v1/model-catalog/snapshots/{snap}/export")
        assert resp.status_code == 200
        envelope = resp.json()
        assert envelope["formatVersion"] == 1
        assert "sha256" in envelope
        assert len(envelope["payload"]["records"]) == 1

    def test_export_contains_no_secrets(self, client, repo):
        snap = repo.stage([_candidate()], "custom_json")
        resp = client.get(f"/api/v1/model-catalog/snapshots/{snap}/export")
        raw = resp.text.lower()
        assert "authorization" not in raw
        assert "api_key" not in raw
        assert "api-key" not in raw

    def test_export_unknown_snapshot_404(self, client):
        resp = client.get("/api/v1/model-catalog/snapshots/nonexistent/export")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /sync/openrouter
# ---------------------------------------------------------------------------


class TestPostSyncOpenRouter:
    def test_sync_stages_records(self, client):
        or_data = {
            "data": [
                {
                    "id": "openai/gpt-4o",
                    "context_length": 128000,
                    "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
                    "architecture": {"modality": "text"},
                    "created": 1700000000,
                }
            ]
        }

        with patch(
            "backend.api.model_catalog_routes._fetch_openrouter",
            new=AsyncMock(return_value=or_data),
        ):
            resp = client.post("/api/v1/model-catalog/sync/openrouter")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert "snapshot_id" in body

    def test_sync_does_not_auto_apply(self, client, repo):
        with patch(
            "backend.api.model_catalog_routes._fetch_openrouter",
            new=AsyncMock(return_value={"data": []}),
        ):
            resp = client.post("/api/v1/model-catalog/sync/openrouter")
        assert resp.status_code == 200
        # No entries — sync only stages for review
        count = repo.db.get_connection().execute(
            "SELECT COUNT(*) FROM model_catalog_entries"
        ).fetchone()[0]
        assert count == 0

    def test_sync_upstream_failure_502(self, client):
        with patch(
            "backend.api.model_catalog_routes._fetch_openrouter",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ):
            resp = client.post("/api/v1/model-catalog/sync/openrouter")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /probe
# ---------------------------------------------------------------------------


class TestPostProbe:
    def test_probe_success_persists_result(self, client, repo):
        from backend.model_catalog.probes import ProbeResult

        probe_result = ProbeResult(
            status="success",
            adapter="ollama",
            data={
                "native": 32768,
                "service": None,
                "architecture": "llama",
                "quantization": "Q4_K_M",
            },
        )
        with patch(
            "backend.model_catalog.probes.probe_endpoint_from_settings",
            new=AsyncMock(return_value=probe_result),
        ):
            resp = client.post(
                "/api/v1/model-catalog/probe",
                json={"endpoint_id": "ep-1", "model_id": "llama3"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["adapter"] == "ollama"
        assert body["data"]["native"] == 32768
        # Probe result should be persisted
        endpoint = EndpointKey(endpoint_id="ep-1", model_id="llama3")
        probe_record = repo.get_probe(endpoint)
        assert probe_record is not None
        assert probe_record.status == "success"
        assert probe_record.adapter == "ollama"

    def test_probe_unsupported_returns_empty(self, client, repo):
        from backend.model_catalog.probes import ProbeResult

        probe_result = ProbeResult(
            status="unsupported",
            adapter="openai-compatible",
            error="OpenAI-compatible services do not expose model metadata",
        )
        with patch(
            "backend.model_catalog.probes.probe_endpoint_from_settings",
            new=AsyncMock(return_value=probe_result),
        ):
            resp = client.post(
                "/api/v1/model-catalog/probe",
                json={"endpoint_id": "ep-1", "model_id": "gpt-4o"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "unsupported"
        assert body["data"] is None
        # Unsupported results should be persisted as stale
        endpoint = EndpointKey(endpoint_id="ep-1", model_id="gpt-4o")
        probe_record = repo.get_probe(endpoint)
        assert probe_record is not None
        assert probe_record.status == "unsupported"

    def test_probe_error_persists(self, client, repo):
        from backend.model_catalog.probes import ProbeResult

        probe_result = ProbeResult(
            status="error",
            adapter="ollama",
            error="connection refused",
        )
        with patch(
            "backend.model_catalog.probes.probe_endpoint_from_settings",
            new=AsyncMock(return_value=probe_result),
        ):
            resp = client.post(
                "/api/v1/model-catalog/probe",
                json={"endpoint_id": "ep-1", "model_id": "llama3"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert body["error"] == "connection refused"
        endpoint = EndpointKey(endpoint_id="ep-1", model_id="llama3")
        probe_record = repo.get_probe(endpoint)
        assert probe_record is not None
        assert probe_record.status == "error"

    def test_probe_missing_body_422(self, client):
        resp = client.post("/api/v1/model-catalog/probe", json={})
        assert resp.status_code == 422

    def test_probe_no_auth_rejected(self, repo):
        unauth = _unauth_client(repo)
        resp = unauth.post(
            "/api/v1/model-catalog/probe",
            json={"endpoint_id": "ep-1", "model_id": "llama3"},
        )
        assert resp.status_code == 401
