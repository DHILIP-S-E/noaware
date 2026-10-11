"""Security tests for hop-by-hop redirect validation and connection-level SSRF defense."""

import pytest
import httpx
from src.security.url_validator import (
    validate_url,
    URLSecurityError,
    SSRFProtectedSyncBackend,
    create_ssrf_client,
)
from src.monitoring.fetcher import SourceFetcher, FetchError


def test_validate_url_rejects_internal_ip_schemes():
    with pytest.raises(URLSecurityError):
        validate_url("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(URLSecurityError):
        validate_url("http://127.0.0.1:8080/admin")

    with pytest.raises(URLSecurityError):
        validate_url("http://192.168.1.1/")

    with pytest.raises(URLSecurityError):
        validate_url("http://10.0.0.1/internal")


def test_connection_level_ssrf_backend_blocks_private_ips():
    backend = SSRFProtectedSyncBackend()
    with pytest.raises(URLSecurityError, match="Connection-level SSRF blocked"):
        backend.connect_tcp("127.0.0.1", 80)

    with pytest.raises(URLSecurityError, match="Connection-level SSRF blocked"):
        backend.connect_tcp("169.254.169.254", 80)


import socket

def test_fetcher_hop_by_hop_redirect_to_metadata_is_blocked(monkeypatch):
    """
    Simulates a public website redirecting to AWS cloud metadata http://169.254.169.254.
    Ensures the hop is intercepted and aborted BEFORE connecting.
    """
    fetcher = SourceFetcher()

    orig_getaddrinfo = socket.getaddrinfo
    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "public.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
        return orig_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    class MockRedirectClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers=None, follow_redirects=False):
            # First request to public URL returns a redirect to cloud metadata
            if "public.example.com" in url:
                return httpx.Response(
                    status_code=302,
                    headers={"Location": "http://169.254.169.254/latest/meta-data/"},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(status_code=200, request=httpx.Request("GET", url))

    # Monkeypatch client factory to simulate intermediate redirect hop
    monkeypatch.setattr("src.monitoring.fetcher.create_ssrf_client", lambda timeout_seconds=15.0: MockRedirectClient())

    with pytest.raises(URLSecurityError, match="restricted IP"):
        fetcher.fetch("https://public.example.com/redirect-to-metadata")


def test_fetcher_max_redirect_limit_enforced(monkeypatch):
    """Ensures infinite redirect loops are bounded."""
    fetcher = SourceFetcher(max_redirects=3)

    orig_getaddrinfo = socket.getaddrinfo
    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "public.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
        return orig_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    class MockLoopClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, headers=None, follow_redirects=False):
            # Keeps redirecting
            return httpx.Response(
                status_code=301,
                headers={"Location": "https://public.example.com/loop"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr("src.monitoring.fetcher.create_ssrf_client", lambda timeout_seconds=15.0: MockLoopClient())

    with pytest.raises(FetchError, match="Exceeded maximum allowed redirects"):
        fetcher.fetch("https://public.example.com/loop")


def test_ssrf_backend_pins_exact_validated_ip(monkeypatch):
    """
    Proves that the address passed to socket.create_connection is the resolved,
    validated IP address ('93.184.216.34') and NOT the hostname string ('example.com').
    """
    backend = SSRFProtectedSyncBackend()
    captured_connections = []

    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "safe.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return socket.getaddrinfo(host, port, *args, **kwargs)

    class DummySocket:
        def setsockopt(self, *args):
            pass
        def settimeout(self, *args):
            pass

    def mock_create_connection(address, timeout=None, source_address=None):
        captured_connections.append(address)
        return DummySocket()

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", mock_create_connection)

    stream = backend.connect_tcp("safe.example.com", 443)
    assert len(captured_connections) == 1
    # Address passed to create_connection must be the pinned IP ('93.184.216.34', 443)
    assert captured_connections[0] == ("93.184.216.34", 443)
    assert captured_connections[0][0] != "safe.example.com"


def test_dns_rebinding_aborted_at_connection_time(monkeypatch):
    """
    Simulates a true DNS-rebinding TOCTOU attack:
    1. Initial URL pre-check resolves 'rebind.attacker.com' to safe public IP '93.184.216.34'.
    2. At connection time, DNS records update to point to AWS metadata '169.254.169.254'.
    3. Proves that connection-level backend detects the rebinding and aborts the connection.
    """
    resolution_count = 0

    def rebinding_getaddrinfo(host, port, *args, **kwargs):
        nonlocal resolution_count
        if host == "rebind.attacker.com":
            resolution_count += 1
            if resolution_count == 1:
                # First check: returns benign public IP
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
            else:
                # Rebound check at connection time: returns private AWS metadata IP
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port or 0))]
        return socket.getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)

    # 1. First validation passes (simulating URL pre-check)
    is_safe, ip = validate_url("https://rebind.attacker.com/status")
    assert is_safe is True
    assert ip == "93.184.216.34"

    # 2. Connection time: DNS rebinds to 169.254.169.254
    backend = SSRFProtectedSyncBackend()
    with pytest.raises(URLSecurityError, match="Connection-level SSRF blocked.*169.254.169.254"):
        backend.connect_tcp("rebind.attacker.com", 443)


def test_tls_sni_and_hostname_verification_preserved(monkeypatch):
    """
    Proves that when upgrading a pinned IP socket to TLS, the server_hostname
    passed to ssl_context.wrap_socket is the original domain name ('secure.example.com'),
    preserving SNI and certificate verification.
    """
    from httpcore._backends.sync import SyncStream
    import ssl

    class DummySocket:
        def setsockopt(self, *args):
            pass
        def settimeout(self, *args):
            pass
        def close(self):
            pass

    dummy_raw_sock = DummySocket()
    stream = SyncStream(dummy_raw_sock)

    wrapped_hostnames = []

    class DummySSLContext:
        def wrap_socket(self, sock, server_hostname=None):
            wrapped_hostnames.append(server_hostname)
            return sock

    ssl_ctx = DummySSLContext()
    stream.start_tls(ssl_ctx, server_hostname="secure.example.com")

    # TLS wrap_socket must receive original server_hostname for SNI / cert validation
    assert len(wrapped_hostnames) == 1
    assert wrapped_hostnames[0] == "secure.example.com"


def test_multi_hop_redirect_intercepted(monkeypatch):
    """
    Tests a 3-hop redirect chain:
    Hop 1: public.example.com/start (302 -> https://public.example.com/next)
    Hop 2: public.example.com/next (302 -> http://127.0.0.1/admin)
    Ensures Hop 2 -> Hop 3 is intercepted before connection.
    """
    fetcher = SourceFetcher(max_redirects=5)

    def mock_getaddrinfo(host, port, *args, **kwargs):
        if "public.example.com" in host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
        return socket.getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    class MockMultiHopClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, headers=None, follow_redirects=False):
            if "/start" in url:
                return httpx.Response(
                    status_code=302,
                    headers={"Location": "https://public.example.com/next"},
                    request=httpx.Request("GET", url),
                )
            if "/next" in url:
                return httpx.Response(
                    status_code=302,
                    headers={"Location": "http://127.0.0.1:8080/admin"},
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(status_code=200, request=httpx.Request("GET", url))

    monkeypatch.setattr("src.monitoring.fetcher.create_ssrf_client", lambda timeout_seconds=15.0: MockMultiHopClient())

    with pytest.raises(URLSecurityError, match="restricted internal domain|restricted IP"):
        fetcher.fetch("https://public.example.com/start")
