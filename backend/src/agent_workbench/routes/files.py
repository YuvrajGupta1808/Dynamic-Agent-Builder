"""Workspace file tree, content, diff, uploads, and apply."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from ..core.dependencies import get_store, get_workspace_manager
from ..domain.models import ApplyFileRequest
from ..infra.session_store import SessionStore
from ..infra.workspace import WorkspaceManager

router = APIRouter(prefix="/api", tags=["files"])


@router.get("/sessions/{session_id}/files/tree")
def file_tree(
    session_id: str,
    store: SessionStore = Depends(get_store),
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
) -> dict:
    session = store.get_session(session_id)
    tree = workspace_manager.tree(Path(session.cwd))
    return tree.model_dump(mode="json")


@router.get("/sessions/{session_id}/files/content")
def file_content(
    session_id: str,
    path: str = Query(...),
    store: SessionStore = Depends(get_store),
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
) -> dict:
    session = store.get_session(session_id)
    content = workspace_manager.read_file(Path(session.cwd), path)
    return content.model_dump(mode="json")


@router.get("/sessions/{session_id}/files/diff")
def file_diff(
    session_id: str,
    path: str | None = Query(default=None),
    store: SessionStore = Depends(get_store),
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
) -> dict:
    session = store.get_session(session_id)
    diff = workspace_manager.diff(Path(session.cwd), path)
    return diff.model_dump(mode="json", by_alias=True)


@router.post("/sessions/{session_id}/uploads")
async def uploads(
    session_id: str,
    files: list[UploadFile] = File(...),
    store: SessionStore = Depends(get_store),
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
) -> dict:
    session = store.get_session(session_id)
    if session.workspace_mode not in {"uploaded", "local"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploads are not supported for this workspace mode")
    saved = await workspace_manager.save_uploads(Path(session.cwd), files)
    return {"saved": saved}


@router.post("/sessions/{session_id}/files/apply")
def apply_file(
    session_id: str,
    payload: ApplyFileRequest,
    store: SessionStore = Depends(get_store),
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
) -> dict:
    session = store.get_session(session_id)
    if session.workspace_mode == "remote_sandbox":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Remote sandbox file apply is not enabled")
    content = workspace_manager.write_file(Path(session.cwd), payload.path, payload.content)
    return content.model_dump(mode="json")
