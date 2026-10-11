"""Secure HTTP and Resource Fetcher for NowAware."""

import logging
from urllib.parse import urljoin
from typing import Tuple, Dict, Any, Optional, List
import httpx

from src.security.url_validator import (
    validate_url,
    URLSecurityError,
    create_ssrf_client,
)
from src.config import settings

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when source retrieval fails."""
    pass


class SourceFetcher:
    """Safely retrieves public web pages and feeds with SSRF, DNS rebinding, and DoS protections."""

    def __init__(
        self,
        timeout_seconds: Optional[int] = None,
        max_bytes: Optional[int] = None,
        max_redirects: int = 5,
        mock_sources: Optional[Dict[str, Optional[str]]] = None,
    ):
        self.timeout_seconds = timeout_seconds or settings.request_timeout_seconds
        self.max_bytes = max_bytes or settings.max_response_bytes
        self.max_redirects = max_redirects
        self.mock_sources: Dict[str, Optional[str]] = mock_sources or {}
        self.user_agent = "NowAware-Agent/1.0 (Personal AI Monitoring; https://nowaware.local)"

    def register_mock_source(self, url: str, content: Optional[str]):
        """Allows injecting mock content or simulated outages for offline demos and tests."""
        self.mock_sources[url] = content

    def fetch(self, url: str) -> Tuple[str, Dict[str, Any]]:
        """
        Retrieves the content of a public URL with connection-level SSRF defense and
        hop-by-hop redirect validation.
        Returns: (raw_content_str, metadata_dict)
        Raises: URLSecurityError, FetchError
        """
        if not url or not isinstance(url, str):
            raise FetchError("URL cannot be empty.")

        url = url.strip()

        # Check mock/demo registry first
        if url in self.mock_sources:
            content = self.mock_sources[url]
            if content is None:
                raise FetchError(f"HTTP 503 Service Unavailable: Simulated server outage at {url}.")
            return content, {
                "status_code": 200,
                "content_type": "text/html",
                "final_url": url,
                "redirect_hops": [],
                "is_mock": True,
            }

        # Check if URL uses mock/fixture scheme
        allow_mock = url.startswith("mock://") or url.startswith("fixture://")
        is_safe, resolved_ip = validate_url(url, allow_mock_schemes=allow_mock)
        if not is_safe:
            raise URLSecurityError(f"Security validation failed for URL: {url}")

        if allow_mock and url in self.mock_sources:
            content = self.mock_sources[url]
            if content is None:
                raise FetchError(f"HTTP 503 Service Unavailable: Simulated server outage at {url}.")
            return content, {
                "status_code": 200,
                "content_type": "text/html",
                "final_url": url,
                "redirect_hops": [],
                "is_mock": True,
            }

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,application/rss+xml,application/atom+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        redirect_hops: List[str] = []
        current_url = url

        try:
            with create_ssrf_client(timeout_seconds=float(self.timeout_seconds)) as client:
                for redirect_idx in range(self.max_redirects + 1):
                    # Pre-validate each hop URL before requesting
                    val_safe, _ = validate_url(current_url)
                    if not val_safe:
                        raise URLSecurityError(f"Redirect hop '{current_url}' failed security validation.")

                    response = client.get(
                        current_url,
                        headers=headers,
                        follow_redirects=False,  # Enforce manual hop-by-hop checking
                    )

                    # Check for HTTP redirect status codes
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            break  # Redirect without Location header, treat as end

                        next_url = urljoin(current_url, location)
                        redirect_hops.append(next_url)

                        if redirect_idx >= self.max_redirects:
                            raise FetchError(
                                f"Exceeded maximum allowed redirects ({self.max_redirects})."
                            )

                        logger.info(f"Validating redirect hop {redirect_idx + 1}: {current_url} -> {next_url}")
                        # Immediately validate the destination URL before looping
                        validate_url(next_url)
                        current_url = next_url
                        continue

                    # Final non-redirect response reached
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
                        "final_url": current_url,
                        "redirect_hops": redirect_hops,
                        "bytes_received": len(content_bytes),
                        "is_mock": False,
                    }
                    return text_content, metadata

                raise FetchError(f"Exceeded maximum allowed redirects ({self.max_redirects}).")

        except httpx.TimeoutException:
            raise FetchError(f"Connection timed out after {self.timeout_seconds}s while requesting source.")
        except httpx.RequestError as e:
            raise FetchError(f"Network transport error while requesting source: {e}")
        except URLSecurityError:
            raise
        except FetchError:
            raise
        except Exception as e:
            raise FetchError(f"Unexpected error retrieving source: {e}")
