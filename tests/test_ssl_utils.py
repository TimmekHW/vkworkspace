"""Tests for TLS trust: OS store + certifi, plus the Минцифры root behind ``mincifry``."""

from __future__ import annotations

import ssl
from typing import Any

import certifi
import pytest

from vkworkspace import make_ssl_context
from vkworkspace.client import ssl_utils
from vkworkspace.client.bot import Bot, _is_ssl_verification_error
from vkworkspace.client.session import create_session
from vkworkspace.client.ssl_utils import (
    default_ssl_context,
    friendly_ssl_hint,
    normalize_verify,
    resolve_mincifry,
    vendored_ca_pem,
)
from vkworkspace.exceptions import SSLVerificationError
from vkworkspace.types import input_file as input_file_module
from vkworkspace.types.input_file import InputFile

MINCIFRY_CN = "Russian Trusted Root CA"
API = "https://x/bot/v1"


def _subjects(ctx: ssl.SSLContext) -> list[str]:
    return [dict(x[0] for x in c["subject"]).get("commonName", "") for c in ctx.get_ca_certs()]


@pytest.fixture(autouse=True)
def _no_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VKT_MINCIFRY", raising=False)


# ── root cause ──────────────────────────────────────────────────────────


def test_certifi_alone_does_not_trust_mincifry():
    """What httpx uses with ``verify=True`` — the reason Минцифры servers fail."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    assert MINCIFRY_CN not in _subjects(ctx)


# ── the flag ────────────────────────────────────────────────────────────


def test_flag_default_follows_build_constant():
    assert resolve_mincifry(None) is ssl_utils.MINCIFRY_DEFAULT


def test_flag_explicit_wins():
    assert resolve_mincifry(True) is True
    assert resolve_mincifry(False) is False


@pytest.mark.parametrize(("value", "expected"), [("1", True), ("true", True), ("0", False)])
def test_flag_from_env(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool):
    monkeypatch.setenv("VKT_MINCIFRY", value)
    assert resolve_mincifry(None) is expected


def test_context_with_flag_on_trusts_mincifry():
    assert MINCIFRY_CN in _subjects(default_ssl_context(mincifry=True))


def test_flag_controls_vendored_root():
    """Independent of the OS store (which may itself contain the root)."""
    off = make_ssl_context(system_store=False, mincifry=False)
    on = make_ssl_context(system_store=False, mincifry=True)
    assert MINCIFRY_CN not in _subjects(off)
    assert MINCIFRY_CN in _subjects(on)


def test_context_with_flag_off_is_os_store_plus_certifi():
    reference = ssl.create_default_context()
    reference.load_verify_locations(cafile=certifi.where())
    assert sorted(_subjects(default_ssl_context(mincifry=False))) == sorted(_subjects(reference))


def test_context_keeps_public_cas_either_way():
    certifi_count = len(ssl.create_default_context(cafile=certifi.where()).get_ca_certs())
    assert len(default_ssl_context(mincifry=False).get_ca_certs()) >= certifi_count
    assert len(default_ssl_context(mincifry=True).get_ca_certs()) > certifi_count


def test_default_context_is_cached_per_flag():
    assert default_ssl_context(mincifry=True) is default_ssl_context(mincifry=True)
    assert default_ssl_context(mincifry=True) is not default_ssl_context(mincifry=False)


# ── vendored certificate ────────────────────────────────────────────────


def test_vendored_pem_is_the_mincifry_root():
    pem = vendored_ca_pem()
    assert pem.startswith("-----BEGIN CERTIFICATE-----")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cadata=pem)
    (cert,) = ctx.get_ca_certs()
    subject = dict(x[0] for x in cert["subject"])
    assert subject["commonName"] == MINCIFRY_CN
    assert subject["countryName"] == "RU"
    assert cert["subject"] == cert["issuer"]  # self-signed root
    assert "2032" in cert["notAfter"]


def test_vendored_only_context():
    ctx = make_ssl_context(system_store=False, certifi_bundle=False, mincifry=True)
    assert _subjects(ctx) == [MINCIFRY_CN]
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


# ── make_ssl_context / normalize_verify ─────────────────────────────────


def test_make_ssl_context_insecure():
    ctx = make_ssl_context(verify=False)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_make_ssl_context_extra_cafile_on_top_of_defaults():
    ctx = make_ssl_context(cafile=certifi.where(), mincifry=True)
    assert MINCIFRY_CN in _subjects(ctx)


def test_normalize_verify_true_is_default_context():
    assert normalize_verify(True, mincifry=True) is default_ssl_context(mincifry=True)
    assert normalize_verify(True) is default_ssl_context()


@pytest.mark.parametrize("alias", ["mincifry", "MINCIFRY", " Минцифры "])
def test_normalize_verify_alias_string(alias: str):
    assert normalize_verify(alias) is default_ssl_context(mincifry=True)


def test_normalize_verify_false():
    assert normalize_verify(False) is False


def test_normalize_verify_passthrough_context():
    ctx = ssl.create_default_context()
    assert normalize_verify(ctx) is ctx


def test_normalize_verify_path_adds_to_defaults():
    ctx = normalize_verify(certifi.where(), mincifry=True)
    assert isinstance(ctx, ssl.SSLContext)
    assert MINCIFRY_CN in _subjects(ctx)


def test_normalize_verify_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        normalize_verify("/no/such/ca-bundle.pem")


# ── every client the library creates follows the flag ───────────────────


def test_bot_default_verify_is_default_context():
    bot = Bot(token="t", api_url=API)
    assert bot._verify is default_ssl_context()
    assert bot.mincifry is ssl_utils.MINCIFRY_DEFAULT


def test_bot_flag_on():
    bot = Bot(token="t", api_url=API, mincifry=True)
    assert bot.mincifry is True
    assert MINCIFRY_CN in _subjects(bot._verify)  # type: ignore[arg-type]


def test_bot_verify_ssl_alias():
    bot = Bot(token="t", api_url=API, verify_ssl="mincifry")
    assert bot.mincifry is True
    assert bot._verify is default_ssl_context(mincifry=True)


def test_bot_flag_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VKT_MINCIFRY", "1")
    assert Bot(token="t", api_url=API).mincifry is True


def test_bot_accepts_ssl_context():
    ctx = make_ssl_context(verify=False)
    bot = Bot(token="t", api_url=API, verify_ssl=ctx)
    assert bot._verify is ctx


def test_create_session_builds_client():
    import asyncio

    import httpx

    client = create_session(mincifry=True)
    try:
        assert isinstance(client, httpx.AsyncClient)
    finally:
        asyncio.run(client.aclose())


@pytest.mark.asyncio
async def test_from_url_follows_flag(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        content = b"data"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(input_file_module.httpx, "AsyncClient", FakeClient)
    file = await InputFile.from_url("https://example.test/a.bin", mincifry=True)
    assert file.filename == "a.bin"
    assert captured["verify"] is default_ssl_context(mincifry=True)


# ── error reporting ─────────────────────────────────────────────────────


def test_friendly_hint_flag_off_suggests_enabling():
    hint = friendly_ssl_hint("api.vkteams.example", mincifry=False)
    assert "api.vkteams.example" in hint
    assert "mincifry=True" in hint
    assert 'verify_ssl="mincifry"' in hint
    assert "VKT_MINCIFRY=1" in hint


def test_friendly_hint_flag_on_points_elsewhere():
    hint = friendly_ssl_hint("api.vkteams.example", mincifry=True)
    assert "Минцифры" in hint
    assert "mincifry=True" not in hint


def test_is_ssl_verification_error_detects_cause():
    inner = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
    outer = ConnectionError("wrap")
    outer.__cause__ = inner
    assert _is_ssl_verification_error(outer) is True


def test_is_ssl_verification_error_false_for_plain():
    assert _is_ssl_verification_error(ValueError("nope")) is False


def test_ssl_verification_error_is_exportable():
    assert issubclass(SSLVerificationError, Exception)
