"""Public configuration endpoint."""

from fastapi import APIRouter, Depends

from ..core.config import Settings, get_settings
from ..infra.security import require_auth

router = APIRouter(prefix="/api", tags=["config"], dependencies=[Depends(require_auth)])


@router.get("/config")
def config(settings: Settings = Depends(get_settings)) -> dict:
    return settings.to_public_dict()
