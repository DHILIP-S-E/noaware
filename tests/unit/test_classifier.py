"""Unit tests for Change Classifier."""

import pytest
from src.schemas.monitoring import MonitoringRule, SourceType
from src.schemas.changes import ClassificationType
from src.monitoring.diff_engine import DiffEngine
from src.monitoring.classifier import ChangeClassifier
from fixtures.scenarios import (
    SCHOLARSHIP_BASELINE,
    SCHOLARSHIP_EARLIER_DEADLINE,
    SCHOLARSHIP_LAYOUT_ONLY,
)
from src.monitoring.parser import SourceParser


@pytest.fixture
def deadline_rule():
    return MonitoringRule(
        name="Scholarship Deadline",
        source_url="mock://scholarship",
        natural_language_goal="Alert me if the deadline changes.",
        criteria_categories=["Important dates and deadlines"],
        specific_instructions="deadline, due date",
    )


def test_classify_no_changes(deadline_rule):
    diff = DiffEngine.compute_diff("Same text", "Same text")
    res = ChangeClassifier.classify_diff(deadline_rule, diff)
    assert res.change_detected is False
    assert res.classification == ClassificationType.IRRELEVANT
    assert res.should_notify is False


def test_classify_meaningful_deadline_change(deadline_rule):
    base_text, _, _ = SourceParser.parse_html(SCHOLARSHIP_BASELINE)
    new_text, _, _ = SourceParser.parse_html(SCHOLARSHIP_EARLIER_DEADLINE)

    diff = DiffEngine.compute_diff(base_text, new_text)
    res = ChangeClassifier.classify_diff(deadline_rule, diff)

    assert res.change_detected is True
    assert res.classification == ClassificationType.MEANINGFUL
    assert res.should_notify is True
    assert "April 10, 2026" in res.summary or "April 10, 2026" in (res.new_value or "")
    assert len(res.evidence) > 0


def test_classify_suppresses_irrelevant_layout_noise(deadline_rule):
    base_text, _, _ = SourceParser.parse_html(SCHOLARSHIP_BASELINE)
    new_text, _, _ = SourceParser.parse_html(SCHOLARSHIP_LAYOUT_ONLY)

    diff = DiffEngine.compute_diff(base_text, new_text)
    # The substantive text is identical, only footer/noise classes were modified
    res = ChangeClassifier.classify_diff(deadline_rule, diff)

    # Either no diff was created after normalization or it was classified as irrelevant
    if diff.has_changed:
        assert res.classification == ClassificationType.IRRELEVANT
    assert res.should_notify is False


def test_classify_ambiguous_change_marked_uncertain(deadline_rule):
    base = "Notice: General department operations continue as normal."
    curr = "Notice: Some internal committee restructuring is underway."
    diff = DiffEngine.compute_diff(base, curr)

    res = ChangeClassifier.classify_diff(deadline_rule, diff)
    assert res.change_detected is True
    assert res.classification == ClassificationType.UNCERTAIN
    assert res.should_notify is False  # Quiet by default for uncertain
