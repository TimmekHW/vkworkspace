from __future__ import annotations

import httpx


def create_session(
    timeout: float = 90.0,
    connect_timeout: float = 10.0,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        follow_redirects=True,
    )
