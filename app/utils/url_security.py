import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import settings


def _is_private_ip(ip_str: str) -> bool:
    """Rechaza IPs privadas, loopback, link-local, reservadas, multicast y metadata."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_url(url: str) -> bool:
    """
    Valida que una URL de descarga no pueda usarse como SSRF.

    - Solo http/https.
    - Bloquea IPs privadas/loopback/link-local/metadata (resolviendo DNS).
    - Si ALLOWED_DOWNLOAD_HOSTS está definido (sufijos separados por coma),
      exige que el host coincida con alguno de esos sufijos.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname

    if scheme not in ("http", "https"):
        return False
    if not host:
        return False

    # 1. Resolver y bloquear IPs privadas/link-local/metadata
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False

    for info in infos:
        ip = info[4][0]
        if _is_private_ip(ip):
            return False

    # 2. Allowlist por sufijo de host (configurable, no amarrado a Backblaze)
    allowed = [
        h.strip().lower()
        for h in (settings.ALLOWED_DOWNLOAD_HOSTS or "").split(",")
        if h.strip()
    ]
    if allowed:
        host_lower = host.lower()
        if not any(host_lower == a or host_lower.endswith("." + a) for a in allowed):
            return False

    return True
