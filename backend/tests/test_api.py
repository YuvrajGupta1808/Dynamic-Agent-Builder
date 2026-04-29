from pathlib import Path

from fastapi.testclient import TestClient

from agent_workbench.api import create_app
from agent_workbench.core.config import get_settings
from agent_workbench.core.dependencies import get_store, get_workspace_manager


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
    workspace = tmp_path / "workspaces" / "project"
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("# Project\n", encoding="utf-8")
    client = client_for(tmp_path, monkeypatch)

    session_response = client.post(
        "/api/sessions",
        headers=auth_headers(),
        json={
            "cwd": str(workspace),
            "workspaceMode": "local",
            "mode": "accept_everything",
            "model": "mock:deterministic",
        },
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    tree_response = client.get(f"/api/sessions/{session_id}/files/tree", headers=auth_headers())
    assert tree_response.status_code == 200
    assert tree_response.json()["children"][0]["name"] == "README.md"

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
    assert session_response.json()["cwd"].endswith("/workspaces/Client-App")
