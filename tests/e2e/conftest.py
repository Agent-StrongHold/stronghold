"""E2E test fixtures — hits the live Docker stack at localhost:8100."""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

STRONGHOLD_URL = os.getenv("STRONGHOLD_URL", "http://localhost:8100")
API_KEY = os.getenv("STRONGHOLD_API_KEY", "sk-stronghold-prod-2026")


def _stack_running() -> bool:
    """True only when the Stronghold stack is reachable on STRONGHOLD_URL.

    Identity is verified via the /health payload's `service` field, not just
    the HTTP status. CI runners can have stale containers from sibling
    projects (e.g. the homelab predecessor) listening on the same port; a
    bare 200 doesn't prove that this PR's stack is the one under test.
    """
    try:
        r = httpx.get(f"{STRONGHOLD_URL}/health", timeout=3)
    except Exception:  # noqa: BLE001
        return False
    if r.status_code != 200:
        return False
    try:
        return r.json().get("service") == "stronghold"
    except ValueError:
        return False


skip_no_stack = pytest.mark.skipif(
    not _stack_running(),
    reason="Stronghold stack not reachable on STRONGHOLD_URL (start with: docker compose up -d)",
)


class RetryClient:
    """Async HTTP client that retries on 429 (rate limited)."""

    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        self._base_url = base_url
        self._headers = headers

    async def _retry(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers, timeout=30.0
        ) as c:
            for attempt in range(4):
                resp = await getattr(c, method)(path, **kwargs)
                if resp.status_code != 429:
                    return resp
                wait = int(resp.headers.get("x-ratelimit-reset", "5"))
                await asyncio.sleep(min(wait, 10))
            return resp  # Return last 429 if all retries exhausted

    async def get(self, path: str, **kw: object) -> httpx.Response:
        return await self._retry("get", path, **kw)

    async def post(self, path: str, **kw: object) -> httpx.Response:
        return await self._retry("post", path, **kw)


@pytest.fixture
def base_url() -> str:
    return STRONGHOLD_URL


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture
def client() -> RetryClient:
    return RetryClient(
        base_url=STRONGHOLD_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
