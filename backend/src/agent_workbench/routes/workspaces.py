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


@router.get("/workspaces/{workspace_name}/health")
def workspace_health(
    workspace_name: str,
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    root = workspace_manager.workspace_path(auth.user_id, workspace_name)
    health = workspace_manager.workspace_health(root)
    return health.model_dump(mode="json", by_alias=True)


@router.post("/workspaces/{workspace_name}/repair")
def repair_workspace(
    workspace_name: str,
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    root = workspace_manager.workspace_path(auth.user_id, workspace_name)
    health = workspace_manager.repair_workspace(root)
    return health.model_dump(mode="json", by_alias=True)
