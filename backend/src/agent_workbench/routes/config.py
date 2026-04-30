"""Public configuration endpoint."""

from fastapi import APIRouter, Depends

from ..core.config import Settings, get_settings

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def config(settings: Settings = Depends(get_settings)) -> dict:
    return settings.to_public_dict()
