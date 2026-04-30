"""Workspace listing and creation."""

from fastapi import APIRouter, Depends

from ..core.dependencies import get_workspace_manager
from ..domain.models import CreateWorkspaceRequest
from ..infra.security import AuthContext, get_auth_context
from ..infra.workspace import WorkspaceManager

router = APIRouter(prefix="/api", tags=["workspaces"])


@router.get("/workspaces")
def list_workspaces(
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    return {"workspaces": workspace_manager.list_workspaces(auth.user_id)}


@router.post("/workspaces")
def create_workspace(
    payload: CreateWorkspaceRequest,
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    root = workspace_manager.ensure_workspace(auth.user_id, payload.name)
    return {"name": root.name, "path": str(root), "created": True}
