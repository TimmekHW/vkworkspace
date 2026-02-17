"""Tests for InputFile: disk, bytes, base64, URL."""

import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from vkworkspace.types.input_file import InputFile, _filename_from_url

# ── Existing behaviour ───────────────────────────────────────────────


class TestInputFileBasic:
    def test_from_bytes(self):
        data = b"\x89PNG fake image"
        f = InputFile(data, filename="test.png")
        name, fp = f.read()
        assert name == "test.png"
        assert fp.read() == data

    def test_from_bytes_no_filename(self):
        f = InputFile(b"data")
        name, fp = f.read()
        assert name is None
        assert fp.read() == b"data"

    def test_from_path(self, tmp_path: Path):
        p = tmp_path / "hello.txt"
        p.write_bytes(b"hello")
        f = InputFile(str(p))
        name, fp = f.read()
        assert name == "hello.txt"
        assert fp.read() == b"hello"
        fp.close()

    def test_from_path_object(self, tmp_path: Path):
        p = tmp_path / "data.bin"
        p.write_bytes(b"\x00\x01")
        f = InputFile(p, filename="custom.bin")
        name, fp = f.read()
        assert name == "custom.bin"
        fp.close()

    def test_file_not_found(self):
        f = InputFile("/nonexistent/path.jpg")
        with pytest.raises(FileNotFoundError):
            f.read()

    def test_from_binary_io(self):
        bio = BytesIO(b"stream data")
        f = InputFile(bio, filename="stream.dat")
        name, fp = f.read()
        assert name == "stream.dat"
        assert fp is bio


# ── from_base64 ──────────────────────────────────────────────────────


class TestFromBase64:
    def test_basic(self):
        original = b"hello world"
        b64 = base64.b64encode(original).decode()
        f = InputFile.from_base64(b64, filename="hello.txt")
        name, fp = f.read()
        assert name == "hello.txt"
        assert fp.read() == original

    def test_no_filename(self):
        f = InputFile.from_base64(base64.b64encode(b"x").decode())
        name, _ = f.read()
        assert name is None

    def test_png_roundtrip(self):
        # 1x1 red PNG
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
            "nGP4z8BQDwAEgAF/pooBPQAAAABJRU5ErkJggg=="
        )
        f = InputFile.from_base64(png_b64, filename="pixel.png")
        name, fp = f.read()
        data = fp.read()
        assert name == "pixel.png"
        assert data[:4] == b"\x89PNG"


# ── from_url ─────────────────────────────────────────────────────────


class TestFromUrl:
    @pytest.mark.asyncio
    async def test_downloads_and_wraps(self):
        fake_resp = httpx.Response(200, content=b"image bytes",
                                   request=httpx.Request("GET", "https://example.com/photo.jpg"))

        with patch("vkworkspace.types.input_file.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            f = await InputFile.from_url("https://example.com/photo.jpg")

        name, fp = f.read()
        assert name == "photo.jpg"
        assert fp.read() == b"image bytes"

    @pytest.mark.asyncio
    async def test_custom_filename_overrides(self):
        fake_resp = httpx.Response(200, content=b"data",
                                   request=httpx.Request("GET", "https://example.com/photo.jpg"))

        with patch("vkworkspace.types.input_file.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            f = await InputFile.from_url(
                "https://example.com/photo.jpg",
                filename="custom.png",
            )

        name, _ = f.read()
        assert name == "custom.png"

    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        fake_resp = httpx.Response(404, request=httpx.Request("GET", "https://x.com/missing.jpg"))

        with patch("vkworkspace.types.input_file.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=fake_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await InputFile.from_url("https://x.com/missing.jpg")


# ── _filename_from_url ───────────────────────────────────────────────


class TestFilenameFromUrl:
    def test_simple(self):
        assert _filename_from_url("https://example.com/photo.jpg") == "photo.jpg"

    def test_with_query(self):
        assert _filename_from_url("https://cdn.com/img/logo.png?v=2") == "logo.png"

    def test_encoded(self):
        assert _filename_from_url("https://x.com/%D1%84%D0%BE%D1%82%D0%BE.jpg") == "фото.jpg"

    def test_no_extension_returns_none(self):
        assert _filename_from_url("https://example.com/download") is None

    def test_root_returns_none(self):
        assert _filename_from_url("https://example.com/") is None

    def test_nested_path(self):
        assert _filename_from_url("https://cdn.com/a/b/c/report.pdf") == "report.pdf"
