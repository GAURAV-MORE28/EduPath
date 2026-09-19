"""Backend smoke test: the app boots and the health endpoint responds."""
import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint_reports_status() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "database" in body
    assert "orchestration" in body
