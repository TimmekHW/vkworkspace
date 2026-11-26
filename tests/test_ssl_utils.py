"""TLS trust: what the machine trusts is found, the Минцифры chain is behind ``mincifry``."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Any, Self

import certifi
import httpx2
import pytest
import truststore

from vkworkspace import make_ssl_context
from vkworkspace.client import ssl_utils
from vkworkspace.client.bot import Bot, _is_ssl_verification_error
from vkworkspace.client.session import create_session
from vkworkspace.client.ssl_utils import (
    _is_os_verified,
    _mincifry_in_system_store,
    _system_ca_files,
    default_ssl_context,
    describe_trust,
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
CERTS = Path(ssl_utils.__file__).parent.parent / "certs"
ROOT_PEM = CERTS / "russian_trusted_root_ca.pem"


def _first_certifi_certificate() -> tuple[str, str]:
    """PEM text and common name (or organisation) of some other real CA."""
    text = Path(certifi.where()).read_text("utf-8")
    pem = text[text.index("-----BEGIN CERTIFICATE-----") :]
    pem = pem[: pem.index("-----END CERTIFICATE-----") + len("-----END CERTIFICATE-----")] + "\n"
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cadata=pem)
    subject = dict(x[0] for x in ctx.get_ca_certs()[0]["subject"])
    return pem, subject.get("commonName", "")


OTHER_PEM, OTHER_CN = _first_certifi_certificate()


def _ca_certs(ctx: ssl.SSLContext) -> list[dict[str, Any]]:
    """CA certificates loaded into *ctx* (for a truststore context — the ones added to it)."""
    return getattr(ctx, "_ctx", ctx).get_ca_certs()


def _subjects(ctx: ssl.SSLContext) -> list[str]:
    return [dict(x[0] for x in c["subject"]).get("commonName", "") for c in _ca_certs(ctx)]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in ("VKT_MINCIFRY", "SSL_CERT_FILE", "SSL_CERT_DIR", *ssl_utils.CA_BUNDLE_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def no_system(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine where nothing is installed: an empty OpenSSL store, no known paths."""
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", ())
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_DIRS", ())
    monkeypatch.setattr(
        ssl_utils.httpx2, "create_ssl_context", lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    )
    monkeypatch.setattr(ssl_utils, "_has_no_ca", lambda ctx: not ctx.get_ca_certs())
    monkeypatch.delattr(ssl, "enum_certificates", raising=False)


@pytest.fixture
def os_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine whose operating system verifies certificates itself (Windows, macOS)."""
    monkeypatch.setattr(
        ssl_utils.httpx2,
        "create_ssl_context",
        lambda: truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )


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


# ── the default: httpx2's own trust ─────────────────────────────────────


def test_default_context_is_the_one_httpx2_builds():
    ours = default_ssl_context(mincifry=False)
    theirs = httpx2.create_ssl_context()
    assert type(ours) is type(theirs)
    assert ours.verify_mode == ssl.CERT_REQUIRED
    assert ours.check_hostname is True


def test_default_context_honours_ssl_cert_file(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", ())
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_DIRS", ())
    monkeypatch.setenv("SSL_CERT_FILE", str(ROOT_PEM))
    ctx = make_ssl_context(mincifry=False)
    assert _subjects(ctx) == [MINCIFRY_CN]


def test_os_verified_context_gets_nothing_on_top(os_verified):
    ctx = make_ssl_context(mincifry=False)
    assert isinstance(ctx, truststore.SSLContext)
    assert _is_os_verified(ctx)
    assert _ca_certs(ctx) == []  # no files added: the OS decides


def test_openssl_context_is_not_os_verified(no_system):
    assert not _is_os_verified(make_ssl_context(mincifry=False))


def test_default_context_is_cached_per_flag():
    assert default_ssl_context(mincifry=True) is default_ssl_context(mincifry=True)
    assert default_ssl_context(mincifry=True) is not default_ssl_context(mincifry=False)


# ── certificates found on the machine ───────────────────────────────────


def test_bundle_of_the_distribution_is_found(monkeypatch, tmp_path, no_system):
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", (str(tmp_path / "absent.crt"), str(bundle)))
    assert _system_ca_files() == [str(bundle)]
    assert _subjects(make_ssl_context(mincifry=False)) == [MINCIFRY_CN]


def test_certificate_dropped_into_an_anchors_directory_is_found(monkeypatch, tmp_path, no_system):
    """Copied by a Dockerfile, ``update-ca-certificates`` never ran."""
    anchors = tmp_path / "ca-certificates"
    (anchors / "corp").mkdir(parents=True)
    (anchors / "corp" / "mincifry_root.crt").write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    (anchors / "other.pem").write_text(OTHER_PEM, "utf-8")
    (anchors / "README.txt").write_text("not a certificate", "utf-8")
    (anchors / "broken.crt").write_text("-----BEGIN CERTIFICATE-----\ngarbage\n", "utf-8")
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_DIRS", (str(anchors), str(tmp_path / "absent")))

    names = sorted(os.path.basename(p) for p in _system_ca_files())
    assert names == ["broken.crt", "mincifry_root.crt", "other.pem"]
    ctx = make_ssl_context(mincifry=False)  # the broken file is skipped, not fatal
    assert sorted(_subjects(ctx)) == sorted([MINCIFRY_CN, OTHER_CN])


def test_binary_cer_file_is_found(monkeypatch, tmp_path, no_system):
    """A ``.cer`` in DER form — the system's own bundle builder skips such files."""
    anchors = tmp_path / "ca-certificates"
    anchors.mkdir()
    der = ssl.PEM_cert_to_DER_cert(ROOT_PEM.read_text("utf-8").strip())
    (anchors / "Russian_Trusted_Root_CA.cer").write_bytes(der)
    (anchors / "other.cer").write_text(OTHER_PEM, "utf-8")
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_DIRS", (str(anchors),))
    ctx = make_ssl_context(mincifry=False)
    assert sorted(_subjects(ctx)) == sorted([MINCIFRY_CN, OTHER_CN])
    assert _mincifry_in_system_store() is True


@pytest.mark.parametrize("variable", ["REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"])
def test_bundle_named_by_the_environment_is_found(monkeypatch, tmp_path, no_system, variable):
    bundle = tmp_path / "mounted-ca.pem"
    bundle.write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    monkeypatch.setenv(variable, str(bundle))
    assert _system_ca_files() == [str(bundle)]
    assert _subjects(make_ssl_context(mincifry=False)) == [MINCIFRY_CN]


def test_environment_bundle_is_added_to_an_os_verified_context(monkeypatch, tmp_path, os_verified):
    bundle = tmp_path / "mounted-ca.pem"
    bundle.write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    ctx = make_ssl_context(mincifry=False)
    assert _subjects(ctx) == [MINCIFRY_CN]


def test_one_file_is_loaded_once(monkeypatch, tmp_path, no_system):
    bundle = tmp_path / "ca.crt"
    bundle.write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", (str(bundle),))
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_DIRS", (str(tmp_path),))
    assert _system_ca_files() == [str(bundle)]


def test_system_store_off_searches_nothing(monkeypatch, tmp_path, no_system):
    bundle = tmp_path / "ca.crt"
    bundle.write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", (str(bundle),))
    ctx = make_ssl_context(system_store=False, mincifry=False)
    assert type(ctx) is ssl.SSLContext
    assert _ca_certs(ctx) == []


# ── vendored certificates behind the flag ───────────────────────────────


def test_flag_controls_vendored_chain():
    off = make_ssl_context(system_store=False, mincifry=False)
    on = make_ssl_context(system_store=False, mincifry=True)
    assert _subjects(off) == []
    assert _subjects(on) == [MINCIFRY_CN]
    assert on.verify_mode == ssl.CERT_REQUIRED
    assert on.check_hostname is True


def test_flag_adds_the_chain_to_the_default_context():
    assert MINCIFRY_CN in _subjects(default_ssl_context(mincifry=True))


def test_flag_adds_the_root_to_an_os_verified_context(os_verified):
    ctx = make_ssl_context(mincifry=True)
    assert _subjects(ctx) == [MINCIFRY_CN]


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


# ── is the Минцифры root already on the machine ─────────────────────────


def _root_der() -> bytes:
    return ssl.PEM_cert_to_DER_cert(ROOT_PEM.read_text("utf-8").strip())


def test_mincifry_found_in_the_windows_store(monkeypatch):
    stores: list[str] = []

    def enum_certificates(store: str) -> list[tuple[bytes, str, bool]]:
        stores.append(store)
        return [(b"other", "x509_asn", True), (_root_der(), "x509_asn", True)]

    monkeypatch.setattr(ssl, "enum_certificates", enum_certificates, raising=False)
    assert _mincifry_in_system_store() is True
    assert stores == ["ROOT"]


def test_mincifry_missing_from_the_windows_store(monkeypatch):
    monkeypatch.setattr(ssl, "enum_certificates", lambda store: [], raising=False)
    assert _mincifry_in_system_store() is False


def test_mincifry_found_in_a_linux_bundle(monkeypatch, tmp_path, no_system):
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", (str(bundle),))
    assert _mincifry_in_system_store() is True


def test_mincifry_missing_on_linux(monkeypatch, tmp_path, no_system):
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text(OTHER_PEM, "utf-8")
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", (str(bundle),))
    assert _mincifry_in_system_store() is False


def test_describe_trust_lists_what_was_found(monkeypatch, tmp_path, no_system):
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text(ROOT_PEM.read_text("utf-8"), "utf-8")
    monkeypatch.setattr(ssl_utils, "SYSTEM_CA_FILES", (str(bundle),))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    text = describe_trust(mincifry=False)
    assert f"REQUESTS_CA_BUNDLE={bundle}" in text
    assert f"found: {bundle}" in text
    assert "CA certificates loaded from files: 1" in text
    assert "in the system store: found" in text
    assert "(mincifry): off" in text


def test_describe_trust_on_this_machine():
    text = describe_trust()
    assert "Russian Trusted Root CA" in text


# ── make_ssl_context / normalize_verify ─────────────────────────────────


def test_make_ssl_context_insecure():
    ctx = make_ssl_context(verify=False)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_make_ssl_context_extra_cafile_on_top_of_defaults(tmp_path):
    extra = tmp_path / "corp-ca.pem"
    extra.write_text(OTHER_PEM, "utf-8")
    ctx = make_ssl_context(cafile=extra, mincifry=False)
    assert OTHER_CN in _subjects(ctx)


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


def test_normalize_verify_path_adds_to_defaults(tmp_path):
    extra = tmp_path / "corp-ca.pem"
    extra.write_text(OTHER_PEM, "utf-8")
    ctx = normalize_verify(str(extra), mincifry=True)
    assert isinstance(ctx, ssl.SSLContext)
    assert MINCIFRY_CN in _subjects(ctx)
    assert OTHER_CN in _subjects(ctx)


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


@pytest.mark.asyncio
async def test_create_session_builds_client():
    client = create_session(mincifry=True)
    try:
        assert isinstance(client, httpx2.AsyncClient)
    finally:
        await client.aclose()


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_posix_ca_locations_are_not_searched_on_windows(monkeypatch: pytest.MonkeyPatch):
    """With SSL_CERT_FILE set the context is plain OpenSSL: "/etc/ssl/certs" would be
    a folder on the current drive that any local user may create."""
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    for name in ssl_utils.CA_BUNDLE_ENV:
        monkeypatch.delenv(name, raising=False)
    assert ssl_utils.SYSTEM_CA_FILES == ()
    assert ssl_utils.SYSTEM_CA_DIRS == ()
    assert ssl_utils._system_ca_files() == []


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

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(input_file_module.httpx2, "AsyncClient", FakeClient)
    file = await InputFile.from_url("https://example.test/a.bin", mincifry=True)
    assert file.filename == "a.bin"
    assert captured["verify"] is default_ssl_context(mincifry=True)


# ── error reporting ─────────────────────────────────────────────────────


def test_hint_when_the_machine_does_not_have_the_root(monkeypatch):
    monkeypatch.setattr(ssl_utils, "_mincifry_in_system_store", lambda: False)
    hint = friendly_ssl_hint("api.vkteams.example", mincifry=False)
    assert "api.vkteams.example" in hint
    assert "в системном хранилище не найден" in hint
    assert "mincifry=True" in hint
    assert 'verify_ssl="mincifry"' in hint
    assert "VKT_MINCIFRY=1" in hint
    assert "describe_trust" in hint


def test_hint_when_the_machine_has_the_root(monkeypatch):
    monkeypatch.setattr(ssl_utils, "_mincifry_in_system_store", lambda: True)
    hint = friendly_ssl_hint("api.vkteams.example", mincifry=False)
    assert "в системном хранилище найден" in hint
    assert "промежуточный сертификат" in hint
    assert "corp-ca.pem" in hint
    assert "mincifry=True" not in hint  # the root is there: the switch would change nothing


def test_hint_with_the_flag_on_points_elsewhere(monkeypatch):
    monkeypatch.setattr(ssl_utils, "_mincifry_in_system_store", lambda: False)
    hint = friendly_ssl_hint("api.vkteams.example", mincifry=True)
    assert "Минцифры" in hint
    assert "mincifry=True" not in hint
    assert "corp-ca.pem" in hint


def test_hint_survives_a_failing_lookup(monkeypatch):
    def boom() -> bool:
        raise OSError("store unavailable")

    monkeypatch.setattr(ssl_utils, "_mincifry_in_system_store", boom)
    assert "mincifry=True" in friendly_ssl_hint("h", mincifry=False)


def _verify_failure() -> httpx2.ConnectError:
    try:
        try:
            raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get")
        except ssl.SSLCertVerificationError as inner:
            raise httpx2.ConnectError("verify failed") from inner
    except httpx2.ConnectError as exc:
        return exc


def test_ssl_verification_error_is_detected_in_the_cause_chain():
    assert _is_ssl_verification_error(_verify_failure())
    assert not _is_ssl_verification_error(httpx2.ConnectError("refused"))
    assert not _is_ssl_verification_error(ValueError("nope"))


async def test_verification_failure_raises_the_library_error_with_a_remedy(monkeypatch):
    monkeypatch.setattr(ssl_utils, "_mincifry_in_system_store", lambda: False)

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise _verify_failure()

    bot = Bot(
        token="t", api_url="https://api.vkteams.example/bot/v1", retry_on_5xx=None, mincifry=False
    )
    bot._session = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    with pytest.raises(SSLVerificationError, match=r"api.vkteams.example") as info:
        await bot.send_text("c@x", "hi")
    assert "mincifry=True" in str(info.value)
    await bot.close()
