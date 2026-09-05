import json
from pathlib import Path
from typing import Dict, List, Optional
from packaging.version import Version
from backend.models.update import UpdateManifest


class UpdateMetadataService:
    """Manages update manifest storage and retrieval."""

    def __init__(self, metadata_dir: str = "data/update-metadata"):
        self.metadata_dir = Path(metadata_dir)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, List[UpdateManifest]] = {}

    def _load_manifests(self, channel: str) -> List[UpdateManifest]:
        """Load all manifests for a channel from JSON files."""
        if channel in self._cache:
            return self._cache[channel]

        channel_dir = self.metadata_dir / channel
        if not channel_dir.exists():
            return []

        manifests = []
        for manifest_file in channel_dir.glob("*.json"):
            with open(manifest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                manifests.append(UpdateManifest(**data))

        # Sort by version descending
        manifests.sort(key=lambda m: Version(m.version), reverse=True)
        self._cache[channel] = manifests
        return manifests

    def get_latest(self, channel: str) -> Optional[UpdateManifest]:
        """Get the latest manifest for a channel."""
        manifests = self._load_manifests(channel)
        return manifests[0] if manifests else None

    def get_history(self, channel: str, limit: int = 10) -> List[UpdateManifest]:
        """Get version history for a channel."""
        manifests = self._load_manifests(channel)
        return manifests[:limit]

    def invalidate_cache(self):
        """Clear cached manifests (call after adding new manifests)."""
        self._cache.clear()
