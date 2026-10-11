"""Concurrency and race-condition tests for NowAware.

Verifies:
1. Atomic rule lock claiming/releasing under multi-threaded contention.
2. Duplicate alert prevention under concurrent event writes (UNIQUE constraint / conditional insert).
3. Concurrent service check_rule execution where only one worker acquires the lease.
"""

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest

from src.schemas.monitoring import MonitoringRule, SourceSnapshot
from src.schemas.changes import ChangeEvent, ClassificationType, ConfidenceLevel
from src.storage.sqlite_store import SQLiteStorage
from src.monitoring.service import MonitoringService
from src.monitoring.fetcher import SourceFetcher


@pytest.fixture
def concurrency_storage():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage = SQLiteStorage(db_path=path)
    yield storage
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def test_concurrent_rule_lock_claim(concurrency_storage):
    """
    Ensures that when N concurrent threads attempt to claim a lease lock on the same rule,
    exactly ONE thread succeeds and (N-1) fail.
    """
    rule = MonitoringRule(
        name="Concurrent Rule",
        source_url="mock://example.com/test",
        owner_id="tenant-1",
        natural_language_goal="Test locking",
    )
    concurrency_storage.save_rule(rule)

    num_threads = 10
    results = []

    def try_claim(worker_idx):
        worker_id = f"worker-{worker_idx}"
        claimed = concurrency_storage.claim_rule_lock(rule.id, worker_id, lease_seconds=30)
        return claimed

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(try_claim, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    # Exactly one worker must have claimed the lock
    assert results.count(True) == 1
    assert results.count(False) == num_threads - 1

    # Find which worker succeeded
    successful_idx = results.index(True)
    successful_worker = f"worker-{successful_idx}"

    # Releasing the lock should allow claiming again
    concurrency_storage.release_rule_lock(rule.id, successful_worker)
    reclaimed = concurrency_storage.claim_rule_lock(rule.id, "worker-next", lease_seconds=30)
    assert reclaimed is True


def test_concurrent_duplicate_alert_insertion(concurrency_storage):
    """
    Ensures that under concurrent processing, multiple workers inserting the same
    (rule_id, change_fingerprint) result in exactly 1 saved event, with all duplicate
    attempts returning False without throwing an uncaught exception.
    """
    rule = MonitoringRule(
        name="Concurrent Alert Rule",
        source_url="mock://example.com/items",
        owner_id="tenant-1",
        natural_language_goal="Test deduplication",
    )
    concurrency_storage.save_rule(rule)

    fingerprint = "fp_concurrent_exact_match_999"
    num_threads = 8

    def try_insert_event(idx):
        event = ChangeEvent(
            rule_id=rule.id,
            rule_name=rule.name,
            change_fingerprint=fingerprint,
            classification=ClassificationType.MEANINGFUL,
            summary=f"Price dropped from worker {idx}",
            impact_explanation="Price dropped by $20, relevant to budget criteria.",
            recommended_action="Purchase item at discount",
            evidence=["$100 -> $80"],
            source_url=rule.source_url,
            confidence=ConfidenceLevel.HIGH,
            should_notify=True,
        )
        saved = concurrency_storage.save_change_event(event)
        return saved

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(try_insert_event, i) for i in range(num_threads)]
        insert_results = [f.result() for f in futures]

    # Exactly one insert must succeed, rest must return False
    assert insert_results.count(True) == 1
    assert insert_results.count(False) == num_threads - 1

    # Verify database table has exactly 1 record
    all_events = concurrency_storage.list_change_events(rule_id=rule.id)
    assert len(all_events) == 1
    assert all_events[0].change_fingerprint == fingerprint


def test_concurrent_service_check_rule_skips_locked_rule(concurrency_storage):
    """
    Verifies that MonitoringService.check_rule() respects active locks and skips execution
    if another worker has already leased the rule.
    """
    rule = MonitoringRule(
        name="Service Concurrent Check",
        source_url="mock://store.com/price",
        owner_id="tenant-1",
        natural_language_goal="Monitor price changes",
    )
    concurrency_storage.save_rule(rule)

    mock_sources = {
        "mock://store.com/price": "Item price is $100. Available now.",
    }
    fetcher = SourceFetcher(mock_sources=mock_sources)
    service = MonitoringService(storage=concurrency_storage, fetcher=fetcher)

    # Establish baseline
    service.establish_baseline(rule, owner_id="tenant-1")

    # Manually lock the rule as if Worker A is actively running
    locked = concurrency_storage.claim_rule_lock(rule.id, "worker-in-flight", lease_seconds=60)
    assert locked is True

    # Now Worker B tries to check the rule
    changed_b, event_b, info_b = service.check_rule(rule.id, owner_id="tenant-1")
    assert changed_b is False
    assert event_b is None
    assert "claimed by another active worker" in info_b

    # Release lock
    concurrency_storage.release_rule_lock(rule.id, "worker-in-flight")

    # Now check_rule should proceed
    changed_c, event_c, info_c = service.check_rule(rule.id, owner_id="tenant-1")
    assert changed_c is False
    assert event_c is None
    assert "unchanged" in info_c.lower()
