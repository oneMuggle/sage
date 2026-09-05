from fastapi import APIRouter, HTTPException, Query
from typing import List
from backend.services.update_metadata import UpdateMetadataService, validate_channel
from backend.models.update import UpdateManifest

router = APIRouter(prefix="/updates", tags=["updates"])

# Singleton service instance (in production, inject via dependency)
_metadata_service = UpdateMetadataService()


@router.get("/latest", response_model=UpdateManifest)
async def get_latest_manifest(
    channel: str = Query("stable", description="Update channel"),
):
    """Get the latest manifest for a channel."""
    try:
        validate_channel(channel)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    manifest = _metadata_service.get_latest(channel)
    if not manifest:
        raise HTTPException(
            status_code=404,
            detail=f"No manifests found for channel '{channel}'",
        )
    return manifest


@router.get("/history", response_model=List[UpdateManifest])
async def get_version_history(
    channel: str = Query("stable", description="Update channel"),
    limit: int = Query(10, ge=1, le=100, description="Max results"),
):
    """Get version history for a channel."""
    try:
        validate_channel(channel)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _metadata_service.get_history(channel, limit)


@router.get("/channels", response_model=List[str])
async def get_available_channels():
    """Get list of available update channels."""
    # In MVP, channels are fixed. Future: read from filesystem or config.
    return ["stable", "beta", "alpha"]
