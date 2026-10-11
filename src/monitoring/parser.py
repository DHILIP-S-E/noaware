"""Source Content Parsing Engine for HTML and Feeds."""

from typing import Tuple, Dict, Any, List, Optional
from bs4 import BeautifulSoup
import feedparser
from src.schemas.monitoring import SourceType
from src.monitoring.normalizer import normalize_whitespace


class SourceParser:
    """Extracts readable content and structured metadata from raw HTML or feeds."""

    @staticmethod
    def detect_source_type(content: str, content_type: str = "") -> SourceType:
        """Determines whether content is RSS, Atom, or regular HTML."""
        ct = content_type.lower()
        if "rss" in ct or "atom" in ct:
            return SourceType.RSS

        content_head = content[:2000].lower()
        if "<rss" in content_head or "<rdf:rdf" in content_head:
            return SourceType.RSS
        if "<feed" in content_head and "xmlns=\"http://www.w3.org/2005/atom\"" in content_head:
            return SourceType.ATOM

        return SourceType.HTML

    @staticmethod
    def parse_html(raw_html: str) -> Tuple[str, str, Dict[str, Any]]:
        """
        Extracts clean, readable textual content from HTML.
        Removes scripts, styles, navigation, footer, forms, header boilerplate.
        Returns: (normalized_text, page_title, metadata)
        """
        soup = BeautifulSoup(raw_html, "html.parser")

        # Extract title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Remove extraneous tags that introduce noise
        unwanted_tags = [
            "script", "style", "nav", "footer", "header", "noscript",
            "aside", "iframe", "svg", "form", "button", "dialog"
        ]
        for tag in soup.find_all(unwanted_tags):
            tag.decompose()

        # Also strip elements commonly marked as cookies, banners, sponsored content, or ads
        def _is_noise_attr(val):
            if not val:
                return False
            val_str = " ".join(val).lower() if isinstance(val, (list, tuple)) else str(val).lower()
            return any(w in val_str for w in ["cookie", "banner", "advert", "sponsored", "sidebar", "popup", "promo"])

        for noise_elem in soup.find_all(class_=_is_noise_attr):
            noise_elem.decompose()

        for noise_elem in soup.find_all(id=_is_noise_attr):
            noise_elem.decompose()

        # Extract headings and paragraphs in natural reading order
        text = soup.get_text(separator="\n")
        normalized = normalize_whitespace(text)

        metadata = {
            "title": title,
            "char_count": len(normalized),
            "line_count": len(normalized.splitlines()),
        }
        return normalized, title, metadata

    @staticmethod
    def parse_feed(raw_feed: str) -> Tuple[str, str, Dict[str, Any]]:
        """
        Parses RSS or Atom feeds using feedparser.
        Returns: (compact_feed_representation, feed_title, metadata)
        """
        parsed = feedparser.parse(raw_feed)
        feed_title = parsed.feed.get("title", "Untitled Feed").strip()

        lines = [f"FEED: {feed_title}"]
        entries_meta: List[Dict[str, Any]] = []

        for entry in parsed.entries[:50]:  # Top 50 recent entries
            entry_id = entry.get("id") or entry.get("link") or entry.get("title", "")
            title = entry.get("title", "No Title").strip()
            published = entry.get("published") or entry.get("updated", "")
            summary = entry.get("summary") or entry.get("description", "")
            clean_summary = normalize_whitespace(
                BeautifulSoup(summary, "html.parser").get_text()
            )

            lines.append(f"--- ENTRY ---")
            lines.append(f"ID: {entry_id}")
            lines.append(f"TITLE: {title}")
            if published:
                lines.append(f"PUBLISHED: {published}")
            if clean_summary:
                lines.append(f"SUMMARY: {clean_summary}")

            entries_meta.append({
                "id": entry_id,
                "title": title,
                "published": published,
                "link": entry.get("link", ""),
            })

        normalized = "\n".join(lines)
        metadata = {
            "title": feed_title,
            "entry_count": len(parsed.entries),
            "entries": entries_meta,
        }
        return normalized, feed_title, metadata

    @classmethod
    def parse(
        cls, raw_content: str, source_type: Optional[SourceType] = None, content_type: str = ""
    ) -> Tuple[str, str, Dict[str, Any]]:
        """High-level dispatch parser."""
        if not source_type:
            source_type = cls.detect_source_type(raw_content, content_type)

        if source_type in (SourceType.RSS, SourceType.ATOM):
            return cls.parse_feed(raw_content)
        else:
            return cls.parse_html(raw_content)
