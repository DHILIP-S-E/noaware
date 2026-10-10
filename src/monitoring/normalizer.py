"""Content Normalization and Hashing Engine for NowAware."""

import hashlib
import re
from typing import Tuple


def normalize_whitespace(text: str) -> str:
    """Collapses multiple spaces, tabs, and duplicate blank lines into clean readable lines."""
    if not text:
        return ""
    # Standardize newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace non-breaking spaces
    text = text.replace("\xa0", " ")
    # Replace multiple inline whitespace with single space
    lines = []
    for line in text.split("\n"):
        cleaned_line = " ".join(line.split())
        if cleaned_line:
            lines.append(cleaned_line)
    return "\n".join(lines)


def clean_html_boilerplate(soup_or_text: str) -> str:
    """Removes dynamic noise like session IDs, tracking params, and ephemeral tokens."""
    text = soup_or_text
    # Remove obvious timestamp/runtime tags or csrf tokens if present
    text = re.sub(r'csrf[-_]token["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_\-]+["\']?', '', text, flags=re.IGNORECASE)
    return text


def compute_content_hash(text: str) -> str:
    """Computes SHA-256 hash of normalized text."""
    normalized = normalize_whitespace(text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_change_fingerprint(rule_id: str, diff_text: str) -> str:
    """Computes a stable fingerprint of diff changes to prevent duplicate alerts."""
    normalized_diff = " ".join(diff_text.split()).strip()
    payload = f"{rule_id}:{normalized_diff}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
