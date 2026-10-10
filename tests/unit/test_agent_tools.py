"""Unit tests for Strands agent tools."""

import os
import tempfile
import json
import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.monitoring.fetcher import SourceFetcher
from src.agent.tools import (
    set_global_context,
    inspect_source,
    create_monitoring_rule,
    get_monitoring_rule,
    check_for_changes,
    pause_monitor,
    update_monitor,
    prepare_alert,
)
from fixtures.scenarios import SCHOLARSHIP_BASELINE


@pytest.fixture
def tool_context():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage = SQLiteStorage(path)
    fetcher = SourceFetcher()
    fetcher.register_mock_source("mock://scholarship", SCHOLARSHIP_BASELINE)
    set_global_context(storage, fetcher)
    yield storage, fetcher
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def test_inspect_source_tool(tool_context):
    res = inspect_source(url="mock://scholarship")
    assert "Successfully inspected" in res
    assert "STEM Global Leadership" in res


def test_create_and_get_rule_tools(tool_context):
    storage, _ = tool_context
    res = create_monitoring_rule(
        name="Agent Created Monitor",
        source_url="mock://scholarship",
        natural_language_goal="Watch for deadline change",
        criteria_categories=["Important dates and deadlines"],
    )
    assert "Successfully created" in res

    rules = storage.list_rules()
    assert len(rules) == 1
    rule_id = rules[0].id

    # Test get rule tool
    rule_json = get_monitoring_rule(rule_id=rule_id)
    parsed = json.loads(rule_json)
    assert parsed["id"] == rule_id
    assert parsed["name"] == "Agent Created Monitor"


def test_pause_and_update_tools(tool_context):
    storage, _ = tool_context
    create_monitoring_rule(
        name="Monitor 1",
        source_url="mock://scholarship",
        natural_language_goal="Goal",
        criteria_categories=["Dates"],
    )
    rule_id = storage.list_rules()[0].id

    # Pause
    pause_res = pause_monitor(rule_id=rule_id)
    assert "paused" in pause_res

    # Update
    update_res = update_monitor(rule_id=rule_id, name="Renamed Monitor", check_interval_minutes=60)
    assert "updated" in update_res

    updated_rule = storage.get_rule(rule_id)
    assert updated_rule.name == "Renamed Monitor"
    assert updated_rule.check_interval_minutes == 60


def test_prepare_alert_tool(tool_context):
    storage, _ = tool_context
    create_monitoring_rule(
        name="Monitor 1",
        source_url="mock://scholarship",
        natural_language_goal="Goal",
        criteria_categories=["Dates"],
    )
    rule_id = storage.list_rules()[0].id

    alert_res = prepare_alert(
        rule_id=rule_id,
        summary="Deadline moved earlier to April 10",
        impact_explanation="Directly affects submission window.",
        evidence=["Deadline: April 10, 2026"],
        previous_value="May 15, 2026",
        new_value="April 10, 2026",
    )
    assert "Alert recorded successfully" in alert_res
    events = storage.list_change_events(rule_id=rule_id)
    assert len(events) == 1
