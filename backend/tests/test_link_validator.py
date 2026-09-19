"""Link validation tests (`app/retrieval/link_validator.py`, design §15.2's
"link validation job"). Uses `httpx.MockTransport` so the suite stays fully
offline -- same convention as `tests/test_github_client.py`.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.retrieval.link_validator import (
    LINK_STATUS_BROKEN,
    LINK_STATUS_OK,
    LINK_STATUS_REDIRECTED,
    check_url,
    validate_resources,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_ok_link_returns_ok():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with _client(handler) as client:
        status, detail = await check_url(client, "https://example.org/ok")
    assert status == LINK_STATUS_OK
    assert "200" in detail


@pytest.mark.asyncio
async def test_redirected_link_is_flagged_redirected_not_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "https://example.org/new"})
        return httpx.Response(200)

    async with _client(handler) as client:
        status, _ = await check_url(client, "https://example.org/old")
    assert status == LINK_STATUS_REDIRECTED


@pytest.mark.asyncio
async def test_404_is_broken():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client(handler) as client:
        status, detail = await check_url(client, "https://example.org/missing")
    assert status == LINK_STATUS_BROKEN
    assert "404" in detail


@pytest.mark.asyncio
async def test_network_error_is_broken():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _client(handler) as client:
        status, detail = await check_url(client, "https://example.org/down")
    assert status == LINK_STATUS_BROKEN
    assert "ConnectError" in detail


@pytest.mark.asyncio
async def test_head_rejected_falls_back_to_get():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200)

    async with _client(handler) as client:
        status, _ = await check_url(client, "https://example.org/head-not-allowed")
    assert status == LINK_STATUS_OK


@pytest.mark.asyncio
async def test_head_and_get_both_fail_is_broken():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with _client(handler) as client:
        status, _ = await check_url(client, "https://example.org/always-down")
    assert status == LINK_STATUS_BROKEN


@pytest.mark.asyncio
async def test_validate_resources_checks_every_pair_and_stamps_checked_at():
    def handler(request: httpx.Request) -> httpx.Response:
        if "broken" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200)

    as_of = date(2026, 3, 1)
    async with _client(handler) as client:
        results = await validate_resources(
            [("res.a", "https://example.org/ok-a"), ("res.b", "https://example.org/broken-b")],
            client,
            as_of=as_of,
        )

    by_id = {r.resource_id: r for r in results}
    assert by_id["res.a"].status == LINK_STATUS_OK
    assert by_id["res.b"].status == LINK_STATUS_BROKEN
    assert all(r.checked_at == as_of for r in results)


@pytest.mark.asyncio
async def test_validate_resources_empty_input():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    async with _client(handler) as client:
        assert await validate_resources([], client) == []
