"""Custom Strands Agent Tools for NowAware."""

import json
from typing import Dict, Any, List, Optional
from strands import tool

from src.security.url_validator import validate_url, URLSecurityError
from src.monitoring.fetcher import SourceFetcher, FetchError
from src.monitoring.parser import SourceParser
from src.monitoring.normalizer import compute_content_hash, compute_change_fingerprint
from src.monitoring.diff_engine import DiffEngine
from src.monitoring.classifier import ChangeClassifier
from src.schemas.monitoring import MonitoringRule, SourceSnapshot, RuleStatus, SourceType
from src.schemas.changes import (
    ChangeEvent,
    ChangeAnalysisResult,
    ClassificationType,
    ConfidenceLevel,
)
from src.storage.base import BaseStorage, AuthorizationError

# Storage reference set dynamically or by factory
_active_storage: Optional[BaseStorage] = None
_active_fetcher: Optional[SourceFetcher] = None
_active_owner_id: str = "default-user"


def set_global_context(storage: BaseStorage, fetcher: SourceFetcher, owner_id: str = "default-user"):
    """Sets active storage, fetcher, and tenant owner dependencies for agent tools."""
    global _active_storage, _active_fetcher, _active_owner_id
    _active_storage = storage
    _active_fetcher = fetcher
    _active_owner_id = owner_id


def get_owner_id() -> str:
    return _active_owner_id


def get_storage() -> BaseStorage:
    if _active_storage is None:
        from src.storage.sqlite_store import SQLiteStorage
        from src.config import settings
        return SQLiteStorage(settings.local_db_path)
    return _active_storage


def get_fetcher() -> SourceFetcher:
    if _active_fetcher is None:
        return SourceFetcher()
    return _active_fetcher


@tool
def inspect_source(url: str) -> str:
    """
    Retrieves and summarizes the content of an approved public URL or feed.
    Validates URL safety against SSRF attacks.
    """
    try:
        fetcher = get_fetcher()
        raw_content, meta = fetcher.fetch(url)
        normalized, title, parse_meta = SourceParser.parse(raw_content)
        summary = (
            f"Successfully inspected source: '{title}' ({url})\n"
            f"Content Length: {len(normalized)} characters ({parse_meta.get('line_count', 0)} lines)\n"
            f"Top Excerpt:\n{normalized[:500]}..."
        )
        return summary
    except (URLSecurityError, FetchError) as e:
        return f"Source inspection failed: {e}"
    except Exception as e:
        return f"Unexpected error during source inspection: {e}"


@tool
def create_monitoring_rule(
    name: str,
    source_url: str,
    natural_language_goal: str,
    criteria_categories: List[str],
    specific_instructions: str = "",
    check_interval_minutes: int = 30,
) -> str:
    """
    Validates and creates a new monitoring rule and captures its initial baseline.
    """
    storage = get_storage()
    fetcher = get_fetcher()

    # Validate URL
    allow_mock = source_url.startswith("mock://") or source_url.startswith("fixture://")
    try:
        is_safe, _ = validate_url(source_url, allow_mock_schemes=allow_mock)
        if not is_safe:
            return f"Error: URL {source_url} failed security validation."
    except Exception as e:
        return f"URL validation error: {e}"

    rule = MonitoringRule(
        name=name,
        source_url=source_url,
        owner_id=get_owner_id(),
        natural_language_goal=natural_language_goal,
        criteria_categories=criteria_categories,
        specific_instructions=specific_instructions,
        check_interval_minutes=max(5, check_interval_minutes),
        status=RuleStatus.ACTIVE,
    )

    try:
        raw_content, meta = fetcher.fetch(source_url)
        normalized, title, parse_meta = SourceParser.parse(raw_content)
        content_hash = compute_content_hash(normalized)

        snapshot = SourceSnapshot(
            rule_id=rule.id,
            content_hash=content_hash,
            normalized_content=normalized,
            summary=f"Initial baseline captured ({title or 'Source'})",
            metadata=parse_meta,
        )

        rule.last_snapshot_id = snapshot.snapshot_id
        storage.save_rule(rule)
        storage.save_snapshot(snapshot)

        return (
            f"Successfully created monitoring rule '{rule.name}' (ID: {rule.id}) with initial baseline established. "
            f"Content hash: {content_hash[:12]}."
        )
    except Exception as e:
        return f"Failed to capture baseline and create rule: {e}"


@tool
def get_monitoring_rule(rule_id: str) -> str:
    """
    Retrieves configuration and current status of an existing monitoring rule by ID.
    """
    storage = get_storage()
    try:
        rule = storage.get_rule(rule_id, owner_id=get_owner_id())
    except AuthorizationError as e:
        return f"Authorization error: {e}"
    if not rule:
        return f"Monitoring rule with ID '{rule_id}' not found."
    return json.dumps(rule.to_dict(), indent=2)


@tool
def check_for_changes(rule_id: str) -> str:
    """
    Retrieves current content for a rule, compares against stored baseline, and returns detected differences.
    """
    storage = get_storage()
    fetcher = get_fetcher()

    rule = storage.get_rule(rule_id)
    if not rule:
        return f"Rule {rule_id} not found."

    latest_snapshot = storage.get_latest_snapshot(rule_id)
    if not latest_snapshot:
        return f"No baseline snapshot exists for rule {rule_id}. Please establish a baseline first."

    try:
        raw_content, meta = fetcher.fetch(rule.source_url)
        normalized, title, parse_meta = SourceParser.parse(raw_content)
        current_hash = compute_content_hash(normalized)

        if current_hash == latest_snapshot.content_hash:
            return "No changes detected. The current source content matches baseline hash."

        diff_result = DiffEngine.compute_diff(
            latest_snapshot.normalized_content, normalized
        )

        analysis = ChangeClassifier.classify_diff(rule, diff_result, rule.source_url)
        return json.dumps(analysis.model_dump(), indent=2)
    except Exception as e:
        return f"Failed to check source: {e}"


@tool
def classify_change(
    rule_id: str,
    removed_text: str,
    added_text: str,
) -> str:
    """
    Evaluates whether specific textual differences matter to the user's criteria.
    """
    storage = get_storage()
    rule = storage.get_rule(rule_id)
    if not rule:
        return f"Rule {rule_id} not found."

    diff_result = DiffEngine.compute_diff(removed_text, added_text)
    analysis = ChangeClassifier.classify_diff(rule, diff_result, rule.source_url)
    return json.dumps(analysis.model_dump(), indent=2)


@tool
def get_monitor_history(rule_id: str) -> str:
    """
    Retrieves earlier snapshots and change events/alerts for a given rule.
    """
    storage = get_storage()
    events = storage.list_change_events(rule_id=rule_id, limit=10)
    snapshots = storage.list_snapshots(rule_id=rule_id, limit=5)

    summary = {
        "rule_id": rule_id,
        "recent_snapshots_count": len(snapshots),
        "recent_alerts": [
            {
                "event_id": e.event_id,
                "detected_at": e.detected_at,
                "classification": e.classification.value,
                "summary": e.summary,
                "should_notify": e.should_notify,
            }
            for e in events
        ],
    }
    return json.dumps(summary, indent=2)


@tool
def prepare_alert(
    rule_id: str,
    summary: str,
    impact_explanation: str,
    evidence: List[str],
    previous_value: Optional[str] = None,
    new_value: Optional[str] = None,
    confidence: str = "high",
    recommended_action: str = "Review update",
) -> str:
    """
    Stores an evidence-backed alert event for the user.
    """
    storage = get_storage()
    rule = storage.get_rule(rule_id)
    if not rule:
        return f"Rule {rule_id} not found."

    fingerprint = compute_change_fingerprint(rule_id, f"{previous_value}->{new_value}:{summary}")

    # Check deduplication
    if storage.is_duplicate_event(rule_id, fingerprint):
        return "Duplicate alert suppressed. A matching alert has already been recorded."

    conf_enum = ConfidenceLevel.HIGH
    try:
        conf_enum = ConfidenceLevel(confidence.lower())
    except ValueError:
        pass

    event = ChangeEvent(
        rule_id=rule.id,
        rule_name=rule.name,
        change_fingerprint=fingerprint,
        classification=ClassificationType.MEANINGFUL,
        summary=summary,
        previous_value=previous_value,
        new_value=new_value,
        impact_explanation=impact_explanation,
        evidence=evidence,
        source_url=rule.source_url,
        confidence=conf_enum,
        recommended_action=recommended_action,
        should_notify=True,
    )

    storage.save_change_event(event)
    return f"Alert recorded successfully. Event ID: {event.event_id}."


@tool
def pause_monitor(rule_id: str) -> str:
    """Pauses scheduled checks for a monitor."""
    storage = get_storage()
    try:
        rule = storage.get_rule(rule_id, owner_id=get_owner_id())
    except AuthorizationError as e:
        return f"Authorization error: {e}"
    if not rule:
        return f"Rule {rule_id} not found."
    rule.status = RuleStatus.PAUSED
    storage.update_rule(rule, owner_id=get_owner_id())
    return f"Monitor '{rule.name}' has been paused."


@tool
def update_monitor(
    rule_id: str,
    name: Optional[str] = None,
    natural_language_goal: Optional[str] = None,
    specific_instructions: Optional[str] = None,
    check_interval_minutes: Optional[int] = None,
) -> str:
    """Updates parameters of an existing monitoring rule."""
    storage = get_storage()
    try:
        rule = storage.get_rule(rule_id, owner_id=get_owner_id())
    except AuthorizationError as e:
        return f"Authorization error: {e}"
    if not rule:
        return f"Rule {rule_id} not found."

    if name:
        rule.name = name
    if natural_language_goal:
        rule.natural_language_goal = natural_language_goal
    if specific_instructions is not None:
        rule.specific_instructions = specific_instructions
    if check_interval_minutes:
        rule.check_interval_minutes = max(5, check_interval_minutes)

    storage.update_rule(rule, owner_id=get_owner_id())
    return f"Monitor '{rule.name}' updated successfully."


ALL_TOOLS = [
    inspect_source,
    create_monitoring_rule,
    get_monitoring_rule,
    check_for_changes,
    classify_change,
    get_monitor_history,
    prepare_alert,
    pause_monitor,
    update_monitor,
]
