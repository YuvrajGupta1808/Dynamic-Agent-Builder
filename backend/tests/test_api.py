from pathlib import Path

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
    assert children == {"README.md"}

    with client.stream(
        "POST",
        f"/api/sessions/{session_id}/runs/stream",
        headers={**auth_headers(), "Content-Type": "application/json"},
        json={"message": "hello"},
    ) as response:
        body = "".join(response.iter_text())
    assert "event: token" in body
    assert "event: done" in body


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

    assert (root / "README.md").read_text(encoding="utf-8").startswith("# support-suite")
    assert not (root / "AGENTS.md").exists()
    assert not (root / "WORKSPACE_CONTEXT.md").exists()
    assert not (root / "skills").exists()
    assert not (root / "agents").exists()


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
