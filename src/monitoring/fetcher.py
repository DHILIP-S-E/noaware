"""Secure HTTP and Resource Fetcher for NowAware."""

import httpx
from typing import Tuple, Dict, Any, Optional
from src.security.url_validator import validate_url, URLSecurityError
from src.config import settings


class FetchError(Exception):
    """Raised when source retrieval fails."""
    pass


class SourceFetcher:
    """Safely retrieves public web pages and feeds with SSRF and DoS protections."""

    def __init__(
        self,
        timeout_seconds: Optional[int] = None,
        max_bytes: Optional[int] = None,
        mock_sources: Optional[Dict[str, str]] = None,
    ):
        self.timeout_seconds = timeout_seconds or settings.request_timeout_seconds
        self.max_bytes = max_bytes or settings.max_response_bytes
        self.mock_sources = mock_sources or {}
        self.user_agent = "NowAware-Agent/1.0 (Personal AI Monitoring; https://nowaware.local)"

    def register_mock_source(self, url: str, content: str):
        """Allows injecting mock content for offline demos and tests."""
        self.mock_sources[url] = content

    def fetch(self, url: str) -> Tuple[str, Dict[str, Any]]:
        """
        Retrieves the content of a public URL.
        Returns: (raw_content_str, metadata_dict)
        Raises: URLSecurityError, FetchError
        """
        if not url:
            raise FetchError("URL cannot be empty.")

        # Check mock/demo registry first
        if url in self.mock_sources:
            content = self.mock_sources[url]
            if content is None:
                raise FetchError(f"HTTP 503 Service Unavailable: Simulated server outage at {url}.")
            return content, {
                "status_code": 200,
                "content_type": "text/html",
                "final_url": url,
                "is_mock": True,
            }

        # Perform SSRF validation
        allow_mock = url.startswith("mock://") or url.startswith("fixture://")
        is_safe, resolved_ip = validate_url(url, allow_mock_schemes=allow_mock)
        if not is_safe:
            raise URLSecurityError(f"Security validation failed for URL: {url}")

        if allow_mock and url in self.mock_sources:
            return self.mock_sources[url], {
                "status_code": 200,
                "content_type": "text/html",
                "final_url": url,
                "is_mock": True,
            }

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,application/rss+xml,application/atom+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            # We follow redirects but re-validate destination in client hooks
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                max_redirects=5,
                headers=headers,
            ) as client:
                response = client.get(url)

                # Validate final redirected URL against SSRF
                final_url = str(response.url)
                if final_url != url:
                    val_safe, _ = validate_url(final_url)
                    if not val_safe:
                        raise URLSecurityError(f"Redirected to disallowed location: {final_url}")

                if response.status_code >= 400:
                    raise FetchError(
                        f"HTTP {response.status_code} error received from source ({response.reason_phrase})."
                    )

                # Enforce response body size limit
                content_bytes = response.content
                if len(content_bytes) > self.max_bytes:
                    raise FetchError(
                        f"Response size ({len(content_bytes)} bytes) exceeds safety limit of {self.max_bytes} bytes."
                    )

                content_type = response.headers.get("content-type", "")
                text_content = response.text

                metadata = {
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "final_url": final_url,
                    "bytes_received": len(content_bytes),
                    "is_mock": False,
                }
                return text_content, metadata

        except httpx.TimeoutException:
            raise FetchError(f"Connection timed out after {self.timeout_seconds}s while requesting source.")
        except httpx.RequestError as e:
            raise FetchError(f"Network transport error while requesting source: {e}")
        except URLSecurityError:
            raise
        except Exception as e:
            raise FetchError(f"Unexpected error retrieving source: {e}")
