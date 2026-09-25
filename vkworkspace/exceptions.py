from __future__ import annotations


class VKWorkspaceError(Exception):
    pass


class VKTeamsAPIError(VKWorkspaceError):
    def __init__(self, method: str, message: str) -> None:
        self.method = method
        self.message = message
        super().__init__(f"API error in {method}: {message}")


class InvalidToken(VKWorkspaceError):
    pass


class SSLVerificationError(VKWorkspaceError):
    """TLS certificate verification failed (commonly the Минцифры CA).

    Raised instead of a bare ``httpx.ConnectError`` so the traceback carries
    a copy‑paste remedy. See :func:`vkworkspace.client.ssl_utils.make_ssl_context`.
    """


class FileDownloadError(VKWorkspaceError):
    """A file download from the VK Teams file host failed."""

    def __init__(self, url: str, message: str) -> None:
        self.url = url
        self.message = message
        super().__init__(f"File download failed: {message}")
