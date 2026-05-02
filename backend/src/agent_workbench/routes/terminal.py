"""Interactive terminal websocket routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from ..core.config import Settings, get_settings
from ..core.dependencies import get_store, get_terminal_manager
from ..infra.security import authenticate_request
from ..infra.session_store import SessionStore
from ..services.terminal import TerminalManager, parse_terminal_message

router = APIRouter(prefix="/api", tags=["terminal"])


@router.websocket("/sessions/{session_id}/terminal/ws")
async def terminal_ws(
    websocket: WebSocket,
    session_id: str,
    settings: Settings = Depends(get_settings),
    store: SessionStore = Depends(get_store),
    terminals: TerminalManager = Depends(get_terminal_manager),
) -> None:
    token = websocket.query_params.get("token", "")
    try:
        authenticate_request(f"Bearer {token}", settings)
        session = store.get_session(session_id)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    client_id = uuid4().hex
    terminals.connect(session_id, Path(session.cwd), client_id)
    await websocket.accept()
    async def _pump_terminal_output() -> None:
        while True:
            event = await asyncio.to_thread(terminals.read_event, session_id, client_id, 0.25)
            if event is None:
                await asyncio.sleep(0.01)
                continue
            await websocket.send_json(event)

    async def _pump_terminal_input() -> None:
        while True:
            message = await websocket.receive_text()
            payload = parse_terminal_message(message)
            event_type = str(payload.get("type") or "")
            if event_type == "input":
                terminals.write(session_id, str(payload.get("data") or ""))
            elif event_type == "resize":
                terminals.resize(session_id, int(payload.get("cols") or 80), int(payload.get("rows") or 24))
            elif event_type == "interrupt":
                terminals.interrupt(session_id)
            else:
                await websocket.send_json({"type": "error", "message": f"Unsupported terminal event: {event_type}"})

    output_task = asyncio.create_task(_pump_terminal_output())
    input_task = asyncio.create_task(_pump_terminal_input())
    try:
        done, pending = await asyncio.wait({output_task, input_task}, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is None:
                continue
            if isinstance(exc, WebSocketDisconnect):
                break
            if isinstance(exc, ValueError):
                await websocket.send_json({"type": "error", "message": str(exc)})
                break
            raise exc
    except WebSocketDisconnect:
        pass
    finally:
        output_task.cancel()
        input_task.cancel()
        terminals.disconnect(session_id, client_id)
