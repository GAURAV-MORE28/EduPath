"""`github_repo_summary` tool (design §26.2): repo languages, README excerpt,
top-level file tree/manifest filenames via the GitHub REST API. Read-only,
no side effects, no deep code analysis (explicitly out of scope this phase —
this is metadata only, the E2-tier evidence source design §22.4 calls
"Confirmed by GitHub artifact (languages, dependency manifests,
README/tree)").

`httpx.AsyncClient` is injected (never constructed with a bare default
inside a method) so tests can supply an `httpx.MockTransport` instead of
making live network calls — the same pattern the rest of this codebase uses
to keep the test suite offline (no live network calls in `data/scripts/validate_dataset.py`,
no live provider calls in the LLM/Embedding/VLM Gateways).
"""
from __future__ import annotations

import base64
import re

import httpx

from app.config import get_settings
from app.schemas.profiling import GitHubRepoSummary

_REPO_URL_RE = re.compile(r"github\.com[:/]+(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$")

_MANIFEST_FILENAMES = frozenset(
    {
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "setup.py",
        "package.json",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "Gemfile",
        "composer.json",
        "Dockerfile",
    }
)

README_EXCERPT_CHARS = 1500


class InvalidGitHubUrlError(ValueError):
    pass


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    match = _REPO_URL_RE.search(repo_url.strip())
    if not match:
        raise InvalidGitHubUrlError(f"Not a recognizable GitHub repo URL: {repo_url!r}")
    return match.group("owner"), match.group("repo")


class GitHubClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client
        settings = get_settings()
        self._headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if settings.github_token:
            self._headers["Authorization"] = f"Bearer {settings.github_token}"

    async def repo_summary(self, repo_url: str) -> GitHubRepoSummary:
        try:
            owner, repo = parse_repo_url(repo_url)
        except InvalidGitHubUrlError as exc:
            return GitHubRepoSummary(repo_url=repo_url, full_name="", fetched=False, degraded_reason=str(exc))

        base = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            repo_resp = await self._client.get(base, headers=self._headers)
        except httpx.HTTPError as exc:
            return GitHubRepoSummary(repo_url=repo_url, full_name="", fetched=False, degraded_reason=f"network error: {exc}")

        if repo_resp.status_code == 404:
            return GitHubRepoSummary(repo_url=repo_url, full_name="", fetched=False, degraded_reason="repository not found")
        if repo_resp.status_code == 403:
            return GitHubRepoSummary(repo_url=repo_url, full_name="", fetched=False, degraded_reason="rate limited")
        if repo_resp.status_code != 200:
            return GitHubRepoSummary(
                repo_url=repo_url, full_name="", fetched=False, degraded_reason=f"unexpected status {repo_resp.status_code}"
            )

        repo_json = repo_resp.json()
        full_name = repo_json.get("full_name", f"{owner}/{repo}")
        description = repo_json.get("description") or ""

        languages = await self._get_json(f"{base}/languages", default={})
        readme_excerpt = await self._get_readme(base)
        top_level_files = await self._get_top_level_files(base)
        manifest_files = [f for f in top_level_files if f in _MANIFEST_FILENAMES]

        return GitHubRepoSummary(
            repo_url=repo_url,
            full_name=full_name,
            description=description,
            languages=languages,
            readme_excerpt=readme_excerpt,
            manifest_files=manifest_files,
            top_level_files=top_level_files,
            fetched=True,
        )

    async def _get_json(self, url: str, default):
        try:
            resp = await self._client.get(url, headers=self._headers)
        except httpx.HTTPError:
            return default
        if resp.status_code != 200:
            return default
        return resp.json()

    async def _get_readme(self, base: str) -> str:
        try:
            resp = await self._client.get(f"{base}/readme", headers=self._headers)
        except httpx.HTTPError:
            return ""
        if resp.status_code != 200:
            return ""
        payload = resp.json()
        content_b64 = payload.get("content", "")
        try:
            text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - malformed base64 from an unexpected API shape, degrade to empty
            return ""
        return text[:README_EXCERPT_CHARS]

    async def _get_top_level_files(self, base: str) -> list[str]:
        listing = await self._get_json(f"{base}/contents/", default=[])
        if not isinstance(listing, list):
            return []
        return [entry["name"] for entry in listing if isinstance(entry, dict) and entry.get("type") == "file"]
