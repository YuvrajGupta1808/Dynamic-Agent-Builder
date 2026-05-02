from pathlib import Path
import json

from fastapi.testclient import TestClient

from agent_workbench.api import create_app
from agent_workbench.core.config import get_settings
from agent_workbench.core.dependencies import get_store, get_workspace_manager
from agent_workbench.domain.models import ApprovalRecord


def client_for(tmp_path: Path, monkeypatch) -> TestClient:
    workspace_root = tmp_path / "workspaces"
    monkeypatch.setenv("WORKBENCH_TOKEN", "test-token")
    monkeypatch.setenv("WORKBENCH_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("WORKBENCH_ALLOWED_ROOTS", str(workspace_root))
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / ".data"))
    monkeypatch.setenv("WORKBENCH_DEFAULT_MODEL", "mock:deterministic")
    get_settings.cache_clear()
    get_store.cache_clear()
    get_workspace_manager.cache_clear()
    return TestClient(create_app())


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_config_requires_auth(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    assert client.get("/api/config").status_code == 401
    response = client.get("/api/config", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["defaultModel"] == "mock:deterministic"


def test_create_session_and_stream(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)

    workspace_response = client.post("/api/workspaces", headers=auth_headers(), json={"name": "project"})
    assert workspace_response.status_code == 200

    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "project",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]
    assert session_response.json()["cwd"].endswith("/workspaces/_local/project")

    tree_response = client.get(f"/api/sessions/{session_id}/files/tree", headers=auth_headers())
    assert tree_response.status_code == 200
    children = {child["name"] for child in tree_response.json().get("children") or []}
    assert children == {"README.md", "agents"}

    with client.stream(
        "POST",
        f"/api/sessions/{session_id}/runs/stream",
        headers={**auth_headers(), "Content-Type": "application/json"},
        json={"message": "hello"},
    ) as response:
        body = "".join(response.iter_text())
    assert "event: token" in body
    assert "event: done" in body


def _recv_terminal_output(websocket, expected: str, attempts: int = 40) -> str:
    chunks: list[str] = []
    for _ in range(attempts):
        event = websocket.receive_json()
        if event["type"] == "output":
            chunks.append(event["data"])
            if expected in "".join(chunks):
                break
        if event["type"] == "status":
            continue
    return "".join(chunks)


def test_terminal_websocket_runs_in_session_workspace(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    client.post("/api/workspaces", headers=auth_headers(), json={"name": "project"})
    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "project",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    session_id = session_response.json()["id"]
    cwd = session_response.json()["cwd"]

    with client.websocket_connect(f"/api/sessions/{session_id}/terminal/ws?token=test-token") as websocket:
        websocket.send_text(json.dumps({"type": "input", "data": "pwd\n"}))
        output = _recv_terminal_output(websocket, cwd, attempts=60)
        assert cwd in output

        websocket.send_text(json.dumps({"type": "input", "data": "cd agents\npwd\n"}))
        output = _recv_terminal_output(websocket, f"{cwd}/agents", attempts=80)
        assert f"{cwd}/agents" in output


def test_managed_workspace_create_and_session(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)

    workspace_response = client.post("/api/workspaces", headers=auth_headers(), json={"name": "Client App"})
    assert workspace_response.status_code == 200
    assert workspace_response.json()["name"] == "Client-App"

    list_response = client.get("/api/workspaces", headers=auth_headers())
    assert list_response.status_code == 200
    assert any(item["name"] == "Client-App" for item in list_response.json()["workspaces"])

    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "Client-App",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    assert session_response.status_code == 200
    assert session_response.json()["cwd"].endswith("/workspaces/_local/Client-App")


def test_workspace_bootstrap_starts_minimal(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)

    workspace_response = client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    assert workspace_response.status_code == 200
    root = Path(workspace_response.json()["path"])

    assert (root / "README.md").is_file()
    assert (root / "agents").is_dir()
    assert (root / "agents" / "README.md").is_file()
    assert {child.name for child in root.iterdir()} == {"README.md", "agents"}


def test_workspace_layout_allows_top_level_markdown_files(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)

    workspace_response = client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    root = Path(workspace_response.json()["path"])
    root.joinpath("TEST_SUMMARY.md").write_text("# Summary\n", encoding="utf-8")

    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "support-suite",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    assert session_response.status_code == 200


def test_workspace_layout_rejects_disallowed_top_level_entries(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)

    workspace_response = client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    root = Path(workspace_response.json()["path"])
    root.joinpath("notes").mkdir()

    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "support-suite",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    assert session_response.status_code == 409
    detail = session_response.json()["detail"]
    assert detail["status"] == "invalid"
    assert detail["recoverable"] is False
    assert detail["invalidEntries"] == ["notes/"]
    assert "agents/" in detail["allowedTopLevelEntries"]
    assert "*.md" in detail["allowedTopLevelEntries"]


def test_workspace_health_reports_recoverable_runtime_artifacts(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    workspace_response = client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    root = Path(workspace_response.json()["path"])
    root.joinpath("guild.json").write_text('{"agent_id":"abc"}', encoding="utf-8")
    artifact_dir = root / "large_tool_results"
    artifact_dir.mkdir()
    artifact_dir.joinpath("chatcmpl-tool-1").write_text("large output", encoding="utf-8")

    health = client.get("/api/workspaces/support-suite/health", headers=auth_headers())
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "invalid"
    assert body["recoverable"] is True
    assert sorted(body["invalidEntries"]) == ["guild.json", "large_tool_results/"]
    assert body["repairAvailable"] is True


def test_workspace_repair_moves_known_legacy_artifacts(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    workspace_response = client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    root = Path(workspace_response.json()["path"])
    root.joinpath("guild.json").write_text('{"agent_id":"abc"}', encoding="utf-8")
    artifact_dir = root / "large_tool_results"
    artifact_dir.mkdir()
    artifact_dir.joinpath("chatcmpl-tool-1").write_text("large output", encoding="utf-8")

    repaired = client.post("/api/workspaces/support-suite/repair", headers=auth_headers())
    assert repaired.status_code == 200
    body = repaired.json()
    assert body["status"] == "valid"
    assert sorted(body["repairedEntries"]) == ["guild.json", "large_tool_results/"]
    assert sorted(child.name for child in root.iterdir()) == ["README.md", "agents"]

    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "support-suite",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    assert session_response.status_code == 200


def test_workspace_apply_rejects_manual_scaffolding_outside_agents_root(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "support-suite",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    session_id = session_response.json()["id"]
    blocked = client.post(
        f"/api/sessions/{session_id}/files/apply",
        headers=auth_headers(),
        json={"path": "notes.txt", "content": "blocked"},
    )
    assert blocked.status_code == 403
    assert "Writes are restricted" in blocked.json()["detail"]


def test_workspace_apply_allows_top_level_markdown_files(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "support-suite",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    session_id = session_response.json()["id"]
    ok = client.post(
        f"/api/sessions/{session_id}/files/apply",
        headers=auth_headers(),
        json={"path": "TEST_SUMMARY.md", "content": "# ok\n"},
    )
    assert ok.status_code == 200
    assert ok.json()["path"] == "TEST_SUMMARY.md"


def test_workspace_apply_allows_agent_code_inside_agents_root(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    client.post("/api/workspaces", headers=auth_headers(), json={"name": "support-suite"})
    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "workspace": "support-suite",
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    session_id = session_response.json()["id"]
    ok = client.post(
        f"/api/sessions/{session_id}/files/apply",
        headers=auth_headers(),
        json={"path": "agents/refunds-agent/index.ts", "content": "export const ok = true;\n"},
    )
    assert ok.status_code == 200
    assert ok.json()["path"] == "agents/refunds-agent/index.ts"


def test_interrupt_decision_route_supports_edit(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    store = get_store()
    store.create_interrupt(
        ApprovalRecord(
            runId="run-1",
            interruptId="intr-1",
            tool="request_checkpoint_review",
            payload={
                "phase": "architecture_review",
                "summary": "Two-agent design is ready.",
                "findings": ["billing and escalation split cleanly"],
                "next_steps": ["scaffold the chosen agents"],
            },
            allowedDecisions=["approve", "edit", "reject"],
        )
    )

    response = client.post(
        "/api/runs/run-1/interrupts/intr-1",
        headers=auth_headers(),
        json={
            "decision": "edit",
            "reason": "Tighten the summary before moving on.",
            "editedAction": {
                "name": "request_checkpoint_review",
                "args": {
                    "phase": "architecture_review",
                    "summary": "Single frontline agent plus escalation path is ready for review.",
                    "findings": ["one LLM agent handles FAQs", "escalation stays explicit"],
                    "next_steps": ["write the shared context", "scaffold the chosen agent"],
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "edited"
    assert body["reason"] == "Tighten the summary before moving on."
    assert body["editedAction"]["name"] == "request_checkpoint_review"
