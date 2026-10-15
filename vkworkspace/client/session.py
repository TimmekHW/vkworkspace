from __future__ import annotations

import ssl
from pathlib import Path

import httpx

from vkworkspace.client.ssl_utils import normalize_verify


def create_session(
    timeout: float = 90.0,
    connect_timeout: float = 10.0,
    proxy: str | None = None,
    verify: bool | str | Path | ssl.SSLContext = True,
    mincifry: bool | None = None,
) -> httpx.AsyncClient:
    """Standalone httpx client with the same TLS trust as :class:`~vkworkspace.Bot`."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        follow_redirects=True,
        proxy=proxy,
        verify=normalize_verify(verify, mincifry=mincifry),
    )
