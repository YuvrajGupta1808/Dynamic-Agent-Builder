"""Agent run streaming and interrupt decisions."""

import json
import uuid
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import APIRouter, Depends
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..core.config import Settings, get_settings
from ..core.dependencies import get_store
from ..domain.models import InterruptDecision, RunStreamRequest
from ..infra.security import validate_model
from ..infra.session_store import SessionStore
from ..services.streaming import stream_run, submit_interrupt_decision

router = APIRouter(prefix="/api", tags=["runs"])


def _encode_multipart_form(fields: dict[str, str], file_field: str, filename: str, content_type: str, file_bytes: bytes) -> tuple[bytes, str]:
    boundary = f"----WorkbenchBoundary{uuid.uuid4().hex}"
    boundary_bytes = boundary.encode("utf-8")
    body = bytearray()
    for key, value in fields.items():
        body.extend(b"--" + boundary_bytes + b"\r\n")
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(b"--" + boundary_bytes + b"\r\n")
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8")
    )
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(b"--" + boundary_bytes + b"--\r\n")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


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
    submit_interrupt_decision(run_id, interrupt_id, payload.decision)
    return approval.model_dump(mode="json", by_alias=True)


@router.post("/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: str = Form("whisper-v3-turbo"),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    _ = settings
    import os

    fireworks_api_key = os.getenv("FIREWORKS_API_KEY")
    if not fireworks_api_key:
        raise HTTPException(status_code=400, detail="FIREWORKS_API_KEY is not configured on the backend.")
    if model not in {"whisper-v3", "whisper-v3-turbo"}:
        raise HTTPException(status_code=400, detail="Unsupported transcription model.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Audio file is empty.")
    if len(file_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 25MB limit for this endpoint.")

    host = "https://audio-prod.api.fireworks.ai" if model == "whisper-v3" else "https://audio-turbo.api.fireworks.ai"
    body, content_type = _encode_multipart_form(
        fields={"model": model, "response_format": "json"},
        file_field="file",
        filename=file.filename or "recording.webm",
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
    )
    last_error_detail = ""
    candidate_hosts = [
        host,
        # Fallbacks for environments that block one host shape.
        "https://audio-prod.api.fireworks.ai",
        "https://audio-turbo.api.fireworks.ai",
    ]
    auth_header_candidates = [
        fireworks_api_key,
        f"Bearer {fireworks_api_key}",
    ]
    payload: dict[str, str] | None = None

    for candidate_host in candidate_hosts:
        for auth_value in auth_header_candidates:
            req = urllib_request.Request(
                f"{candidate_host}/v1/audio/transcriptions",
                data=body,
                method="POST",
                headers={
                    # Fireworks docs show raw API key in Authorization; keep Bearer fallback.
                    "Authorization": auth_value,
                    "Content-Type": content_type,
                    "Accept": "application/json",
                    "User-Agent": "Dynamic-Agent-Workbench/1.0",
                },
            )
            try:
                with urllib_request.urlopen(req, timeout=90) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    break
            except urllib_error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="ignore")
                last_error_detail = details or str(exc.reason)
                continue
            except urllib_error.URLError as exc:
                last_error_detail = str(exc.reason)
                continue
        if payload is not None:
            break

    if payload is None:
        raise HTTPException(status_code=502, detail=f"Fireworks transcription failed: {last_error_detail or 'upstream unavailable'}")

    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="Transcription response was empty.")
    return {"text": text}
