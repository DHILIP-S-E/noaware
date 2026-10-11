"""SSRF Defense and Connection-Level Socket Validation for NowAware."""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple, Optional, Iterable
import httpcore
from httpcore._backends.sync import SyncBackend, SyncStream, map_exceptions, ConnectTimeout, ConnectError, ExceptionMapping, SOCKET_OPTION
import httpx


class URLSecurityError(Exception):
    """Raised when a URL violates SSRF safety rules or targets internal endpoints."""
    pass


def is_ip_private_or_restricted(ip_str: str) -> bool:
    """Check if an IP address belongs to loopback, private, link-local, or reserved spaces."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # Check standard attributes
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True

        # Explicit check for AWS/cloud metadata address: 169.254.169.254
        if str(ip) == "169.254.169.254":
            return True

        # Check IPv4 mapped IPv6 (e.g., ::ffff:127.0.0.1 or ::ffff:169.254.169.254)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return is_ip_private_or_restricted(str(ip.ipv4_mapped))

        return False
    except ValueError:
        return True


def validate_url(url: str, allow_mock_schemes: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validates a URL against SSRF attacks.
    Returns (is_valid, resolved_ip_or_error_reason).
    """
    if not url or not isinstance(url, str):
        raise URLSecurityError("URL cannot be empty.")

    url = url.strip()
    parsed = urlparse(url)

    # 1. Enforce scheme: only http or https (unless demo/mock scheme explicitly permitted for unit tests)
    allowed_schemes = ("http", "https")
    if parsed.scheme.lower() not in allowed_schemes:
        if allow_mock_schemes and parsed.scheme.lower() in ("mock", "fixture"):
            return True, "mock"
        raise URLSecurityError(f"Disallowed scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted.")

    # 2. Reject credentials in URL (e.g. https://user:pass@example.com)
    if parsed.username or parsed.password:
        raise URLSecurityError("Credentials embedded in URL are forbidden.")

    # 3. Check hostname exists
    hostname = parsed.hostname
    if not hostname:
        raise URLSecurityError("URL is missing a valid hostname.")

    hostname_lower = hostname.lower()

    # 4. Reject localhost, local domain names, and cloud metadata names
    restricted_hostnames = {
        "localhost",
        "127.0.0.1",
        "::1",
        "metadata.google.internal",
        "instance-data",
        "local",
        "internal",
    }
    if (
        hostname_lower in restricted_hostnames
        or hostname_lower.endswith(".local")
        or hostname_lower.endswith(".localhost")
        or hostname_lower.endswith(".internal")
    ):
        raise URLSecurityError(f"Hostname '{hostname}' resolves to restricted internal domain.")

    # 5. Check if hostname is direct IP address
    try:
        ip = ipaddress.ip_address(hostname)
        if is_ip_private_or_restricted(str(ip)):
            raise URLSecurityError(f"Direct IP '{hostname}' belongs to private/restricted IP range.")
        return True, str(ip)
    except ValueError:
        pass

    # 6. Resolve DNS and check all resolved IPs
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise URLSecurityError(f"Failed to resolve hostname '{hostname}': {e}")

    resolved_ips = []
    for item in addr_info:
        sockaddr = item[4]
        ip_addr = sockaddr[0]
        if is_ip_private_or_restricted(ip_addr):
            raise URLSecurityError(
                f"Hostname '{hostname}' resolved to restricted IP '{ip_addr}'."
            )
        resolved_ips.append(ip_addr)

    primary_ip = resolved_ips[0] if resolved_ips else None
    return True, primary_ip


class SSRFProtectedSyncBackend(SyncBackend):
    """
    Custom network backend for httpcore that enforces IP validation and pinning
    at the raw TCP socket creation layer, eliminating DNS rebinding / TOCTOU attacks.
    """

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Iterable[SOCKET_OPTION]] = None,
    ) -> SyncStream:
        # Pre-connection IP resolution and verification
        try:
            addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise URLSecurityError(f"Failed to resolve host '{host}' at connection time: {e}")

        safe_ips = []
        for item in addr_info:
            ip_str = item[4][0]
            if is_ip_private_or_restricted(ip_str):
                raise URLSecurityError(
                    f"Connection-level SSRF blocked: host '{host}' resolved to restricted IP '{ip_str}'."
                )
            safe_ips.append((item[0], item[1], item[2], item[3], item[4]))

        if not safe_ips:
            raise URLSecurityError(f"No valid IP address found for host '{host}'.")

        # Pin socket connection to the first verified safe IP
        pinned_item = safe_ips[0]
        pinned_addr = (pinned_item[4][0], port)
        source_address = None if local_address is None else (local_address, 0)
        if socket_options is None:
            socket_options = []

        exc_map: ExceptionMapping = {
            socket.timeout: ConnectTimeout,
            OSError: ConnectError,
        }

        with map_exceptions(exc_map):
            sock = socket.create_connection(
                pinned_addr,
                timeout,
                source_address=source_address,
            )
            for option in socket_options:
                sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        return SyncStream(sock)


class SSRFProtectedTransport(httpx.HTTPTransport):
    """HTTPX Transport backed by connection-level SSRF defense."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Override the pool's network backend with our SSRF validator
        self._pool._network_backend = SSRFProtectedSyncBackend()


def create_ssrf_client(timeout_seconds: float = 15.0) -> httpx.Client:
    """Creates an HTTPX client equipped with connection-level SSRF defense."""
    transport = SSRFProtectedTransport(verify=True)
    return httpx.Client(
        transport=transport,
        timeout=timeout_seconds,
        follow_redirects=False,  # Redirects must be explicitly validated per hop
    )
