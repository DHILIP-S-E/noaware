"""Unit tests for MonitoringService workflow."""

import os
import tempfile
import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.monitoring.fetcher import SourceFetcher
from src.monitoring.service import MonitoringService
from src.schemas.monitoring import MonitoringRule, RuleStatus
from src.schemas.changes import ClassificationType
from fixtures.scenarios import SCHOLARSHIP_BASELINE, SCHOLARSHIP_EARLIER_DEADLINE


@pytest.fixture
def test_service():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage = SQLiteStorage(path)
    fetcher = SourceFetcher()
    fetcher.register_mock_source("mock://test-scholarship", SCHOLARSHIP_BASELINE)
    service = MonitoringService(storage=storage, fetcher=fetcher)
    yield service
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def test_service_establish_baseline(test_service):
    rule = MonitoringRule(
        name="Scholarship",
        source_url="mock://test-scholarship",
        natural_language_goal="Watch deadline",
        criteria_categories=["Important dates and deadlines"],
    )
    test_service.storage.save_rule(rule)
    snapshot = test_service.establish_baseline(rule)

    assert snapshot is not None
    assert len(snapshot.content_hash) == 64
    assert test_service.storage.get_latest_snapshot(rule.id) is not None


def test_service_detects_no_changes(test_service):
    rule = MonitoringRule(
        name="Scholarship",
        source_url="mock://test-scholarship",
        natural_language_goal="Watch deadline",
        criteria_categories=["Important dates and deadlines"],
    )
    test_service.storage.save_rule(rule)
    test_service.establish_baseline(rule)

    has_changed, event, msg = test_service.check_rule(rule.id)
    assert has_changed is False
    assert event is None
    assert "unchanged" in msg.lower()


def test_service_detects_meaningful_change_and_prevents_duplicates(test_service):
    rule = MonitoringRule(
        name="Scholarship",
        source_url="mock://test-scholarship",
        natural_language_goal="Watch deadline",
        criteria_categories=["Important dates and deadlines"],
    )
    test_service.storage.save_rule(rule)
    test_service.establish_baseline(rule)

    # First check with updated content -> Meaningful Change
    has_changed, event, msg = test_service.check_rule(
        rule.id, simulated_content=SCHOLARSHIP_EARLIER_DEADLINE
    )
    assert has_changed is True
    assert event is not None
    assert event.classification == ClassificationType.MEANINGFUL
    assert event.should_notify is True

    # Immediate second check with same updated content -> Unchanged or Duplicate Alert suppressed
    has_changed_2, event_2, msg_2 = test_service.check_rule(
        rule.id, simulated_content=SCHOLARSHIP_EARLIER_DEADLINE
    )
    # Since snapshot was updated to the new content, second check returns unchanged
    assert event_2 is None


def test_service_handles_retrieval_error_preserves_baseline(test_service):
    rule = MonitoringRule(
        name="Scholarship",
        source_url="mock://failing-source",
        natural_language_goal="Watch deadline",
    )
    test_service.storage.save_rule(rule)
    # Manually establish baseline
    from src.schemas.monitoring import SourceSnapshot
    test_service.storage.save_snapshot(
        SourceSnapshot(rule_id=rule.id, content_hash="hash123", normalized_content="Initial")
    )

    # Now check a failing source (empty or not in mock fetcher)
    has_changed, event, msg = test_service.check_rule(rule.id)
    assert has_changed is False
    assert event is None
    assert "failed" in msg.lower()

    # Rule recorded failure
    updated_rule = test_service.storage.get_rule(rule.id)
    assert updated_rule.consecutive_failures == 1
    assert updated_rule.error_message is not None

    # Baseline is still preserved
    latest = test_service.storage.get_latest_snapshot(rule.id)
    assert latest.content_hash == "hash123"
