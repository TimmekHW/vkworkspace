from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlparse

import httpx


class InputFile:
    """Wrapper for files to be uploaded via the Bot API.

    Supports multiple input sources::

        # From disk
        InputFile("photo.jpg")
        InputFile(Path("/tmp/report.pdf"))

        # From memory
        InputFile(b"\\x89PNG...", filename="image.png")

        # From open file handle
        InputFile(open("data.csv", "rb"))

        # From base64 string
        InputFile.from_base64("iVBORw0KGgo=", filename="logo.png")

        # From URL (async — downloads the file first)
        file = await InputFile.from_url("https://example.com/photo.jpg")
    """

    def __init__(
        self,
        file: str | Path | BinaryIO | bytes,
        filename: str | None = None,
    ) -> None:
        """Create an InputFile.

        Args:
            file: File source — path (``str`` / ``Path``), raw ``bytes``,
                or an open binary stream (``BinaryIO``).
            filename: Name sent to the server. Auto-detected for disk files;
                **required** for ``bytes`` / ``BinaryIO`` if you want a
                meaningful name in the chat.

        Examples::

            InputFile("report.pdf")                       # from disk
            InputFile(b"raw data", filename="data.bin")   # from memory
            InputFile(open("f.csv", "rb"))                # from stream
        """
        self.file = file
        self.filename = filename

    def read(self) -> tuple[str | None, BinaryIO | bytes]:
        """Open the file and return ``(filename, file_object)``.

        Called internally by ``Bot._file_payload()``. You normally don't
        need to call this yourself.

        Raises:
            FileNotFoundError: If *file* is a path and it doesn't exist.
        """
        if isinstance(self.file, (str, Path)):
            path = Path(self.file).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {path}")
            return self.filename or path.name, open(path, "rb")
        if isinstance(self.file, bytes):
            return self.filename, BytesIO(self.file)
        return self.filename, self.file

    @classmethod
    def from_base64(
        cls,
        data: str,
        filename: str | None = None,
    ) -> InputFile:
        """Create an InputFile from a base64-encoded string.

        Args:
            data: Base64-encoded file content.
            filename: Name for the file on the server.

        Example::

            import base64
            b64 = base64.b64encode(raw_bytes).decode()
            file = InputFile.from_base64(b64, filename="avatar.png")
            await bot.send_file(chat_id, file=file)
        """
        return cls(file=base64.b64decode(data), filename=filename)

    _DEFAULT_MAX_SIZE: int = 50 * 1024 * 1024  # 50 MB

    @classmethod
    async def from_url(
        cls,
        url: str,
        filename: str | None = None,
        timeout: float = 30.0,
        proxy: str | None = None,
        max_size: int | None = None,
    ) -> InputFile:
        """Download a file from *url* and wrap it as an InputFile.

        The file is downloaded into memory and then sent as a normal upload.
        For images (JPG/PNG/WEBP/GIF) VK Teams will display them inline.

        Args:
            url: Full URL to download.
            filename: Override auto-detected filename from URL path.
            timeout: Download timeout in seconds (default 30).
            proxy: HTTP proxy URL. Pass ``bot.proxy`` to reuse the bot's proxy.
            max_size: Maximum allowed file size in bytes (default 50 MB).
                Pass ``0`` to disable the limit.

        Raises:
            httpx.HTTPStatusError: If the download fails (4xx/5xx).
            ValueError: If the file exceeds *max_size*.

        Example::

            # Photo from the internet
            photo = await InputFile.from_url("https://http.cat/200.jpg")
            await bot.send_file(chat_id, file=photo, caption="200 OK")

            # Through corporate proxy
            file = await InputFile.from_url(url, proxy=bot.proxy)
        """
        limit = cls._DEFAULT_MAX_SIZE if max_size is None else max_size

        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, proxy=proxy,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        if limit and len(resp.content) > limit:
            size_mb = len(resp.content) / 1024 / 1024
            raise ValueError(
                f"Downloaded file is too large: {size_mb:.1f} MB "
                f"(limit {limit / 1024 / 1024:.0f} MB)"
            )

        if filename is None:
            filename = _filename_from_url(url)

        return cls(file=resp.content, filename=filename)


def _filename_from_url(url: str) -> str | None:
    """Extract a filename from the URL path, e.g. ``photo.jpg``."""
    path = unquote(urlparse(url).path)
    name = Path(path).name
    return name if name and "." in name else None
