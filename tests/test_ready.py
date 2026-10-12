from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_ready_ok():
    client = TestClient(app)
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "dashboard.html" in data["templates"]
    assert "format_vlad" in data["filters"]
    assert "hours_word" in data["filters"]
