"""Agent run streaming and interrupt decisions."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..core.config import Settings, get_settings
from ..core.dependencies import get_store
from ..domain.models import InterruptDecision, RunStreamRequest
from ..infra.security import require_auth, validate_model
from ..infra.session_store import SessionStore
from ..services.streaming import stream_run

router = APIRouter(prefix="/api", tags=["runs"], dependencies=[Depends(require_auth)])


@router.post("/sessions/{session_id}/runs/stream")
def run_stream(
    session_id: str,
    payload: RunStreamRequest,
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
) -> StreamingResponse:
    session = store.get_session(session_id)
    validate_model(payload.model or session.model, settings)
    run_id = store.create_run(session_id)
    generator = stream_run(
        session=session,
        request=payload,
        run_id=run_id,
        store=store,
        command_timeout_seconds=settings.command_timeout_seconds,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/interrupts/{interrupt_id}")
def decide_interrupt(
    run_id: str,
    interrupt_id: str,
    payload: InterruptDecision,
    store: SessionStore = Depends(get_store),
) -> dict:
    approval = store.decide_interrupt(run_id, interrupt_id, payload.decision)
    return approval.model_dump(mode="json", by_alias=True)
