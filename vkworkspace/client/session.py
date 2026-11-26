from __future__ import annotations

import ssl
from pathlib import Path

import httpx2

from vkworkspace.client.ssl_utils import normalize_verify


def create_session(
    timeout: float = 90.0,
    connect_timeout: float = 10.0,
    proxy: str | None = None,
    verify: bool | str | Path | ssl.SSLContext = True,
    mincifry: bool | None = None,
) -> httpx2.AsyncClient:
    """Standalone httpx2 client with the same TLS trust as :class:`~vkworkspace.Bot`."""
    return httpx2.AsyncClient(
        timeout=httpx2.Timeout(timeout, connect=connect_timeout),
        follow_redirects=True,
        proxy=proxy,
        verify=normalize_verify(verify, mincifry=mincifry),
    )
