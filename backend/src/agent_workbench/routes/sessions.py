"""Session creation."""

from fastapi import APIRouter, Depends

from ..core.config import Settings, get_settings
from ..core.dependencies import get_store, get_workspace_manager
from ..domain.models import CreateSessionRequest, GenerateTitleRequest
from ..infra.security import require_auth, validate_model
from ..infra.session_store import SessionStore
from ..infra.workspace import WorkspaceManager, create_uploaded_seed
from ..services.titles import generate_short_title

router = APIRouter(prefix="/api", tags=["sessions"], dependencies=[Depends(require_auth)])


@router.post("/sessions")
def create_session(
    payload: CreateSessionRequest,
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    workspace_manager: WorkspaceManager = Depends(get_workspace_manager),
) -> dict:
    model = validate_model(payload.model or settings.default_model, settings)
    if payload.workspace_mode == "remote_sandbox" and not settings.remote_sandbox_enabled:
        root = workspace_manager.root_for("remote_sandbox", "pending", payload.cwd, payload.workspace)
        root.mkdir(parents=True, exist_ok=True)
        workspace = workspace_manager.create("remote_sandbox", payload.cwd, payload.workspace)
    else:
        workspace = workspace_manager.create(payload.workspace_mode, payload.cwd, payload.workspace)
    if payload.workspace_mode == "uploaded":
        create_uploaded_seed(workspace.root)
    session = store.create_session(
        session_id=workspace.session_id,
        cwd=str(workspace.root),
        workspace_mode=payload.workspace_mode,
        mode=payload.mode,
        model=model,
    )
    return session.model_dump(mode="json", by_alias=True)


@router.post("/sessions/{session_id}/title")
def create_title(
    session_id: str,
    payload: GenerateTitleRequest,
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> dict:
    session = store.get_session(session_id)
    model = validate_model(payload.model or session.model, settings)
    title = generate_short_title(payload.prompt, model)
    return {"title": title}
