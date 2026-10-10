"""Unit tests for URL Security and SSRF Protections."""

import pytest
from src.security.url_validator import validate_url, is_ip_private_or_restricted, URLSecurityError


def test_ip_private_or_restricted():
    assert is_ip_private_or_restricted("127.0.0.1") is True
    assert is_ip_private_or_restricted("10.0.0.1") is True
    assert is_ip_private_or_restricted("192.168.1.100") is True
    assert is_ip_private_or_restricted("172.16.0.5") is True
    assert is_ip_private_or_restricted("169.254.169.254") is True  # AWS Metadata
    assert is_ip_private_or_restricted("::1") is True
    assert is_ip_private_or_restricted("8.8.8.8") is False  # Public Google DNS
    assert is_ip_private_or_restricted("1.1.1.1") is False  # Public Cloudflare DNS


def test_validate_url_rejects_disallowed_schemes():
    with pytest.raises(URLSecurityError, match="Disallowed scheme"):
        validate_url("ftp://example.com/file")

    with pytest.raises(URLSecurityError, match="Disallowed scheme"):
        validate_url("file:///etc/passwd")

    with pytest.raises(URLSecurityError, match="Disallowed scheme"):
        validate_url("gopher://example.com")


def test_validate_url_rejects_credentials():
    with pytest.raises(URLSecurityError, match="Credentials embedded"):
        validate_url("https://user:password@example.com")


def test_validate_url_rejects_localhost_and_internal_domains():
    with pytest.raises(URLSecurityError):
        validate_url("http://localhost:8080")

    with pytest.raises(URLSecurityError):
        validate_url("http://127.0.0.1/admin")

    with pytest.raises(URLSecurityError):
        validate_url("http://metadata.google.internal")


def test_validate_url_rejects_aws_metadata_ip():
    with pytest.raises(URLSecurityError):
        validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_allows_mock_scheme_when_flagged():
    is_safe, resolved = validate_url("mock://foundation.org/scholarship", allow_mock_schemes=True)
    assert is_safe is True
    assert resolved == "mock"
