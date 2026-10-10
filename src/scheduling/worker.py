"""AWS Lambda Monitoring Handler and Scheduled Background Worker."""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, List

from src.config import settings
from src.schemas.monitoring import RuleStatus
from src.storage.base import BaseStorage
from src.monitoring.fetcher import SourceFetcher
from src.monitoring.service import MonitoringService
from src.notifications.ses_email import SESEmailProvider

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def get_worker_service() -> MonitoringService:
    """Instantiates service according to active environment mode."""
    if settings.is_aws_mode:
        from src.storage.dynamodb_store import DynamoDBStorage
        storage = DynamoDBStorage()
    else:
        from src.storage.sqlite_store import SQLiteStorage
        storage = SQLiteStorage(settings.local_db_path)

    fetcher = SourceFetcher()
    notifier = SESEmailProvider()
    return MonitoringService(storage=storage, fetcher=fetcher, notification_provider=notifier)


def run_scheduled_checks(max_rules: int = 25) -> Dict[str, Any]:
    """
    Core batch processing logic invoked by Lambda or background runner.
    Finds active rules due for checking, processes them sequentially or boundedly.
    """
    service = get_worker_service()
    now_iso = datetime.now(timezone.utc).isoformat()

    all_rules = service.storage.list_rules()
    due_rules = []

    for rule in all_rules:
        if rule.status != RuleStatus.ACTIVE:
            continue
        # If never checked or next_check_at is now or in the past
        if not rule.next_check_at or rule.next_check_at <= now_iso:
            due_rules.append(rule)

    due_rules = due_rules[:max_rules]
    logger.info(f"Scheduled worker found {len(due_rules)} due rules to evaluate (out of {len(all_rules)} total).")

    results = {
        "timestamp": now_iso,
        "evaluated_count": len(due_rules),
        "changes_detected": 0,
        "alerts_dispatched": 0,
        "errors": 0,
        "details": [],
    }

    for rule in due_rules:
        rule_res = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "status": "success",
            "message": "",
        }
        try:
            has_changed, event, message = service.check_rule(rule.id)
            if has_changed and event:
                results["changes_detected"] += 1
                if event.should_notify:
                    results["alerts_dispatched"] += 1
                rule_res["message"] = f"Detected: {event.summary}"
            else:
                rule_res["message"] = message or "Unchanged"
        except Exception as e:
            results["errors"] += 1
            rule_res["status"] = "error"
            rule_res["message"] = str(e)
            logger.error(f"Error checking rule {rule.id}: {e}")

        results["details"].append(rule_res)

    return results


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda entrypoint triggered by Amazon EventBridge scheduled rule.
    """
    logger.info("NowAware Lambda Scheduled Worker invoked by EventBridge.")
    result = run_scheduled_checks()
    return {
        "statusCode": 200,
        "body": result,
    }


if __name__ == "__main__":
    # Local CLI test invocation
    res = run_scheduled_checks()
    print("Execution complete:", res)
