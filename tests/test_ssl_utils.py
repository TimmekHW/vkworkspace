"""Tests for TLS helpers (Минцифры / private‑CA support)."""

from __future__ import annotations

import ssl

import pytest

from vkworkspace import make_ssl_context
from vkworkspace.client.bot import Bot, _is_ssl_verification_error
from vkworkspace.client.ssl_utils import friendly_ssl_hint, normalize_verify
from vkworkspace.exceptions import SSLVerificationError


def test_make_ssl_context_default():
    ctx = make_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_make_ssl_context_insecure():
    ctx = make_ssl_context(verify=False)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_make_ssl_context_with_cafile(tmp_path):
    # A syntactically valid (self‑signed‑looking) PEM is not required here —
    # load_verify_locations only needs a parseable file; use certifi's bundle.
    import certifi

    ctx = make_ssl_context(cafile=certifi.where())
    assert isinstance(ctx, ssl.SSLContext)


def test_normalize_verify_passthrough_context():
    ctx = ssl.create_default_context()
    assert normalize_verify(ctx) is ctx


def test_normalize_verify_bool():
    assert normalize_verify(True) is True
    assert normalize_verify(False) is False


def test_normalize_verify_path(tmp_path):
    import certifi

    result = normalize_verify(certifi.where())
    assert isinstance(result, ssl.SSLContext)


def test_normalize_verify_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        normalize_verify("/no/such/ca-bundle.pem")


def test_bot_accepts_ssl_context():
    ctx = make_ssl_context(verify=False)
    bot = Bot(token="t", api_url="https://x/bot/v1", verify_ssl=ctx)
    assert bot._verify is ctx


def test_friendly_hint_mentions_mincifry():
    hint = friendly_ssl_hint("api.teams.sovcombank.ru")
    assert "Минцифры" in hint
    assert "sovcombank.ru" in hint


def test_is_ssl_verification_error_detects_cause():
    inner = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
    outer = ConnectionError("wrap")
    outer.__cause__ = inner
    assert _is_ssl_verification_error(outer) is True


def test_is_ssl_verification_error_false_for_plain():
    assert _is_ssl_verification_error(ValueError("nope")) is False


def test_ssl_verification_error_is_exportable():
    assert issubclass(SSLVerificationError, Exception)
