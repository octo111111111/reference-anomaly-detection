from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from reference_anomaly_detection.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "reference-anomaly-detection"
    assert "retraction_index" in body


def test_reference_check_rejects_missing_file(client: TestClient) -> None:
    response = client.post("/v1/reference-check")
    assert response.status_code == 422
