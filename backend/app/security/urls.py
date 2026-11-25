"""URL validation and SSRF defenses for operator-supplied source URLs.

Phase 1 validates URLs at entry time (scheme, userinfo, literal IPs, local hostnames).
Phase 2's fetcher must additionally call :func:`resolve_and_check_host` on every request and redirect
hop, and connect only to the validated address (DNS-rebinding defense).
"""

import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    """Raised when a URL is not allowed as a retrieval source."""


_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal", "metadata"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan")


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    # Reject legacy numeric forms such as 2130706433 or 0x7f.1 that resolvers may treat as IPs.
    try:
        if host.isdigit() or host.lower().startswith("0x"):
            return ipaddress.ip_address(socket.inet_aton(host))
        if all(p.isdigit() or p.lower().startswith("0x") for p in host.split(".")) and "." in host:
            return ipaddress.ip_address(socket.inet_aton(host))
    except (OSError, ValueError):
        raise UnsafeUrlError("Ambiguous numeric host is not allowed") from None
    return None


def validate_source_url(raw_url: str) -> tuple[str, str]:
    """Validate a URL and return ``(clean_url, normalized_url)``.

    Raises :class:`UnsafeUrlError` for disallowed URLs.
    """
    if not raw_url or len(raw_url) > 2048:
        raise UnsafeUrlError("URL is empty or too long")
    if any(ch.isspace() for ch in raw_url.strip()) or any(ord(ch) < 32 for ch in raw_url):
        raise UnsafeUrlError("URL contains whitespace or control characters")
    url = raw_url.strip()
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise UnsafeUrlError("URL could not be parsed") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https URLs are allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrlError("URL has no host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeUrlError("Invalid internationalized host name") from exc
    ip = _parse_ip_literal(host)
    if ip is not None and is_blocked_ip(ip):
        raise UnsafeUrlError("Private, loopback, link-local and reserved addresses are not allowed")
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeUrlError("Local or internal host names are not allowed")
    if ip is None and "." not in host:
        raise UnsafeUrlError("Single-label host names are not allowed")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("Invalid port") from exc
    if port is not None and port not in (80, 443, 8080, 8443):
        raise UnsafeUrlError("Non-standard ports are not allowed")

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if (port is None or default_port) else f"{host}:{port}"
    if ip is not None and ip.version == 6:
        netloc = f"[{host.strip('[]')}]" + ("" if port is None or default_port else f":{port}")
    path = parts.path or "/"
    normalized = urlunsplit(SplitResult(scheme, netloc, path, parts.query, ""))
    return url, normalized


def resolve_and_check_host(host: str, port: int = 443) -> list[str]:
    """Resolve ``host`` and ensure every address is public. Returns the validated addresses."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Host could not be resolved: {host}") from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise UnsafeUrlError("Host resolved to no addresses")
    for addr in addresses:
        if is_blocked_ip(ipaddress.ip_address(addr.split("%")[0])):
            raise UnsafeUrlError("Host resolves to a non-public address")
    return addresses


def normalize_host_list(hosts: list[str]) -> list[str]:
    cleaned: list[str] = []
    for host in hosts:
        h = host.strip().lower().rstrip(".")
        if not h:
            continue
        if "/" in h or "@" in h or ":" in h or " " in h:
            raise UnsafeUrlError(f"Invalid allowed host: {host}")
        if h in _BLOCKED_HOSTNAMES or h.endswith(_BLOCKED_SUFFIXES):
            raise UnsafeUrlError(f"Local host not allowed: {host}")
        ip = _parse_ip_literal(h)
        if ip is not None and is_blocked_ip(ip):
            raise UnsafeUrlError(f"Private address not allowed: {host}")
        if h not in cleaned:
            cleaned.append(h)
    return cleaned
