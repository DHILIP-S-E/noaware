"""Unit tests for HTML and RSS/Atom parser."""

import pytest
from src.monitoring.parser import SourceParser
from src.schemas.monitoring import SourceType
from fixtures.scenarios import SCHOLARSHIP_BASELINE, RESEARCH_FEED_BASELINE


def test_detect_source_type():
    assert SourceParser.detect_source_type("<html><body>test</body></html>") == SourceType.HTML
    assert SourceParser.detect_source_type("<?xml><rss version='2.0'></rss>") == SourceType.RSS
    assert SourceParser.detect_source_type("<feed xmlns=\"http://www.w3.org/2005/atom\"></feed>") == SourceType.ATOM


def test_parse_html_strips_scripts_and_nav():
    html = """
    <html>
      <head><title>Test Scholarship</title></head>
      <body>
        <script>alert('malicious')</script>
        <style>.test { color: red; }</style>
        <nav><a href="#">Nav Item</a></nav>
        <h1>Main Scholarship Notice</h1>
        <p>Deadline is May 15, 2026.</p>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    text, title, meta = SourceParser.parse_html(html)
    assert title == "Test Scholarship"
    assert "alert" not in text
    assert "Nav Item" not in text
    assert "Copyright" not in text
    assert "Main Scholarship Notice" in text
    assert "Deadline is May 15, 2026." in text


def test_parse_feed():
    text, title, meta = SourceParser.parse_feed(RESEARCH_FEED_BASELINE)
    assert "Clean Energy Research" in title
    assert meta["entry_count"] >= 1
    assert "FY26 Community Solar Deployment Award" in text
    assert "ENTRY" in text
