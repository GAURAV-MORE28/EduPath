"""`github_repo_summary` tool tests (design §26.2). Uses `httpx.MockTransport`
so the suite stays fully offline — no live GitHub API calls, matching the
rest of this codebase's "no live network calls in tests" convention.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.profiling.github_client import GitHubClient, InvalidGitHubUrlError, parse_repo_url


def test_parse_repo_url_https():
    assert parse_repo_url("https://github.com/octocat/hello-world") == ("octocat", "hello-world")


def test_parse_repo_url_with_git_suffix_and_trailing_slash():
    assert parse_repo_url("https://github.com/octocat/hello-world.git/") == ("octocat", "hello-world")


def test_parse_repo_url_rejects_non_github_url():
    with pytest.raises(InvalidGitHubUrlError):
        parse_repo_url("https://gitlab.com/octocat/hello-world")


def _readme_payload(text: str) -> dict:
    return {"content": base64.b64encode(text.encode("utf-8")).decode("ascii")}


def _mock_transport(*, repo_status=200, repo_body=None, languages=None, readme_text="", contents=None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/octocat/hello-world":
            return httpx.Response(repo_status, json=repo_body or {})
        if path.endswith("/languages"):
            return httpx.Response(200, json=languages or {})
        if path.endswith("/readme"):
            return httpx.Response(200, json=_readme_payload(readme_text))
        if path.endswith("/contents/"):
            return httpx.Response(200, json=contents or [])
        return httpx.Response(404, json={"message": "not found"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_repo_summary_happy_path():
    transport = _mock_transport(
        repo_body={"full_name": "octocat/hello-world", "description": "A demo repo"},
        languages={"Python": 1000, "Shell": 200},
        readme_text="# Hello World\nThis project does things.",
        contents=[
            {"name": "requirements.txt", "type": "file"},
            {"name": "README.md", "type": "file"},
            {"name": "src", "type": "dir"},
        ],
    )
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
        summary = await GitHubClient(client).repo_summary("https://github.com/octocat/hello-world")

    assert summary.fetched is True
    assert summary.full_name == "octocat/hello-world"
    assert summary.description == "A demo repo"
    assert summary.languages == {"Python": 1000, "Shell": 200}
    assert "Hello World" in summary.readme_excerpt
    assert summary.manifest_files == ["requirements.txt"]
    assert "src" not in summary.top_level_files  # directories are excluded, files only


@pytest.mark.asyncio
async def test_repo_summary_404_degrades_without_raising():
    transport = _mock_transport(repo_status=404)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
        summary = await GitHubClient(client).repo_summary("https://github.com/octocat/hello-world")

    assert summary.fetched is False
    assert summary.degraded_reason == "repository not found"


@pytest.mark.asyncio
async def test_repo_summary_rate_limited_degrades_without_raising():
    transport = _mock_transport(repo_status=403)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
        summary = await GitHubClient(client).repo_summary("https://github.com/octocat/hello-world")

    assert summary.fetched is False
    assert summary.degraded_reason == "rate limited"


@pytest.mark.asyncio
async def test_repo_summary_invalid_url_degrades_without_raising():
    async with httpx.AsyncClient() as client:
        summary = await GitHubClient(client).repo_summary("https://not-github.com/foo/bar")

    assert summary.fetched is False
    assert summary.degraded_reason is not None


@pytest.mark.asyncio
async def test_repo_summary_network_error_degrades_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
        summary = await GitHubClient(client).repo_summary("https://github.com/octocat/hello-world")

    assert summary.fetched is False
    assert "network error" in summary.degraded_reason
