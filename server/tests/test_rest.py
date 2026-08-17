from fastapi.testclient import TestClient

from app import create_app


def test_health() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_actions() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/v1/actions")
        assert r.status_code == 200
        data = r.json()
        assert "actions" in data
        assert any(a["name"] == "speak" for a in data["actions"])


def test_protocol_advertises_every_version_it_still_serves() -> None:
    """A robot can check before connecting whether it will be understood."""
    app = create_app()
    with TestClient(app) as client:
        data = client.get("/v1/protocol").json()
        assert data["protocol"] in data["supported_protocols"]
