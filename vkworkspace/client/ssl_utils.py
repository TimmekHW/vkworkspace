"""TLS trust for VK Teams servers.

``httpx`` with ``verify=True`` loads **only** the ``certifi`` bundle and never
consults the operating-system trust store, so a CA installed into Windows,
RedOS, Fedora or a Docker image stays invisible to it. vkworkspace builds its
own :class:`ssl.SSLContext` instead (:func:`default_ssl_context`):

* the OS trust store — ``ssl.create_default_context()``: Windows user and
  machine stores, Linux OpenSSL default paths, ``SSL_CERT_FILE`` / ``SSL_CERT_DIR``;
* the ``certifi`` bundle — public CAs even in minimal containers;
* the vendored ``Russian Trusted Root CA`` (``vkworkspace/certs/``) — when
  **Минцифры** trust is on: ``Bot(mincifry=True)``, ``verify_ssl="mincifry"``,
  the ``VKT_MINCIFRY=1`` environment variable, or :data:`MINCIFRY_DEFAULT`.

Certificate source: https://www.gosuslugi.ru/crt
"""

from __future__ import annotations

import os
import ssl
from functools import lru_cache
from importlib import resources
from pathlib import Path

MINCIFRY_CERT_URL = "https://www.gosuslugi.ru/crt"

#: Whether Минцифры trust is on when ``mincifry`` is not given and
#: ``VKT_MINCIFRY`` is unset.
MINCIFRY_DEFAULT: bool = False

#: Environment variable that overrides :data:`MINCIFRY_DEFAULT`.
MINCIFRY_ENV = "VKT_MINCIFRY"

#: Values of ``verify_ssl`` that mean "verify, and trust Минцифры".
MINCIFRY_ALIASES = frozenset({"mincifry", "минцифры"})

#: PEM files shipped in ``vkworkspace/certs/``.
VENDORED_CA_FILES: tuple[str, ...] = ("russian_trusted_root_ca.pem",)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def is_mincifry_alias(value: object) -> bool:
    """``True`` for ``verify_ssl="mincifry"`` (case-insensitive, RU/EN spelling)."""
    return isinstance(value, str) and value.strip().lower() in MINCIFRY_ALIASES


def resolve_mincifry(value: bool | None) -> bool:
    """Resolve the ``mincifry`` flag: explicit value → ``VKT_MINCIFRY`` → default."""
    if value is not None:
        return bool(value)
    env = os.environ.get(MINCIFRY_ENV, "").strip().lower()
    if env:
        return env in _TRUE_VALUES
    return MINCIFRY_DEFAULT


def vendored_ca_pem() -> str:
    """PEM text of every CA certificate shipped with the package."""
    certs = resources.files("vkworkspace") / "certs"
    return "\n".join(
        (certs / name).read_text(encoding="utf-8").strip() for name in VENDORED_CA_FILES
    )


def make_ssl_context(
    *,
    cafile: str | Path | None = None,
    capath: str | Path | None = None,
    cadata: str | bytes | None = None,
    use_truststore: bool = False,
    verify: bool = True,
    system_store: bool = True,
    certifi_bundle: bool = True,
    mincifry: bool | None = None,
) -> ssl.SSLContext:
    """Build the :class:`ssl.SSLContext` used by :class:`~vkworkspace.Bot`.

    Args:
        cafile: Extra CA bundle (PEM) to trust in addition to the defaults,
            e.g. a private corporate CA.
        capath: Directory of hashed CA certs (OpenSSL ``c_rehash`` layout).
        cadata: Extra CA certificate(s) as PEM text / DER bytes.
        use_truststore: Verify through the OS trust API via the optional
            ``truststore`` package (``pip install "vkworkspace[ssl]"``) instead
            of ``ssl.create_default_context()``.
        verify: ``False`` builds an **insecure** context (no certificate or
            hostname checks).
        system_store: Load the OS trust store (default ``True``).
        certifi_bundle: Load the ``certifi`` bundle (default ``True``).
        mincifry: Also trust the vendored Минцифры root CA. ``None`` resolves
            via :func:`resolve_mincifry`.

    Examples::

        bot = Bot(token="...", api_url="...", mincifry=True)         # Минцифры servers
        bot = Bot(..., verify_ssl="/certs/corp-ca.pem")               # + private corporate CA
        bot = Bot(..., verify_ssl=make_ssl_context(use_truststore=True, mincifry=True))
    """
    if not verify:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    if use_truststore:
        try:
            import truststore  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "use_truststore=True requires the 'truststore' package: "
                'pip install "vkworkspace[ssl]"'
            ) from exc
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    elif system_store:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

    if certifi_bundle:
        import certifi

        ctx.load_verify_locations(cafile=certifi.where())
    if resolve_mincifry(mincifry):
        ctx.load_verify_locations(cadata=vendored_ca_pem())
    if cafile or capath or cadata:
        ctx.load_verify_locations(
            cafile=str(cafile) if cafile else None,
            capath=str(capath) if capath else None,
            cadata=cadata,
        )
    return ctx


@lru_cache(maxsize=2)
def _default_ssl_context(mincifry: bool) -> ssl.SSLContext:
    return make_ssl_context(mincifry=mincifry)


def default_ssl_context(mincifry: bool | None = None) -> ssl.SSLContext:
    """The shared context behind ``verify_ssl=True`` (one per flag value, per process)."""
    return _default_ssl_context(resolve_mincifry(mincifry))


def normalize_verify(
    verify_ssl: bool | str | Path | ssl.SSLContext,
    *,
    mincifry: bool | None = None,
) -> bool | ssl.SSLContext:
    """Turn the public ``verify_ssl`` value into what httpx accepts.

    * ``ssl.SSLContext`` — passed through;
    * ``True`` — :func:`default_ssl_context` (OS store + certifi, plus the
      Минцифры root when *mincifry* resolves to ``True``);
    * ``"mincifry"`` — same as ``True`` with Минцифры trust on;
    * ``False`` — no verification;
    * ``str`` / :class:`~pathlib.Path` — a PEM bundle trusted **on top of** the
      defaults.
    """
    if isinstance(verify_ssl, ssl.SSLContext):
        return verify_ssl
    if verify_ssl is True:
        return default_ssl_context(mincifry)
    if verify_ssl is False:
        return False
    if is_mincifry_alias(verify_ssl):
        return default_ssl_context(True)
    path = Path(verify_ssl)
    if not path.is_file():
        raise FileNotFoundError(f"verify_ssl points to a CA bundle that does not exist: {path}")
    return make_ssl_context(cafile=path, mincifry=mincifry)


def friendly_ssl_hint(host: str | None = None, *, mincifry: bool | None = None) -> str:
    """Текст ошибки проверки TLS-сертификата с учётом флага ``mincifry``."""
    where = f" ({host})" if host else ""
    head = f"Не удалось проверить TLS-сертификат сервера{where}. "
    if not resolve_mincifry(mincifry):
        return (
            head + "Если сервер стоит за CA Минцифры (Russian Trusted Root CA) — так "
            "устроены on-premise VK Teams в РФ — включите доверие к нему любым способом:\n"
            "  1. Bot(..., mincifry=True)\n"
            '  2. Bot(..., verify_ssl="mincifry")\n'
            f"  3. переменная окружения {MINCIFRY_ENV}=1\n"
            "Если сервер подписан приватным корпоративным CA — передайте его PEM: "
            "Bot(..., verify_ssl='/path/to/corp-ca.pem').\n"
            "  (Крайний случай, небезопасно: verify_ssl=False.)"
        )
    return (
        head + "vkworkspace уже доверяет системному хранилищу, бандлу certifi и корневому "
        "сертификату Минцифры (Russian Trusted Root CA), поэтому причина обычно одна из:\n"
        "  1. Сервер подписан приватным корпоративным CA — передайте его PEM: "
        "Bot(..., verify_ssl='/path/to/corp-ca.pem') "
        "или verify_ssl=make_ssl_context(cafile='/path/to/corp-ca.pem').\n"
        "  2. Сервер не отдаёт промежуточный сертификат (Sub CA) — проверьте цепочку: "
        "openssl s_client -connect host:443 -showcerts. Если так, добавьте Sub CA "
        f"через verify_ssl=... (скачать: {MINCIFRY_CERT_URL}).\n"
        "  3. Между вами и сервером TLS-перехватывающий прокси — доверьте его CA так же, "
        "как в п.1.\n"
        "  (Крайний случай, небезопасно: verify_ssl=False.)"
    )
