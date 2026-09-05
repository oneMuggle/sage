import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from backend.main import app
from backend.models.update import UpdateManifest, FileMeta


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def metadata_dir(tmp_path, monkeypatch):
    """Override metadata directory for tests."""
    test_dir = tmp_path / "test-metadata"
    test_dir.mkdir()

    # Monkeypatch the service instance in the updates module
    from backend.api.v1 import updates
    from backend.services.update_metadata import UpdateMetadataService

    test_service = UpdateMetadataService(str(test_dir))
    monkeypatch.setattr(updates, "_metadata_service", test_service)

    return test_dir


@pytest.fixture
def sample_manifest():
    """Create a sample manifest."""
    return UpdateManifest(
        version="1.2.3",
        channel="stable",
        release_date=datetime(2026, 9, 5, 12, 0, 0),
        release_notes="## What's New\n- Feature A",
        min_upgradable_version="1.0.0",
        files={
            "win-x64": FileMeta(
                filename="Sage-Setup-1.2.3.exe",
                url="https://updates.sage.app/releases/1.2.3/latest.yml",
                sha512="a" * 128,
                size=104857600,
                signature="sig-placeholder",
            )
        },
        components={},
    )


def test_get_latest_not_found(client, metadata_dir):
    """Test GET /latest returns 404 when no manifests exist."""
    response = client.get("/api/v1/updates/latest?channel=stable")
    assert response.status_code == 404
    assert "No manifests found" in response.json()["detail"]


def test_get_latest_success(client, metadata_dir, sample_manifest):
    """Test GET /latest returns manifest when it exists."""
    # Write manifest
    channel_dir = metadata_dir / "stable"
    channel_dir.mkdir(parents=True)
    with open(channel_dir / "1.2.3.json", "w") as f:
        f.write(sample_manifest.model_dump_json())

    response = client.get("/api/v1/updates/latest?channel=stable")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "1.2.3"
    assert data["channel"] == "stable"


def test_get_history_empty(client, metadata_dir):
    """Test GET /history returns empty list when no manifests."""
    response = client.get("/api/v1/updates/history?channel=stable&limit=10")
    assert response.status_code == 200
    assert response.json() == []


def test_get_history_with_limit(client, metadata_dir, sample_manifest):
    """Test GET /history respects limit parameter."""
    channel_dir = metadata_dir / "stable"
    channel_dir.mkdir(parents=True)

    # Write 5 manifests
    for i in range(5):
        manifest = sample_manifest.model_copy(update={"version": f"1.{i}.0"})
        with open(channel_dir / f"1.{i}.0.json", "w") as f:
            f.write(manifest.model_dump_json())

    response = client.get("/api/v1/updates/history?channel=stable&limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_get_channels(client):
    """Test GET /channels returns available channels."""
    response = client.get("/api/v1/updates/channels")
    assert response.status_code == 200
    channels = response.json()
    assert "stable" in channels
    assert "beta" in channels
    assert "alpha" in channels


def test_invalid_channel_rejected(client):
    """Test that invalid channels are rejected with 400 Bad Request."""
    for invalid_channel in ["nightly", "dev", "../etc", "stable/beta", ""]:
        response = client.get(f"/api/v1/updates/latest?channel={invalid_channel}")
        assert response.status_code == 400
        assert "Invalid update channel" in response.json()["detail"]

        response = client.get(f"/api/v1/updates/history?channel={invalid_channel}")
        assert response.status_code == 400
        assert "Invalid update channel" in response.json()["detail"]


def test_valid_channels_accepted(client):
    """Test that all valid channels are accepted."""
    for valid_channel in ["stable", "beta", "alpha"]:
        response = client.get(f"/api/v1/updates/latest?channel={valid_channel}")
        assert response.status_code == 404  # No manifests, but no validation error
