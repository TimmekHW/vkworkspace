from __future__ import annotations


class VKWorkspaceError(Exception):
    pass


class VKTeamsAPIError(VKWorkspaceError):
    def __init__(self, method: str, message: str) -> None:
        self.method = method
        self.message = message
        super().__init__(f"API error in {method}: {message}")


class VKTeamsNetworkError(VKWorkspaceError):
    """The request got no HTTP response: connection, proxy, TLS or timeout failure.

    Attributes:
        method: Bot API method, e.g. ``"messages/sendText"``.
        message: The HTTP client error by type and text: ``"ReadTimeout"``,
            ``"ConnectError: ..."``.
        original: The ``httpx2`` exception (also ``__cause__``).
    """

    def __init__(self, method: str, message: str, original: BaseException | None = None) -> None:
        self.method = method
        self.message = message
        self.original = original
        super().__init__(f"Network error in {method}: {message}")


class VKTeamsHTTPError(VKWorkspaceError):
    """The server answered with an HTTP error status (4xx / 5xx).

    Attributes:
        method: Bot API method.
        status_code: HTTP status.
        message: ``"HTTP 504"``.
        original: The ``httpx2.HTTPStatusError`` (also ``__cause__``); its
            ``response`` holds the body and headers.
    """

    def __init__(
        self, method: str, status_code: int, original: BaseException | None = None
    ) -> None:
        self.method = method
        self.status_code = status_code
        self.message = f"HTTP {status_code}"
        self.original = original
        super().__init__(f"HTTP error in {method}: {self.message}")


class VKTeamsOutcomeUnknown(VKWorkspaceError):
    """The request may have reached the server, and no answer came.

    Raised by the methods that create something on every call — ``send_text``,
    ``send_text_with_deeplink``, ``send_file``, ``send_voice``, ``create_chat``,
    ``threads_add`` — after a read timeout, a dropped connection, HTTP 504,
    ``"Request timed out"`` or the deadline of the call. The library does not
    repeat such a call, because a repeat could create a duplicate: the message
    may or may not have been delivered.

    The exception is also the error it came from — a
    :class:`VKTeamsNetworkError`, a :class:`VKTeamsHTTPError` (HTTP 504) or a
    :class:`VKTeamsAPIError` (``"Request timed out"``) — so code that catches
    those keeps working::

        try:
            await bot.send_text(chat_id, text)
        except VKTeamsOutcomeUnknown:
            ...  # check the chat before sending again

    Attributes:
        method: Bot API method, e.g. ``"messages/sendText"``.
        message: What happened: ``"ReadTimeout"``, ``"HTTP 504"``,
            ``"Request timed out"``.
        original: The ``httpx2`` exception (also ``__cause__``); ``None`` when
            the server itself answered ``"Request timed out"``.
    """

    method: str
    message: str
    original: BaseException | None

    def __str__(self) -> str:
        return (
            f"{super().__str__()} — the outcome is unknown: "
            "the request may have reached the server, it was not repeated"
        )

    @staticmethod
    def _of(error: VKWorkspaceError) -> VKTeamsOutcomeUnknown:
        """*error* as the same error, marked as one whose outcome is unknown."""
        if isinstance(error, VKTeamsHTTPError):
            return _HTTPOutcomeUnknown(error.method, error.status_code, error.original)
        if isinstance(error, VKTeamsAPIError):
            return _APIOutcomeUnknown(error.method, error.message)
        if isinstance(error, VKTeamsNetworkError):
            return _NetworkOutcomeUnknown(error.method, error.message, error.original)
        raise TypeError(f"{type(error).__name__} cannot have an unknown outcome")


class _NetworkOutcomeUnknown(VKTeamsOutcomeUnknown, VKTeamsNetworkError):
    """No answer after the request was sent: read timeout, dropped connection, deadline."""


class _HTTPOutcomeUnknown(VKTeamsOutcomeUnknown, VKTeamsHTTPError):
    """HTTP 504: the gateway stopped waiting for the server."""


class _APIOutcomeUnknown(VKTeamsOutcomeUnknown, VKTeamsAPIError):
    """The server answered ``"Request timed out"``."""

    def __init__(self, method: str, message: str) -> None:
        super().__init__(method, message)
        self.original = None


class InvalidToken(VKWorkspaceError):
    pass


class SSLVerificationError(VKWorkspaceError):
    """TLS certificate verification failed (commonly the Минцифры CA).

    Raised instead of a bare ``ConnectError`` so the traceback carries
    a copy‑paste remedy. See :func:`vkworkspace.client.ssl_utils.make_ssl_context`.
    """


class FileDownloadError(VKWorkspaceError):
    """A file download from the VK Teams file host failed."""

    def __init__(self, url: str, message: str) -> None:
        self.url = url
        self.message = message
        super().__init__(f"File download failed: {message}")
