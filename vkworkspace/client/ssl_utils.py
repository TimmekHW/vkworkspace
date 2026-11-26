"""TLS trust for VK Teams servers.

With ``verify_ssl=True`` the bot trusts what the machine it runs on trusts. The
certificates are searched for, not configured:

1. **httpx2's own trust** (:func:`httpx2.create_ssl_context`): the
   ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` environment variables; on Windows and
   macOS the operating system verifies the certificate itself — the machine
   store, the current user's store and group policy alike; on Linux the OpenSSL
   system store.
2. **Places a Linux image or a Kubernetes pod keeps CA certificates in**, which
   OpenSSL does not read on its own: the bundle of another distribution
   (:data:`SYSTEM_CA_FILES`), certificates copied into an anchors directory
   without running ``update-ca-certificates`` / ``update-ca-trust`` or mounted
   into ``/etc/ssl/certs`` without a hash link (:data:`SYSTEM_CA_DIRS`), and the
   bundles named by ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``.

A CA installed anywhere above — the **Минцифры** root baked into a Linux image,
in the Windows store, in a bundle mounted into a pod — is trusted with no
settings. For machines that do not have it, the root ships with the package
(``vkworkspace/certs/``) behind one switch: ``Bot(mincifry=True)``,
``verify_ssl="mincifry"``, ``VKT_MINCIFRY=1``, or :data:`MINCIFRY_DEFAULT`.

:func:`describe_trust` prints what was found.

Certificate source: https://www.gosuslugi.ru/crt
"""

from __future__ import annotations

import hashlib
import logging
import os
import ssl
from functools import lru_cache
from importlib import resources
from pathlib import Path

import httpx2

logger = logging.getLogger(__name__)

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

#: CA bundles of Linux / BSD distributions. OpenSSL reads only the one its
#: build points at; a Python built elsewhere (uv, pyenv, conda) may point nowhere.
#: Empty on Windows, where such a path would resolve against the current drive.
SYSTEM_CA_FILES: tuple[str, ...] = (
    ()
    if os.name == "nt"
    else (
        "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Alpine, Arch
        "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL, Fedora, RedOS, CentOS
        "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # RHEL family
        "/etc/ssl/ca-bundle.pem",  # openSUSE
        "/etc/ssl/cert.pem",  # Alpine, BSD
        "/etc/pki/tls/cert.pem",
        "/usr/local/share/certs/ca-root-nss.crt",  # FreeBSD
    )
)

#: Directories an administrator, a Dockerfile or a Kubernetes mount puts extra
#: CA certificates into. A certificate dropped here is trusted even if the
#: system bundle was not rebuilt afterwards. Empty on Windows.
SYSTEM_CA_DIRS: tuple[str, ...] = (
    ()
    if os.name == "nt"
    else (
        "/usr/local/share/ca-certificates",  # Debian, Ubuntu, Alpine
        "/etc/ssl/certs",  # files mounted without a hash link
        "/etc/pki/ca-trust/source/anchors",  # RHEL family
        "/usr/share/pki/ca-trust-source/anchors",
        "/etc/pki/trust/anchors",  # openSUSE
        "/usr/share/pki/trust/anchors",
        "/etc/ca-certificates/trust-source/anchors",  # Arch
    )
)

#: Environment variables that name a CA bundle file. ``SSL_CERT_FILE`` and
#: ``SSL_CERT_DIR`` are read by httpx2 itself.
CA_BUNDLE_ENV: tuple[str, ...] = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")

_CA_FILE_SUFFIXES = (".crt", ".pem", ".cer")
_MAX_CA_FILES = 2000
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


def _fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


@lru_cache(maxsize=1)
def _mincifry_root_fingerprint() -> str:
    pem = (resources.files("vkworkspace") / "certs" / VENDORED_CA_FILES[0]).read_text("utf-8")
    return _fingerprint(ssl.PEM_cert_to_DER_cert(pem.strip()))


def _is_os_verified(ctx: ssl.SSLContext) -> bool:
    """``True`` if *ctx* hands verification to the operating system (``truststore``)."""
    return type(ctx).__module__.partition(".")[0] == "truststore"


def _system_ca_files() -> list[str]:
    """CA certificate files found on this machine outside httpx2's own search.

    Existing files from :data:`CA_BUNDLE_ENV`, :data:`SYSTEM_CA_FILES` and
    :data:`SYSTEM_CA_DIRS`, each real file once.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        real = os.path.realpath(path)
        if real not in seen and os.path.isfile(real) and len(found) < _MAX_CA_FILES:
            seen.add(real)
            found.append(path)

    for name in CA_BUNDLE_ENV:
        if value := os.environ.get(name):
            add(value)
    for path in SYSTEM_CA_FILES:
        add(path)
    for directory in SYSTEM_CA_DIRS:
        if not os.path.isdir(directory):
            continue
        for root, _dirs, names in os.walk(directory):
            for name in sorted(names):
                if name.lower().endswith(_CA_FILE_SUFFIXES):
                    add(os.path.join(root, name))
    return found


def _load_files(ctx: ssl.SSLContext, paths: list[str]) -> list[str]:
    """Add each readable CA file to *ctx*; return the ones that loaded.

    A file is PEM text or one binary (DER) certificate — ``.cer`` files are
    often the latter.
    """
    loaded = []
    for path in paths:
        try:
            try:
                ctx.load_verify_locations(cafile=path)
            except ssl.SSLError:
                ctx.load_verify_locations(cadata=Path(path).read_bytes())
        except (ssl.SSLError, OSError, ValueError) as exc:
            logger.debug("TLS trust: %s skipped (%s)", path, exc)
        else:
            loaded.append(path)
    return loaded


def _has_no_ca(ctx: ssl.SSLContext) -> bool:
    """``True`` if an OpenSSL context has nothing to verify a certificate against."""
    if ctx.get_ca_certs():
        return False
    for capath in (os.environ.get("SSL_CERT_DIR"), ssl.get_default_verify_paths().capath):
        if capath and os.path.isdir(capath) and os.listdir(capath):
            return False
    return True


def make_ssl_context(
    *,
    cafile: str | Path | None = None,
    capath: str | Path | None = None,
    cadata: str | bytes | None = None,
    verify: bool = True,
    system_store: bool = True,
    mincifry: bool | None = None,
) -> ssl.SSLContext:
    """Build the :class:`ssl.SSLContext` used by :class:`~vkworkspace.Bot`.

    Args:
        cafile: Extra CA bundle (PEM) to trust in addition to the defaults,
            e.g. a private corporate CA.
        capath: Directory of hashed CA certs (OpenSSL ``c_rehash`` layout).
        cadata: Extra CA certificate(s) as PEM text / DER bytes.
        verify: ``False`` builds an **insecure** context (no certificate or
            hostname checks).
        system_store: Trust what the machine trusts (default ``True``): httpx2's
            own search plus the CA files found in :data:`SYSTEM_CA_FILES`,
            :data:`SYSTEM_CA_DIRS` and :data:`CA_BUNDLE_ENV`. ``False`` = only
            what the other arguments add.
        mincifry: Also trust the vendored Минцифры root CA. ``None``
            resolves via :func:`resolve_mincifry`.

    Examples::

        bot = Bot(token="...", api_url="...")                       # whatever the machine trusts
        bot = Bot(token="...", api_url="...", mincifry=True)        # + Минцифры from the package
        bot = Bot(..., verify_ssl="/certs/corp-ca.pem")              # + private corporate CA
    """
    if not verify:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    if system_store:
        ctx = httpx2.create_ssl_context()
        if _is_os_verified(ctx):
            # The OS decides; only bundles named by the environment are added.
            paths = [p for n in CA_BUNDLE_ENV if (p := os.environ.get(n)) and os.path.isfile(p)]
        else:
            paths = _system_ca_files()
        _load_files(ctx, paths)
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

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
    """Turn the public ``verify_ssl`` value into what httpx2 accepts.

    * ``ssl.SSLContext`` — passed through;
    * ``True`` — :func:`default_ssl_context` (what the machine trusts, plus the
      Минцифры certificates when *mincifry* resolves to ``True``);
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


def _mincifry_in_system_store() -> bool | None:
    """Whether this machine already trusts the Минцифры root (``Russian Trusted Root CA``).

    Windows: the machine, current-user and group-policy root stores. Linux: the
    CA files of the default context. ``None`` = cannot tell (macOS keychain, an
    OpenSSL directory of hashed certificates).
    """
    wanted = _mincifry_root_fingerprint()
    enum_certificates = getattr(ssl, "enum_certificates", None)
    if enum_certificates is not None:  # Windows
        try:
            return any(
                _fingerprint(der) == wanted for der, _enc, _trust in enum_certificates("ROOT")
            )
        except OSError:
            return None
    ctx = make_ssl_context(mincifry=False)
    if _is_os_verified(ctx):
        return None
    if any(_fingerprint(der) == wanted for der in ctx.get_ca_certs(binary_form=True)):
        return True
    return None if not _has_no_ca(ctx) and not ctx.get_ca_certs() else False


def describe_trust(mincifry: bool | None = None) -> str:
    """What ``verify_ssl=True`` trusts on this machine — for logs and bug reports::

    python -c "from vkworkspace.client.ssl_utils import describe_trust; print(describe_trust())"
    """
    ctx = make_ssl_context(mincifry=False)
    variables = ("SSL_CERT_FILE", "SSL_CERT_DIR", *CA_BUNDLE_ENV)
    lines = [f"{name}={os.environ[name]}" for name in variables if os.environ.get(name)]
    if _is_os_verified(ctx):
        lines.append("certificates are verified by the operating system (machine and user stores)")
    else:
        paths = ssl.get_default_verify_paths()
        lines.append(f"OpenSSL store: cafile={paths.cafile} capath={paths.capath}")
        files = _system_ca_files()
        lines.extend(f"found: {path}" for path in files[:20])
        if len(files) > 20:
            lines.append(f"found: … and {len(files) - 20} more files")
        lines.append(f"CA certificates loaded from files: {len(ctx.get_ca_certs())}")
        if _has_no_ca(ctx):
            lines.append("no CA certificates found on this machine")
    found = _mincifry_in_system_store()
    state = {True: "found", False: "not found", None: "unknown"}[found]
    lines.append(f"Минцифры root (Russian Trusted Root CA) in the system store: {state}")
    flag = "on" if resolve_mincifry(mincifry) else "off"
    lines.append(f"Минцифры certificates from the package (mincifry): {flag}")
    return "\n".join(lines)


def friendly_ssl_hint(host: str | None = None, *, mincifry: bool | None = None) -> str:
    """Текст ошибки проверки TLS-сертификата с учётом флага ``mincifry``."""
    where = f" ({host})" if host else ""
    head = f"Не удалось проверить TLS-сертификат сервера{where}. "
    try:
        in_system = _mincifry_in_system_store()
    except Exception:  # the hint must not replace the error it explains
        in_system = None
    if not resolve_mincifry(mincifry):
        if in_system:
            return (
                head + "Корневой сертификат Минцифры в системном хранилище найден, значит "
                "дело не в нём. Обычно причина одна из:\n"
                "  1. Сервер подписан приватным корпоративным CA — передайте его PEM: "
                "Bot(..., verify_ssl='/path/to/corp-ca.pem').\n"
                "  2. Сервер не отдаёт промежуточный сертификат (Sub CA) — проверьте цепочку: "
                "openssl s_client -connect host:443 -showcerts. Если так, добавьте Sub CA "
                f"через verify_ssl=... (скачать: {MINCIFRY_CERT_URL}).\n"
                "  3. Между вами и сервером TLS-перехватывающий прокси — доверьте его CA так же, "
                "как в п.1.\n"
                "  (Крайний случай, небезопасно: verify_ssl=False.)"
            )
        return (
            head + "Сертификат Минцифры (Russian Trusted Root CA) в системном хранилище "
            "не найден. Если сервер стоит за ним — так устроены on-premise VK Teams в РФ — "
            "включите сертификаты из комплекта любым способом:\n"
            "  1. Bot(..., mincifry=True)\n"
            '  2. Bot(..., verify_ssl="mincifry")\n'
            f"  3. переменная окружения {MINCIFRY_ENV}=1\n"
            "Если сервер подписан приватным корпоративным CA — передайте его PEM: "
            "Bot(..., verify_ssl='/path/to/corp-ca.pem').\n"
            'Что найдено на этой машине: python -c "from vkworkspace.client.ssl_utils '
            'import describe_trust; print(describe_trust())"\n'
            "  (Крайний случай, небезопасно: verify_ssl=False.)"
        )
    return (
        head + "vkworkspace уже доверяет системному хранилищу и корневому сертификату "
        "Минцифры (Russian Trusted Root CA), поэтому причина обычно одна из:\n"
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
