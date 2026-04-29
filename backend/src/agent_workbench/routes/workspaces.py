"""Workspace listing and creation."""

from fastapi import APIRouter, Depends

from ..core.dependencies import get_workspace_manager
from ..domain.models import CreateWorkspaceRequest
from ..infra.security import require_auth
from ..infra.workspace import WorkspaceManager

router = APIRouter(prefix="/api", tags=["workspaces"], dependencies=[Depends(require_auth)])


@router.get("/workspaces")
def list_workspaces(workspace_manager: WorkspaceManager = Depends(get_workspace_manager)) -> dict:
    return {"workspaces": workspace_manager.list_workspaces()}


@router.post("/workspaces")
def create_workspace(
    payload: CreateWorkspaceRequest,
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
) -> dict:
    root = workspace_manager.ensure_workspace(payload.name)
    return {"name": root.name, "path": str(root), "created": True}
