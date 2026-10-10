"""Unit tests for background scheduled worker and Lambda handler."""

import os
import tempfile
import pytest
from src.scheduling.worker import run_scheduled_checks, lambda_handler
from src.storage.sqlite_store import SQLiteStorage
from src.monitoring.fetcher import SourceFetcher
from src.monitoring.service import MonitoringService
from src.schemas.monitoring import MonitoringRule, RuleStatus
from src.config import settings
from fixtures.scenarios import SCHOLARSHIP_BASELINE


@pytest.fixture
def worker_env():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_path = settings.local_db_path
    old_mode = settings.mode

    settings.local_db_path = path
    settings.mode = "demo"

    storage = SQLiteStorage(path)
    rule = MonitoringRule(
        name="Worker Test Rule",
        source_url="mock://foundation.org/scholarship",
        natural_language_goal="Watch deadline",
        criteria_categories=["Dates"],
        status=RuleStatus.ACTIVE,
        next_check_at="2026-01-01T00:00:00Z",  # In the past -> due!
    )
    storage.save_rule(rule)

    yield storage, path

    settings.local_db_path = old_path
    settings.mode = old_mode
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def test_run_scheduled_checks(worker_env):
    results = run_scheduled_checks(max_rules=10)
    assert results["evaluated_count"] >= 1
    assert "timestamp" in results
    assert len(results["details"]) >= 1


def test_lambda_handler(worker_env):
    event = {"source": "aws.events", "detail-type": "Scheduled Event"}
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert "evaluated_count" in response["body"]
