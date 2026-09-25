"""TLS helpers for VK Teams servers behind the Минцифры (Russian Trusted) CA.

Stock ``certifi`` does not trust the Минцифры root, so ``https://<company>.teams…``
fails with ``SSLCertVerificationError`` until it is trusted. Trust it via any of:

* a PEM file — ``verify_ssl="/certs/russian.pem"``,
* a ready :class:`ssl.SSLContext` — ``verify_ssl=make_ssl_context(...)``,
* the OS trust store — ``make_ssl_context(use_truststore=True)``.

Certificate: https://www.gosuslugi.ru/crt
"""

from __future__ import annotations

import ssl
from pathlib import Path

MINCIFRY_CERT_URL = "https://www.gosuslugi.ru/crt"


def make_ssl_context(
    *,
    cafile: str | Path | None = None,
    capath: str | Path | None = None,
    cadata: str | bytes | None = None,
    use_truststore: bool = False,
    verify: bool = True,
) -> ssl.SSLContext:
    """Build an :class:`ssl.SSLContext` for :class:`~vkworkspace.Bot`.

    This is the recommended way to trust the Минцифры (or any private) CA
    without disabling verification wholesale.

    Args:
        cafile: Path to an extra CA bundle in PEM form (e.g. the Минцифры
            root+sub chain). Added **on top of** the system defaults, so
            public certs keep working too.
        capath: Directory of hashed CA certs (OpenSSL ``c_rehash`` layout).
        cadata: CA certificate(s) as an in‑memory PEM string / DER bytes.
        use_truststore: Load trust roots from the **operating system** store
            (Windows cert store / macOS keychain / Linux ``ca-certificates``)
            via the optional ``truststore`` package. Perfect when the
            Минцифры cert is installed machine‑wide. Requires
            ``pip install truststore`` (or ``pip install "vkworkspace[ssl]"``).
        verify: ``False`` builds an **insecure** context (no cert/hostname
            checks). Last resort only — prefer trusting the CA.

    Returns:
        A configured :class:`ssl.SSLContext` to pass as ``verify_ssl``.

    Examples::

        # Trust the Минцифры chain from a file, keep public CAs working
        ctx = make_ssl_context(cafile="/certs/russian_trusted.pem")
        bot = Bot(token="...", api_url="...", verify_ssl=ctx)

        # Trust whatever the OS trusts (cert installed system-wide)
        ctx = make_ssl_context(use_truststore=True)
        bot = Bot(token="...", api_url="...", verify_ssl=ctx)
    """
    if use_truststore:
        try:
            import truststore  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "use_truststore=True requires the 'truststore' package. "
                'Install it with: pip install "vkworkspace[ssl]"  '
                "(or: pip install truststore)"
            ) from exc
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    else:
        ctx = ssl.create_default_context()

    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    if cafile or capath or cadata:
        ctx.load_verify_locations(
            cafile=str(cafile) if cafile else None,
            capath=str(capath) if capath else None,
            cadata=cadata,
        )
    return ctx


def normalize_verify(
    verify_ssl: bool | str | Path | ssl.SSLContext,
) -> bool | ssl.SSLContext:
    """Turn the public ``verify_ssl`` value into something httpx accepts.

    Accepts, in order of preference:

    * ``ssl.SSLContext`` — passed straight through;
    * ``str`` / :class:`pathlib.Path` — treated as a PEM CA‑bundle path and
      wrapped in a context (httpx 0.28 deprecated bare path strings);
    * ``bool`` — ``True`` = default system trust, ``False`` = no verification.
    """
    if isinstance(verify_ssl, ssl.SSLContext):
        return verify_ssl
    if isinstance(verify_ssl, (str, Path)):
        path = Path(verify_ssl)
        if not path.is_file():
            raise FileNotFoundError(f"verify_ssl points to a CA bundle that does not exist: {path}")
        return make_ssl_context(cafile=path)
    return verify_ssl


def friendly_ssl_hint(host: str | None = None) -> str:
    """Текст ошибки проверки TLS-сертификата (обычно — CA Минцифры)."""
    where = f" ({host})" if host else ""
    return (
        f"Не удалось проверить TLS-сертификат сервера{where}. Скорее всего сервер "
        "VK Teams стоит за корневым CA Минцифры («Russian Trusted Root/Sub CA»), "
        "которому стандартный набор сертификатов не доверяет.\n"
        "Как починить (любой из способов):\n"
        f"  1. Установить сертификат Минцифры (root+sub) в хранилище ОС "
        f"({MINCIFRY_CERT_URL}), затем: verify_ssl=make_ssl_context(use_truststore=True).\n"
        "  2. Указать путь к PEM-бандлу: Bot(..., verify_ssl='/path/to/russian_trusted.pem').\n"
        "  3. Или передать готовый контекст: "
        "verify_ssl=make_ssl_context(cafile='/path/to/russian_trusted.pem').\n"
        "  (Крайний случай, небезопасно: verify_ssl=False.)"
    )
