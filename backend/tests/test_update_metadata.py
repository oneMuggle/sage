import json
import pytest
from datetime import datetime
from pathlib import Path
from backend.services.update_metadata import UpdateMetadataService
from backend.models.update import UpdateManifest, FileMeta


@pytest.fixture
def metadata_dir(tmp_path):
    """Create temporary metadata directory."""
    return tmp_path / "metadata"


@pytest.fixture
def sample_manifest():
    """Create a sample manifest for testing."""
    return UpdateManifest(
        version="1.2.3",
        channel="stable",
        release_date=datetime(2026, 9, 5, 12, 0, 0),
        release_notes="## What's New\n- Feature A\n- Bug fix B",
        min_upgradable_version="1.0.0",
        files={
            "win-x64": FileMeta(
                filename="Sage-Setup-1.2.3.exe",
                url="https://updates.sage.app/releases/1.2.3/latest.yml",
                sha512="a" * 128,
                size=104857600,
                signature="sig-placeholder"
            )
        },
        components={}
    )


def test_get_latest_empty(metadata_dir):
    """Test get_latest returns None when no manifests exist."""
    service = UpdateMetadataService(str(metadata_dir))
    result = service.get_latest("stable")
    assert result is None


def test_get_latest_single_manifest(metadata_dir, sample_manifest):
    """Test get_latest returns the only manifest."""
    service = UpdateMetadataService(str(metadata_dir))

    # Write manifest to disk
    channel_dir = metadata_dir / "stable"
    channel_dir.mkdir(parents=True)
    with open(channel_dir / "1.2.3.json", 'w') as f:
        f.write(sample_manifest.model_dump_json())

    result = service.get_latest("stable")
    assert result is not None
    assert result.version == "1.2.3"


def test_get_latest_returns_highest_version(metadata_dir, sample_manifest):
    """Test get_latest returns highest version when multiple exist."""
    service = UpdateMetadataService(str(metadata_dir))

    # Write two manifests
    channel_dir = metadata_dir / "stable"
    channel_dir.mkdir(parents=True)

    manifest1 = sample_manifest.model_copy(update={"version": "1.2.3"})
    manifest2 = sample_manifest.model_copy(update={"version": "1.3.0"})

    with open(channel_dir / "1.2.3.json", 'w') as f:
        f.write(manifest1.model_dump_json())
    with open(channel_dir / "1.3.0.json", 'w') as f:
        f.write(manifest2.model_dump_json())

    result = service.get_latest("stable")
    assert result is not None
    assert result.version == "1.3.0"


def test_get_history_limit(metadata_dir, sample_manifest):
    """Test get_history respects limit parameter."""
    service = UpdateMetadataService(str(metadata_dir))

    channel_dir = metadata_dir / "stable"
    channel_dir.mkdir(parents=True)

    # Write 5 manifests
    for i in range(5):
        manifest = sample_manifest.model_copy(update={"version": f"1.{i}.0"})
        with open(channel_dir / f"1.{i}.0.json", 'w') as f:
            f.write(manifest.model_dump_json())

    result = service.get_history("stable", limit=3)
    assert len(result) == 3
    # Should be sorted descending
    assert result[0].version == "1.4.0"
    assert result[1].version == "1.3.0"
    assert result[2].version == "1.2.0"


def test_channel_isolation(metadata_dir, sample_manifest):
    """Test manifests are isolated by channel."""
    service = UpdateMetadataService(str(metadata_dir))

    # Write to stable channel
    stable_dir = metadata_dir / "stable"
    stable_dir.mkdir(parents=True)
    with open(stable_dir / "1.2.3.json", 'w') as f:
        f.write(sample_manifest.model_dump_json())

    # Query beta channel (should be empty)
    result = service.get_latest("beta")
    assert result is None

    # Query stable channel (should return manifest)
    result = service.get_latest("stable")
    assert result is not None


def test_cache_invalidation(metadata_dir, sample_manifest):
    """Test cache invalidation reloads manifests."""
    service = UpdateMetadataService(str(metadata_dir))

    channel_dir = metadata_dir / "stable"
    channel_dir.mkdir(parents=True)

    # Initial load (empty)
    result1 = service.get_latest("stable")
    assert result1 is None

    # Write manifest
    with open(channel_dir / "1.2.3.json", 'w') as f:
        f.write(sample_manifest.model_dump_json())

    # Still cached as empty
    result2 = service.get_latest("stable")
    assert result2 is None

    # Invalidate cache
    service.invalidate_cache()

    # Now should return manifest
    result3 = service.get_latest("stable")
    assert result3 is not None
    assert result3.version == "1.2.3"


def test_channel_validation_rejects_invalid_channels(metadata_dir):
    """Test that invalid channels are rejected with ValueError."""
    service = UpdateMetadataService(str(metadata_dir))

    for invalid_channel in ["nightly", "dev", "../etc", "stable/beta", ""]:
        with pytest.raises(ValueError, match="Invalid update channel"):
            service.get_latest(invalid_channel)

        with pytest.raises(ValueError, match="Invalid update channel"):
            service.get_history(invalid_channel, limit=10)


def test_channel_validation_accepts_valid_channels(metadata_dir):
    """Test that valid channels are accepted."""
    service = UpdateMetadataService(str(metadata_dir))

    for valid_channel in ["stable", "beta", "alpha"]:
        result = service.get_latest(valid_channel)
        assert result is None  # No manifests, but no error

