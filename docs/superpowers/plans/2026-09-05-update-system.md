# Sage Upgrade System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a comprehensive upgrade system supporting cover upgrades (preserve user data), automatic updates with configurable strategies, and automatic/manual rollback on failure.

**Architecture:** Hybrid approach combining electron-updater (generic provider) for download/install with a custom FastAPI metadata service for update manifest management. Client-side state machine orchestrates the update lifecycle (check → download → install → commit), with health checks on startup triggering automatic rollback after N consecutive failures. Manual rollback within a 7-day window preserves `.prev` installation directory and installer cache.

**Tech Stack:**
- Backend: Python 3.10, FastAPI, Pydantic v2, JSON metadata storage
- Client: Electron 21.4.4, electron-updater (generic provider), TypeScript
- Frontend: React 18, Vite
- Installer: electron-builder NSIS (Windows), AppImage/deb (Linux)
- Security: SHA-512 integrity, HTTPS transport, code signing (Authenticode/GPG)

**Spec:** `docs/superpowers/specs/2026-09-05-update-system-design.md`

## Global Constraints

- **Python version:** Backend uses Python 3.10 (main) / 3.8 (release/win7). Do NOT use system Python.
- **Node version:** Node.js 25.9.0 via nvm
- **Electron version:** 21.4.4 (locked for Win7 compatibility)
- **electron-updater:** Use `generic` provider (not GitHub releases) to integrate with self-hosted metadata service
- **Backward compatibility:** Old clients must gracefully reject manifests they cannot parse (check `min_upgradable_version`)
- **Security:** HTTPS + SHA-512 + code signing required. Metadata signature deferred to v1.1.
- **State persistence:** JSON files in `app.getPath('userData')` (MVP), evolve to SQLite/PostgreSQL later
- **Rollback window:** Default 7 days, configurable via `rollbackWindowDays`
- **Auto-rollback threshold:** Default 3 consecutive health check failures, configurable via `autoRollbackThreshold`
- **Update channels:** stable (default), beta, alpha
- **User data preservation:** NSIS `deleteAppDataOnUninstall: false`, install to original directory

---

## File Structure

### Backend (Python)

```
backend/
├── api/v1/
│   └── updates.py                    # FastAPI router for update endpoints
├── services/
│   └── update_metadata.py            # Metadata storage and retrieval service
├── models/
│   └── update.py                     # Pydantic models (UpdateManifest, FileMeta)
└── tests/
    ├── test_update_metadata.py       # Unit tests for metadata service
    └── test_updates_api.py           # Integration tests for API endpoints
```

**Responsibilities:**
- `backend/models/update.py`: Pydantic models for manifest structure, file metadata, and API responses
- `backend/services/update_metadata.py`: Load/save manifests from JSON files, version comparison, channel filtering
- `backend/api/v1/updates.py`: REST endpoints for fetching latest manifest, version history, and rollback metadata

### Client (Electron/TypeScript)

```
electron/
├── updateManager.ts                  # Main orchestrator, state machine
├── updateState.ts                    # State persistence (StateManager)
├── updateConfig.ts                   # Configuration management (ConfigManager)
├── updateHealthChecker.ts            # Startup health check logic
├── updateRollback.ts                 # Rollback executor
├── ipc/
│   └── updateIpc.ts                  # IPC handlers for renderer communication
└── tests/
    ├── test_updateManager.ts         # Unit tests for state machine
    ├── test_updateState.ts           # Unit tests for state persistence
    ├── test_updateConfig.ts          # Unit tests for config management
    └── test_updateHealthChecker.ts   # Unit tests for health checks
```

**Responsibilities:**
- `updateManager.ts`: Central orchestrator, implements state transitions (check → download → install → commit), coordinates with electron-updater
- `updateState.ts`: Persist update state (current version, last known good, crash count, pending update) with HMAC integrity check
- `updateConfig.ts`: Manage user preferences (update strategy, channel, rollback window, telemetry)
- `updateHealthChecker.ts`: Run 4 health checkpoints on startup (main window loaded, backend /health, DB accessible, IPC responsive), increment crash count on failure
- `updateRollback.ts`: Execute rollback by restoring `.prev` directory and installer cache
- `ipc/updateIpc.ts`: Expose update methods to renderer via IPC (checkForUpdates, downloadUpdate, installUpdate, getUpdateState, canManualRollback, rollback)

### Frontend (React)

```
src/
├── pages/settings/
│   └── UpdateSettings.tsx            # Update settings page
├── components/
│   └── UpdateDialog.tsx              # Update available/download/install dialog
└── hooks/
    └── useUpdate.ts                  # React hook for update state and actions
```

**Responsibilities:**
- `UpdateSettings.tsx`: UI for configuring update strategy, channel, rollback window, auto-rollback threshold, telemetry opt-in
- `UpdateDialog.tsx`: Modal dialog showing update progress, release notes, user actions (install now, later, skip)
- `useUpdate.ts`: Custom hook wrapping IPC calls, manages local state, triggers re-renders on update events

### Installer Scripts

```
build/
└── installer-upgrade.nsh             # NSIS custom script for cover upgrade
```

**Responsibilities:**
- `installer-upgrade.nsh`: Pre-install hook to backup current installation to `.prev`, post-install hook to clean up old `.prev` after successful health check

### Resources

```
resources/
└── default-update-config.json        # Default update configuration
```

**Responsibilities:**
- `default-update-config.json`: Fallback configuration when user config is missing or corrupted

---

## Task 1: Backend Metadata Service Foundation

**Files:**
- Create: `backend/models/update.py`
- Create: `backend/services/update_metadata.py`
- Create: `backend/tests/test_update_metadata.py`
- Modify: `backend/main.py` (add CORS for metadata endpoint, no auth required)

**Interfaces:**
- Consumes: Nothing (foundation layer)
- Produces:
  - `UpdateManifest` (Pydantic model): `version: str`, `channel: str`, `release_date: datetime`, `release_notes: str`, `min_upgradable_version: str`, `files: Dict[str, FileMeta]`, `components: Dict[str, str]`
  - `FileMeta` (Pydantic model): `filename: str`, `url: str`, `sha512: str`, `size: int`, `signature: str`
  - `UpdateMetadataService.get_latest(channel: str) -> Optional[UpdateManifest]`
  - `UpdateMetadataService.get_history(channel: str, limit: int = 10) -> List[UpdateManifest]`

### Step 1: Write Pydantic models

Create `backend/models/update.py`:

```python
from datetime import datetime
from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator
import re


class FileMeta(BaseModel):
    """Metadata for a single update file (installer/binary)."""
    filename: str = Field(..., description="Filename without path")
    url: str = Field(..., description="HTTPS URL to download file")
    sha512: str = Field(..., description="SHA-512 hex digest for integrity check")
    size: int = Field(..., ge=0, description="File size in bytes")
    signature: Optional[str] = Field(None, description="Code signature (Authenticode/GPG)")

    @field_validator('url')
    @classmethod
    def validate_https(cls, v: str) -> str:
        if not v.startswith('https://'):
            raise ValueError('File URL must use HTTPS')
        return v

    @field_validator('sha512')
    @classmethod
    def validate_sha512(cls, v: str) -> str:
        if not re.match(r'^[a-f0-9]{128}$', v):
            raise ValueError('SHA-512 must be 128 hex characters')
        return v


class UpdateManifest(BaseModel):
    """Complete manifest for a single release version."""
    version: str = Field(..., description="Semantic version (e.g., 1.2.3)")
    channel: str = Field(..., description="Update channel: stable | beta | alpha")
    release_date: datetime = Field(..., description="ISO 8601 release timestamp")
    release_notes: str = Field(..., description="Markdown-formatted release notes")
    min_upgradable_version: str = Field(..., description="Minimum version that can upgrade to this")
    files: Dict[str, FileMeta] = Field(..., description="Platform-keyed file metadata")
    components: Dict[str, str] = Field(default_factory=dict, description="Component versions (future use)")

    @field_validator('version')
    @classmethod
    def validate_semver(cls, v: str) -> str:
        if not re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$', v):
            raise ValueError('Version must be semantic version')
        return v

    @field_validator('channel')
    @classmethod
    def validate_channel(cls, v: str) -> str:
        if v not in ('stable', 'beta', 'alpha'):
            raise ValueError('Channel must be stable, beta, or alpha')
        return v
```

### Step 2: Write metadata service

Create `backend/services/update_metadata.py`:

```python
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
```

### Step 3: Write unit tests

Create `backend/tests/test_update_metadata.py`:

```python
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
                url="https://updates.sage.app/Sage-Setup-1.2.3.exe",
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
```

### Step 4: Run tests to verify they fail

```bash
cd /home/fz/project/sage/.claude/worktrees/feat-update-system
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_update_metadata.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'backend.models.update'"

### Step 5: Run tests to verify they pass

After creating the models and service files, run tests again:

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_update_metadata.py -v
```

Expected: PASS (all 6 tests)

### Step 6: Commit

```bash
git add backend/models/update.py backend/services/update_metadata.py backend/tests/test_update_metadata.py
git commit -m "feat: add backend metadata service foundation

- UpdateManifest and FileMeta Pydantic models
- UpdateMetadataService with get_latest() and get_history()
- JSON file storage with channel isolation
- Unit tests for metadata service (6 tests)"
```

---

## Task 2: Backend Update API Routes

**Files:**
- Create: `backend/api/v1/updates.py`
- Modify: `backend/main.py` (register updates router)
- Create: `backend/tests/test_updates_api.py`

**Interfaces:**
- Consumes: `UpdateMetadataService` from Task 1
- Produces:
  - `GET /api/v1/updates/latest?channel=stable` → `UpdateManifest` or 404
  - `GET /api/v1/updates/history?channel=stable&limit=10` → `List[UpdateManifest]`
  - `GET /api/v1/updates/channels` → `List[str]` (available channels)

### Step 1: Write FastAPI router

Create `backend/api/v1/updates.py`:

```python
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from backend.services.update_metadata import UpdateMetadataService
from backend.models.update import UpdateManifest

router = APIRouter(prefix="/updates", tags=["updates"])

# Singleton service instance (in production, inject via dependency)
_metadata_service = UpdateMetadataService()


@router.get("/latest", response_model=UpdateManifest)
async def get_latest_manifest(
    channel: str = Query("stable", description="Update channel")
):
    """Get the latest manifest for a channel."""
    manifest = _metadata_service.get_latest(channel)
    if not manifest:
        raise HTTPException(
            status_code=404,
            detail=f"No manifests found for channel '{channel}'"
        )
    return manifest


@router.get("/history", response_model=List[UpdateManifest])
async def get_version_history(
    channel: str = Query("stable", description="Update channel"),
    limit: int = Query(10, ge=1, le=100, description="Max results")
):
    """Get version history for a channel."""
    return _metadata_service.get_history(channel, limit)


@router.get("/channels", response_model=List[str])
async def get_available_channels():
    """Get list of available update channels."""
    # In MVP, channels are fixed. Future: read from filesystem or config.
    return ["stable", "beta", "alpha"]
```

### Step 2: Register router in main.py

Modify `backend/main.py` (add near other router registrations):

```python
from backend.api.v1 import updates

# ... existing code ...

app.include_router(updates.router, prefix="/api/v1")
```

### Step 3: Write integration tests

Create `backend/tests/test_updates_api.py`:

```python
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from pathlib import Path
import json
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
    monkeypatch.setattr(updates, '_metadata_service', test_service)

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
                url="https://updates.sage.app/Sage-Setup-1.2.3.exe",
                sha512="a" * 128,
                size=104857600,
                signature="sig-placeholder"
            )
        },
        components={}
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
    with open(channel_dir / "1.2.3.json", 'w') as f:
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
        with open(channel_dir / f"1.{i}.0.json", 'w') as f:
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
```

### Step 4: Run tests

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_updates_api.py -v
```

Expected: PASS (all 5 tests)

### Step 5: Manual test with curl

Start the backend server:

```bash
conda activate sage-backend && python backend/main.py
```

In another terminal:

```bash
# Create sample manifest for testing
mkdir -p data/update-metadata/stable
cat > data/update-metadata/stable/1.2.3.json << 'EOF'
{
  "version": "1.2.3",
  "channel": "stable",
  "release_date": "2026-09-05T12:00:00",
  "release_notes": "## What's New\n- Feature A\n- Bug fix B",
  "min_upgradable_version": "1.0.0",
  "files": {
    "win-x64": {
      "filename": "Sage-Setup-1.2.3.exe",
      "url": "https://updates.sage.app/Sage-Setup-1.2.3.exe",
      "sha512": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "size": 104857600,
      "signature": "sig-placeholder"
    }
  },
  "components": {}
}
EOF

# Test endpoints
curl http://127.0.0.1:8765/api/v1/updates/latest?channel=stable
curl http://127.0.0.1:8765/api/v1/updates/history?channel=stable&limit=10
curl http://127.0.0.1:8765/api/v1/updates/channels
```

### Step 6: Commit

```bash
git add backend/api/v1/updates.py backend/main.py backend/tests/test_updates_api.py
git commit -m "feat: add backend update API routes

- GET /api/v1/updates/latest - fetch latest manifest
- GET /api/v1/updates/history - fetch version history
- GET /api/v1/updates/channels - list available channels
- Integration tests for all endpoints (5 tests)"
```

---

## Task 3: Client Update State Management

**Files:**
- Create: `electron/updateState.ts`
- Create: `electron/updateConfig.ts`
- Create: `electron/tests/test_updateState.ts`
- Create: `electron/tests/test_updateConfig.ts`

**Interfaces:**
- Consumes: Electron `app.getPath('userData')`, Node `fs/promises`
- Produces:
  - `StateManager.getState(): Promise<UpdateState>`
  - `StateManager.setState(state: UpdateState): Promise<void>`
  - `ConfigManager.getConfig(): Promise<UpdateConfig>`
  - `ConfigManager.setConfig(config: UpdateConfig): Promise<void>`

### Step 1: Define TypeScript interfaces

Create `electron/updateState.ts`:

```typescript
import { app } from 'electron';
import * as fs from 'fs/promises';
import * as path from 'path';
import * as crypto from 'crypto';

export interface UpdateState {
  currentVersion: string;
  lastKnownGoodVersion: string;
  lastKnownGoodInstallDate: string; // ISO 8601
  crashCount: number;
  rollbackWindowDays: number;
  updateStrategy: 'manual' | 'auto-download' | 'auto-install';
  lastCheckTime: string | null; // ISO 8601
  pendingUpdate: {
    version: string;
    downloadedAt: string; // ISO 8601
  } | null;
  lastRecordedVersion: string;
}

const STATE_FILE = 'update-state.json';
const HMAC_SECRET_ENV = 'SAGE_UPDATE_STATE_HMAC_SECRET';

export class StateManager {
  private statePath: string;
  private hmacSecret: string;

  constructor() {
    this.statePath = path.join(app.getPath('userData'), STATE_FILE);
    this.hmacSecret = process.env[HMAC_SECRET_ENV] || 'default-dev-secret-change-in-prod';
  }

  async getState(): Promise<UpdateState> {
    try {
      const data = await fs.readFile(this.statePath, 'utf-8');
      const parsed = JSON.parse(data);

      // Verify HMAC integrity
      const { hmac, ...state } = parsed;
      const expectedHmac = this.computeHmac(JSON.stringify(state));
      if (hmac !== expectedHmac) {
        console.warn('Update state HMAC mismatch, resetting to defaults');
        return this.getDefaultState();
      }

      return state as UpdateState;
    } catch (error) {
      // File doesn't exist or is corrupted, return defaults
      return this.getDefaultState();
    }
  }

  async setState(state: UpdateState): Promise<void> {
    const stateJson = JSON.stringify(state);
    const hmac = this.computeHmac(stateJson);
    const data = JSON.stringify({ ...state, hmac });

    await fs.writeFile(this.statePath, data, 'utf-8');
  }

  private getDefaultState(): UpdateState {
    const currentVersion = app.getVersion();
    return {
      currentVersion,
      lastKnownGoodVersion: currentVersion,
      lastKnownGoodInstallDate: new Date().toISOString(),
      crashCount: 0,
      rollbackWindowDays: 7,
      updateStrategy: 'auto-download',
      lastCheckTime: null,
      pendingUpdate: null,
      lastRecordedVersion: currentVersion,
    };
  }

  private computeHmac(data: string): string {
    return crypto
      .createHmac('sha256', this.hmacSecret)
      .update(data)
      .digest('hex');
  }
}
```

### Step 2: Define config manager

Create `electron/updateConfig.ts`:

```typescript
import { app } from 'electron';
import * as fs from 'fs/promises';
import * as path from 'path';

export type UpdateStrategy = 'manual' | 'auto-download' | 'auto-install';
export type UpdateChannel = 'stable' | 'beta' | 'alpha';

export interface UpdateConfig {
  updateStrategy: UpdateStrategy;
  channel: UpdateChannel;
  rollbackWindowDays: number;
  autoRollbackThreshold: number;
  checkIntervalHours: number;
  updateServerUrl: string;
  enableTelemetry: boolean;
  cacheRetentionDays: number;
}

const CONFIG_FILE = 'update-config.json';
const DEFAULT_CONFIG_URL = 'https://updates.sage.app';

export class ConfigManager {
  private configPath: string;

  constructor() {
    this.configPath = path.join(app.getPath('userData'), CONFIG_FILE);
  }

  async getConfig(): Promise<UpdateConfig> {
    try {
      const data = await fs.readFile(this.configPath, 'utf-8');
      return JSON.parse(data) as UpdateConfig;
    } catch (error) {
      // File doesn't exist or is corrupted, return defaults
      return this.getDefaultConfig();
    }
  }

  async setConfig(config: UpdateConfig): Promise<void> {
    await fs.writeFile(this.configPath, JSON.stringify(config, null, 2), 'utf-8');
  }

  private getDefaultConfig(): UpdateConfig {
    return {
      updateStrategy: 'auto-download',
      channel: 'stable',
      rollbackWindowDays: 7,
      autoRollbackThreshold: 3,
      checkIntervalHours: 24,
      updateServerUrl: DEFAULT_CONFIG_URL,
      enableTelemetry: false,
      cacheRetentionDays: 30,
    };
  }
}
```

### Step 3: Write unit tests for StateManager

Create `electron/tests/test_updateState.ts`:

```typescript
import { expect } from 'chai';
import * as fs from 'fs/promises';
import * as path from 'path';
import { StateManager, UpdateState } from '../updateState';

// Mock Electron app
const mockUserData = '/tmp/test-user-data';
const mockApp = {
  getPath: (name: string) => {
    if (name === 'userData') return mockUserData;
    throw new Error(`Unknown path: ${name}`);
  },
  getVersion: () => '1.0.0',
};

// Mock app module
(global as any).require = (module: string) => {
  if (module === 'electron') return { app: mockApp };
  throw new Error(`Unknown module: ${module}`);
};

describe('StateManager', () => {
  let stateManager: StateManager;
  let statePath: string;

  beforeEach(async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    stateManager = new StateManager();
    statePath = path.join(mockUserData, 'update-state.json');
  });

  afterEach(async () => {
    await fs.rm(mockUserData, { recursive: true, force: true });
  });

  it('returns default state when file does not exist', async () => {
    const state = await stateManager.getState();
    expect(state.currentVersion).to.equal('1.0.0');
    expect(state.crashCount).to.equal(0);
    expect(state.updateStrategy).to.equal('auto-download');
  });

  it('persists and retrieves state', async () => {
    const newState: UpdateState = {
      currentVersion: '1.2.3',
      lastKnownGoodVersion: '1.2.3',
      lastKnownGoodInstallDate: '2026-09-05T12:00:00.000Z',
      crashCount: 2,
      rollbackWindowDays: 7,
      updateStrategy: 'manual',
      lastCheckTime: '2026-09-05T10:00:00.000Z',
      pendingUpdate: null,
      lastRecordedVersion: '1.2.3',
    };

    await stateManager.setState(newState);
    const retrieved = await stateManager.getState();

    expect(retrieved.currentVersion).to.equal('1.2.3');
    expect(retrieved.crashCount).to.equal(2);
    expect(retrieved.updateStrategy).to.equal('manual');
  });

  it('includes HMAC in persisted state', async () => {
    const state = await stateManager.getState();
    await stateManager.setState(state);

    const data = await fs.readFile(statePath, 'utf-8');
    const parsed = JSON.parse(data);

    expect(parsed).to.have.property('hmac');
    expect(parsed.hmac).to.be.a('string');
    expect(parsed.hmac).to.have.length(64); // SHA-256 hex
  });

  it('returns defaults when HMAC is tampered', async () => {
    const state = await stateManager.getState();
    await stateManager.setState(state);

    // Tamper with state
    const data = await fs.readFile(statePath, 'utf-8');
    const parsed = JSON.parse(data);
    parsed.crashCount = 999; // Modify state without updating HMAC
    await fs.writeFile(statePath, JSON.stringify(parsed), 'utf-8');

    const retrieved = await stateManager.getState();
    expect(retrieved.crashCount).to.equal(0); // Reset to default
  });
});
```

### Step 4: Write unit tests for ConfigManager

Create `electron/tests/test_updateConfig.ts`:

```typescript
import { expect } from 'chai';
import * as fs from 'fs/promises';
import * as path from 'path';
import { ConfigManager, UpdateConfig } from '../updateConfig';

// Mock Electron app
const mockUserData = '/tmp/test-user-data-config';
const mockApp = {
  getPath: (name: string) => {
    if (name === 'userData') return mockUserData;
    throw new Error(`Unknown path: ${name}`);
  },
};

(global as any).require = (module: string) => {
  if (module === 'electron') return { app: mockApp };
  throw new Error(`Unknown module: ${module}`);
};

describe('ConfigManager', () => {
  let configManager: ConfigManager;
  let configPath: string;

  beforeEach(async () => {
    await fs.mkdir(mockUserData, { recursive: true });
    configManager = new ConfigManager();
    configPath = path.join(mockUserData, 'update-config.json');
  });

  afterEach(async () => {
    await fs.rm(mockUserData, { recursive: true, force: true });
  });

  it('returns default config when file does not exist', async () => {
    const config = await configManager.getConfig();
    expect(config.updateStrategy).to.equal('auto-download');
    expect(config.channel).to.equal('stable');
    expect(config.rollbackWindowDays).to.equal(7);
    expect(config.autoRollbackThreshold).to.equal(3);
  });

  it('persists and retrieves config', async () => {
    const newConfig: UpdateConfig = {
      updateStrategy: 'manual',
      channel: 'beta',
      rollbackWindowDays: 14,
      autoRollbackThreshold: 5,
      checkIntervalHours: 12,
      updateServerUrl: 'https://custom-updates.example.com',
      enableTelemetry: true,
      cacheRetentionDays: 60,
    };

    await configManager.setConfig(newConfig);
    const retrieved = await configManager.getConfig();

    expect(retrieved.updateStrategy).to.equal('manual');
    expect(retrieved.channel).to.equal('beta');
    expect(retrieved.rollbackWindowDays).to.equal(14);
  });
});
```

### Step 5: Run tests

```bash
cd /home/fz/project/sage/.claude/worktrees/feat-update-system
npm test -- electron/tests/test_updateState.ts electron/tests/test_updateConfig.ts
```

Expected: PASS (all 6 tests)

### Step 6: Commit

```bash
git add electron/updateState.ts electron/updateConfig.ts electron/tests/
git commit -m "feat: add client update state and config management

- StateManager with HMAC integrity check
- ConfigManager for user preferences
- Unit tests for state persistence and config (6 tests)"
```

---

## Task 4: UpdateManager State Machine (Partial)

**Files:**
- Create: `electron/updateManager.ts` (partial implementation)
- Create: `electron/tests/test_updateManager.ts`

**Interfaces:**
- Consumes: `StateManager`, `ConfigManager` from Task 3, `fetch` API
- Produces:
  - `UpdateManager.checkForUpdates(): Promise<CheckResult>`
  - `UpdateManager.downloadUpdate(): Promise<void>` (stub for now)
  - `UpdateManager.installUpdate(): Promise<void>` (stub for now)

### Step 1: Write UpdateManager skeleton

Create `electron/updateManager.ts`:

```typescript
import { StateManager, UpdateState } from './updateState';
import { ConfigManager, UpdateConfig } from './updateConfig';

export interface CheckResult {
  updateAvailable: boolean;
  version?: string;
  releaseNotes?: string;
  downloadUrl?: string;
}

export class UpdateManager {
  private stateManager: StateManager;
  private configManager: ConfigManager;

  constructor() {
    this.stateManager = new StateManager();
    this.configManager = new ConfigManager();
  }

  async checkForUpdates(): Promise<CheckResult> {
    const config = await this.configManager.getConfig();
    const state = await this.stateManager.getState();

    try {
      // Fetch latest manifest from server
      const response = await fetch(
        `${config.updateServerUrl}/api/v1/updates/latest?channel=${config.channel}`
      );

      if (!response.ok) {
        if (response.status === 404) {
          return { updateAvailable: false };
        }
        throw new Error(`Server returned ${response.status}`);
      }

      const manifest = await response.json();

      // Check if version is newer than current
      if (this.isNewerVersion(manifest.version, state.currentVersion)) {
        // Check if current version meets minimum upgradable version
        if (!this.meetsMinimumVersion(state.currentVersion, manifest.min_upgradable_version)) {
          console.warn(`Current version ${state.currentVersion} cannot upgrade to ${manifest.version}`);
          return { updateAvailable: false };
        }

        // Determine platform-specific file
        const platformKey = this.getPlatformKey();
        const fileMeta = manifest.files[platformKey];

        if (!fileMeta) {
          console.warn(`No update file for platform ${platformKey}`);
          return { updateAvailable: false };
        }

        // Update state with check time
        state.lastCheckTime = new Date().toISOString();
        await this.stateManager.setState(state);

        return {
          updateAvailable: true,
          version: manifest.version,
          releaseNotes: manifest.release_notes,
          downloadUrl: fileMeta.url,
        };
      }

      // No update available
      state.lastCheckTime = new Date().toISOString();
      await this.stateManager.setState(state);

      return { updateAvailable: false };
    } catch (error) {
      console.error('Failed to check for updates:', error);
      throw error;
    }
  }

  async downloadUpdate(): Promise<void> {
    // TODO: Implement in Task 5 (electron-updater integration)
    throw new Error('Not implemented');
  }

  async installUpdate(): Promise<void> {
    // TODO: Implement in Task 6 (cover upgrade coordinator)
    throw new Error('Not implemented');
  }

  private isNewerVersion(latest: string, current: string): boolean {
    const [latestMajor, latestMinor, latestPatch] = latest.split('.').map(Number);
    const [currentMajor, currentMinor, currentPatch] = current.split('.').map(Number);

    if (latestMajor !== currentMajor) return latestMajor > currentMajor;
    if (latestMinor !== currentMinor) return latestMinor > currentMinor;
    return latestPatch > currentPatch;
  }

  private meetsMinimumVersion(current: string, minimum: string): boolean {
    const [currentMajor, currentMinor, currentPatch] = current.split('.').map(Number);
    const [minMajor, minMinor, minPatch] = minimum.split('.').map(Number);

    if (currentMajor !== minMajor) return currentMajor >= minMajor;
    if (currentMinor !== minMinor) return currentMinor >= minMinor;
    return currentPatch >= minPatch;
  }

  private getPlatformKey(): string {
    const platform = process.platform;
    const arch = process.arch;

    if (platform === 'win32') {
      return arch === 'x64' ? 'win-x64' : 'win-ia32';
    } else if (platform === 'linux') {
      return 'linux-x64';
    } else if (platform === 'darwin') {
      return arch === 'arm64' ? 'mac-arm64' : 'mac-x64';
    }

    throw new Error(`Unsupported platform: ${platform}-${arch}`);
  }
}
```

### Step 2: Write unit tests

Create `electron/tests/test_updateManager.ts`:

```typescript
import { expect } from 'chai';
import * as sinon from 'sinon';
import { UpdateManager } from '../updateManager';

// Mock fetch
const mockFetch = sinon.stub(global, 'fetch');

describe('UpdateManager', () => {
  let updateManager: UpdateManager;

  beforeEach(() => {
    updateManager = new UpdateManager();
    mockFetch.reset();
  });

  afterEach(() => {
    sinon.restore();
  });

  describe('checkForUpdates', () => {
    it('returns updateAvailable: false when server returns 404', async () => {
      mockFetch.resolves({
        ok: false,
        status: 404,
        json: async () => ({}),
      } as any);

      const result = await updateManager.checkForUpdates();
      expect(result.updateAvailable).to.be.false;
    });

    it('returns updateAvailable: true when newer version exists', async () => {
      mockFetch.resolves({
        ok: true,
        status: 200,
        json: async () => ({
          version: '1.3.0',
          channel: 'stable',
          release_date: '2026-09-05T12:00:00Z',
          release_notes: '## New features',
          min_upgradable_version: '1.0.0',
          files: {
            'win-x64': {
              filename: 'Sage-Setup-1.3.0.exe',
              url: 'https://updates.sage.app/Sage-Setup-1.3.0.exe',
              sha512: 'a'.repeat(128),
              size: 104857600,
              signature: 'sig',
            },
          },
          components: {},
        }),
      } as any);

      const result = await updateManager.checkForUpdates();
      expect(result.updateAvailable).to.be.true;
      expect(result.version).to.equal('1.3.0');
      expect(result.releaseNotes).to.equal('## New features');
    });

    it('returns updateAvailable: false when current version is up to date', async () => {
      mockFetch.resolves({
        ok: true,
        status: 200,
        json: async () => ({
          version: '1.0.0', // Same as current
          channel: 'stable',
          release_date: '2026-09-05T12:00:00Z',
          release_notes: 'Initial release',
          min_upgradable_version: '1.0.0',
          files: {
            'win-x64': {
              filename: 'Sage-Setup-1.0.0.exe',
              url: 'https://updates.sage.app/Sage-Setup-1.0.0.exe',
              sha512: 'a'.repeat(128),
              size: 104857600,
              signature: 'sig',
            },
          },
          components: {},
        }),
      } as any);

      const result = await updateManager.checkForUpdates();
      expect(result.updateAvailable).to.be.false;
    });

    it('throws error when server returns 500', async () => {
      mockFetch.resolves({
        ok: false,
        status: 500,
        json: async () => ({}),
      } as any);

      try {
        await updateManager.checkForUpdates();
        expect.fail('Should have thrown error');
      } catch (error: any) {
        expect(error.message).to.include('Server returned 500');
      }
    });
  });
});
```

### Step 3: Run tests

```bash
npm test -- electron/tests/test_updateManager.ts
```

Expected: PASS (all 4 tests)

### Step 4: Commit

```bash
git add electron/updateManager.ts electron/tests/test_updateManager.ts
git commit -m "feat: add UpdateManager state machine (checkForUpdates)

- Version comparison logic (semver)
- Platform-specific file selection
- Minimum upgradable version check
- Unit tests for update check (4 tests)"
```

---

## Tasks 5-12: Remaining Implementation

Tasks 5-12 continue with electron-updater integration, cover upgrade coordinator, health checks, rollback mechanism, IPC handlers, settings UI, update dialog, and integration/E2E tests. These will be implemented in subsequent iterations following the same TDD pattern established in Tasks 1-4.

**Task 5:** electron-updater Integration (GenericProvider)
**Task 6:** Cover Upgrade Coordinator (NSIS integration, .prev backup)
**Task 7:** Startup Health Check System (4 checkpoints, crash counter)
**Task 8:** Rollback Mechanism (auto-rollback, manual rollback, .prev restore)
**Task 9:** IPC Handlers (renderer communication)
**Task 10:** Settings UI (update preferences, manual check)
**Task 11:** Update Dialog (progress, release notes, user actions)
**Task 12:** Integration and E2E Tests (end-to-end upgrade flow)

---

## Workload Estimate

| Task | Estimated Hours | Dependencies |
|------|----------------|--------------|
| Task 1 | 2 hours | None |
| Task 2 | 2 hours | Task 1 |
| Task 3 | 3 hours | None |
| Task 4 | 3 hours | Task 3 |
| Task 5 | 4 hours | Task 4 |
| Task 6 | 4 hours | Task 5 |
| Task 7 | 3 hours | Task 3 |
| Task 8 | 4 hours | Task 7 |
| Task 9 | 2 hours | Task 4, 8 |
| Task 10 | 3 hours | Task 9 |
| Task 11 | 3 hours | Task 9 |
| Task 12 | 5 hours | All above |
| **Total** | **~38 hours** | |

**Recommended execution order:** Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 7 → Task 8 → Task 6 → Task 9 → Task 10 → Task 11 → Task 12
