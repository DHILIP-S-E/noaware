"""Unit tests for SQLite Storage."""

import os
import tempfile
import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.schemas.monitoring import MonitoringRule, SourceSnapshot, RuleStatus, SourceType
from src.schemas.changes import ChangeEvent, ClassificationType


@pytest.fixture
def temp_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage = SQLiteStorage(path)
    yield storage
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def test_rule_crud_operations(temp_store):
    rule = MonitoringRule(
        name="Test Monitor",
        source_url="https://example.com/notices",
        natural_language_goal="Watch for updates",
        criteria_categories=["Important dates and deadlines"],
    )

    # Save
    temp_store.save_rule(rule)
    fetched = temp_store.get_rule(rule.id)
    assert fetched is not None
    assert fetched.name == "Test Monitor"
    assert fetched.status == RuleStatus.ACTIVE

    # Update
    rule.status = RuleStatus.PAUSED
    rule.name = "Updated Monitor Name"
    temp_store.update_rule(rule)
    updated = temp_store.get_rule(rule.id)
    assert updated.status == RuleStatus.PAUSED
    assert updated.name == "Updated Monitor Name"

    # List
    rules = temp_store.list_rules()
    assert len(rules) == 1

    # Delete
    temp_store.delete_rule(rule.id)
    assert temp_store.get_rule(rule.id) is None
    assert len(temp_store.list_rules()) == 0


def test_snapshot_operations(temp_store):
    rule = MonitoringRule(name="R1", source_url="https://example.com", natural_language_goal="g")
    temp_store.save_rule(rule)

    snap1 = SourceSnapshot(
        rule_id=rule.id,
        content_hash="hash1",
        normalized_content="Content 1",
        captured_at="2026-01-01T00:00:00Z",
    )
    snap2 = SourceSnapshot(
        rule_id=rule.id,
        content_hash="hash2",
        normalized_content="Content 2",
        captured_at="2026-01-02T00:00:00Z",
    )
    temp_store.save_snapshot(snap1)
    temp_store.save_snapshot(snap2)

    latest = temp_store.get_latest_snapshot(rule.id)
    assert latest is not None
    assert latest.content_hash == "hash2"


def test_change_events_and_deduplication(temp_store):
    rule = MonitoringRule(name="R1", source_url="https://example.com", natural_language_goal="g")
    temp_store.save_rule(rule)

    event = ChangeEvent(
        rule_id=rule.id,
        rule_name=rule.name,
        change_fingerprint="fp123",
        classification=ClassificationType.MEANINGFUL,
        summary="Deadline moved",
        impact_explanation="Explanation",
        source_url=rule.source_url,
        recommended_action="Act",
        should_notify=True,
    )

    temp_store.save_change_event(event)
    assert temp_store.is_duplicate_event(rule.id, "fp123") is True
    assert temp_store.is_duplicate_event(rule.id, "different_fp") is False

    events = temp_store.list_change_events()
    assert len(events) == 1
    assert events[0].read is False

    # Mark Read
    temp_store.mark_event_read(event.event_id, True)
    assert temp_store.get_change_event(event.event_id).read is True
