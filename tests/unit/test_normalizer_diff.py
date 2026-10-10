"""Unit tests for content normalization, hashing, and diff computation."""

import pytest
from src.monitoring.normalizer import (
    normalize_whitespace,
    compute_content_hash,
    compute_change_fingerprint,
)
from src.monitoring.diff_engine import DiffEngine


def test_normalize_whitespace():
    raw = "  Hello   world! \r\n\r\n  This is   a \t test.  \n "
    normalized = normalize_whitespace(raw)
    assert normalized == "Hello world!\nThis is a test."


def test_compute_content_hash():
    text1 = "Line one\nLine two"
    text2 = "Line one\nLine two"
    text3 = "Line one\nLine three"

    hash1 = compute_content_hash(text1)
    hash2 = compute_content_hash(text2)
    hash3 = compute_content_hash(text3)

    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64


def test_compute_change_fingerprint():
    fp1 = compute_change_fingerprint("rule-1", "May 15 -> April 10")
    fp2 = compute_change_fingerprint("rule-1", "May 15  ->  April 10")
    fp3 = compute_change_fingerprint("rule-2", "May 15 -> April 10")

    assert fp1 == fp2  # Normalized spaces produce identical fingerprint
    assert fp1 != fp3  # Different rule produces different fingerprint


def test_diff_engine_identical_content():
    text = "Line 1\nLine 2\nLine 3"
    result = DiffEngine.compute_diff(text, text)
    assert result.has_changed is False
    assert result.diff_unified == ""
    assert len(result.added_lines) == 0
    assert len(result.removed_lines) == 0


def test_diff_engine_detects_changes():
    baseline = "Program: CS\nDeadline: May 15, 2026\nAward: $10,000"
    current = "Program: CS\nDeadline: April 10, 2026\nAward: $10,000"

    result = DiffEngine.compute_diff(baseline, current)
    assert result.has_changed is True
    assert "Deadline: April 10, 2026" in result.added_lines
    assert "Deadline: May 15, 2026" in result.removed_lines
    assert result.isolated_previous == "Deadline: May 15, 2026"
    assert result.isolated_new == "Deadline: April 10, 2026"
    assert len(result.evidence_snippets) > 0
