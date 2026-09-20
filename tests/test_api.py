import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"

def test_auth_status_endpoint():
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert "authenticated" in data

def test_scanner_status_endpoint():
    response = client.get("/api/scanner/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "stage" in data

def test_scanner_results_endpoint():
    response = client.get("/api/scanner/results")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "count" in data

def test_scanner_run_requires_auth(monkeypatch):
    from backend import main
    monkeypatch.setattr(main, "get_active_access_token", lambda db: None)
    response = client.post("/api/scanner/run")
    assert response.status_code == 401
