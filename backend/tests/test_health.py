from fastapi.testclient import TestClient

from claude_coach.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"]
    assert isinstance(data["db_ok"], bool)
