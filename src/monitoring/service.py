"""Monitoring Service Orchestration Layer for NowAware."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any, List

from src.schemas.monitoring import MonitoringRule, SourceSnapshot, RuleStatus, SourceType
from src.schemas.changes import ChangeEvent, ChangeAnalysisResult, ClassificationType
from src.storage.base import BaseStorage, AuthorizationError
from src.monitoring.fetcher import SourceFetcher, FetchError
from src.monitoring.parser import SourceParser
from src.monitoring.normalizer import (
    compute_content_hash,
    compute_change_fingerprint,
    normalize_whitespace,
)
from src.monitoring.diff_engine import DiffEngine
from src.monitoring.classifier import ChangeClassifier
from src.notifications.base import BaseNotificationProvider
from src.security.url_validator import URLSecurityError

logger = logging.getLogger(__name__)


class MonitoringService:
    """Core orchestration service for monitoring rules, checks, and alerts."""

    def __init__(
        self,
        storage: BaseStorage,
        fetcher: SourceFetcher,
        notification_provider: Optional[BaseNotificationProvider] = None,
    ):
        self.storage = storage
        self.fetcher = fetcher
        self.notification_provider = notification_provider

    def establish_baseline(self, rule: MonitoringRule, owner_id: Optional[str] = None) -> SourceSnapshot:
        """Retrieves source and saves initial baseline snapshot."""
        if owner_id and rule.owner_id != owner_id:
            raise AuthorizationError(f"User '{owner_id}' does not own rule '{rule.id}'.")

        raw_content, meta = self.fetcher.fetch(rule.source_url)
        normalized, title, parse_meta = SourceParser.parse(
            raw_content, source_type=rule.source_type, content_type=meta.get("content_type", "")
        )
        content_hash = compute_content_hash(normalized)

        now_iso = datetime.now(timezone.utc).isoformat()
        snapshot = SourceSnapshot(
            rule_id=rule.id,
            captured_at=now_iso,
            content_hash=content_hash,
            normalized_content=normalized,
            summary=f"Baseline: {title or 'Source Content'}",
            metadata=parse_meta,
        )

        rule.last_snapshot_id = snapshot.snapshot_id
        rule.last_checked_at = now_iso
        rule.next_check_at = (
            datetime.now(timezone.utc) + timedelta(minutes=rule.check_interval_minutes)
        ).isoformat()
        rule.error_message = None
        rule.consecutive_failures = 0

        self.storage.save_snapshot(snapshot)
        self.storage.save_rule(rule)
        return snapshot

    def check_rule(
        self,
        rule_id: str,
        simulated_content: Optional[str] = None,
        worker_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[ChangeEvent], Optional[str]]:
        """
        Executes a check against a monitoring rule.
        Enforces tenant authorization and atomic concurrency locks to prevent race conditions.
        Returns: (change_detected: bool, event: Optional[ChangeEvent], error_or_info: Optional[str])
        """
        # Step 0: Check existence and authorization
        rule = self.storage.get_rule(rule_id, owner_id=owner_id)
        if not rule:
            return False, None, f"Rule {rule_id} does not exist or access was denied."

        if rule.status == RuleStatus.PAUSED:
            return False, None, "Rule is currently paused."

        effective_worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

        # Step 0.5: Atomically acquire processing lease lock
        has_lock = self.storage.claim_rule_lock(rule_id, worker_id=effective_worker_id, lease_seconds=60)
        if not has_lock:
            logger.info(f"Rule {rule_id} is currently locked by another worker. Skipping concurrent execution.")
            return False, None, "Rule is currently claimed by another active worker. Skipping concurrent execution."

        try:
            latest_snapshot = self.storage.get_latest_snapshot(rule_id)
            now_dt = datetime.now(timezone.utc)
            now_iso = now_dt.isoformat()

            # Step 1: Fetch source (or use simulation if supplied)
            try:
                if simulated_content is not None:
                    raw_content = simulated_content
                    meta = {"content_type": "text/html", "is_simulated": True}
                else:
                    raw_content, meta = self.fetcher.fetch(rule.source_url)
            except (FetchError, URLSecurityError, Exception) as exc:
                # Preservation of baseline and failure logging
                rule.consecutive_failures += 1
                rule.error_message = str(exc)
                if rule.consecutive_failures >= 3:
                    rule.status = RuleStatus.ERROR
                rule.last_checked_at = now_iso
                rule.next_check_at = (now_dt + timedelta(minutes=rule.check_interval_minutes)).isoformat()
                self.storage.update_rule(rule)
                logger.warning(f"Monitoring check failed for rule '{rule.name}': {exc}")
                return False, None, f"Source retrieval failed: {exc}"

            # Step 2: Parse and normalize
            normalized, title, parse_meta = SourceParser.parse(
                raw_content, source_type=rule.source_type, content_type=meta.get("content_type", "")
            )
            current_hash = compute_content_hash(normalized)

            # If no baseline existed yet, establish it now
            if not latest_snapshot:
                snapshot = SourceSnapshot(
                    rule_id=rule.id,
                    captured_at=now_iso,
                    content_hash=current_hash,
                    normalized_content=normalized,
                    summary=f"Initial baseline ({title})",
                    metadata=parse_meta,
                )
                rule.last_snapshot_id = snapshot.snapshot_id
                rule.last_checked_at = now_iso
                rule.next_check_at = (now_dt + timedelta(minutes=rule.check_interval_minutes)).isoformat()
                rule.error_message = None
                rule.consecutive_failures = 0
                self.storage.save_snapshot(snapshot)
                self.storage.update_rule(rule)
                return False, None, "Initial baseline established. No prior version to compare."

            # Step 3: Exact Hash Comparison
            if current_hash == latest_snapshot.content_hash:
                rule.last_checked_at = now_iso
                rule.next_check_at = (now_dt + timedelta(minutes=rule.check_interval_minutes)).isoformat()
                rule.error_message = None
                rule.consecutive_failures = 0
                self.storage.update_rule(rule)
                return False, None, "Source is unchanged since previous baseline."

            # Step 4: Textual Diff
            diff_result = DiffEngine.compute_diff(
                latest_snapshot.normalized_content, normalized
            )

            if not diff_result.has_changed:
                rule.last_checked_at = now_iso
                rule.next_check_at = (now_dt + timedelta(minutes=rule.check_interval_minutes)).isoformat()
                rule.error_message = None
                self.storage.update_rule(rule)
                return False, None, "No substantive textual differences found."

            # Step 5: Classification
            analysis = ChangeClassifier.classify_diff(rule, diff_result, rule.source_url)

            # Step 6: Deduplication Check via Fingerprint
            change_diff_summary = f"{diff_result.isolated_previous}->{diff_result.isolated_new}:{analysis.summary}"
            fingerprint = compute_change_fingerprint(rule.id, change_diff_summary)

            is_duplicate = self.storage.is_duplicate_event(rule.id, fingerprint)

            # Update baseline snapshot with newly verified content
            new_snapshot = SourceSnapshot(
                rule_id=rule.id,
                captured_at=now_iso,
                content_hash=current_hash,
                normalized_content=normalized,
                summary=f"Updated: {analysis.summary[:80]}",
                metadata=parse_meta,
            )
            self.storage.save_snapshot(new_snapshot)

            rule.last_snapshot_id = new_snapshot.snapshot_id
            rule.last_checked_at = now_iso
            rule.next_check_at = (now_dt + timedelta(minutes=rule.check_interval_minutes)).isoformat()
            rule.error_message = None
            rule.consecutive_failures = 0
            self.storage.update_rule(rule)

            if is_duplicate:
                logger.info(f"Duplicate alert suppressed for rule '{rule.name}' with fingerprint {fingerprint[:8]}")
                return True, None, "Change detected but suppressed as duplicate alert."

            # Step 7: Create and Save Change Event with atomic insertion
            event = ChangeEvent(
                rule_id=rule.id,
                rule_name=rule.name,
                change_fingerprint=fingerprint,
                classification=analysis.classification,
                summary=analysis.summary,
                previous_value=analysis.previous_value,
                new_value=analysis.new_value,
                impact_explanation=analysis.impact_explanation,
                evidence=analysis.evidence,
                source_url=rule.source_url,
                confidence=analysis.confidence,
                recommended_action=analysis.recommended_action,
                should_notify=analysis.should_notify,
                notification_sent=False,
                read=False,
            )

            # Atomic save prevents race condition duplicates
            inserted = self.storage.save_change_event(event)
            if not inserted:
                logger.info(f"Concurrent duplicate event suppressed during atomic insert for rule '{rule.name}'.")
                return True, None, "Change detected but suppressed as duplicate alert."

            # Dispatch Notification only if atomic insert succeeded
            if event.should_notify and self.notification_provider:
                notify_res = self.notification_provider.send_alert(rule, event)
                if notify_res.get("success"):
                    event.notification_sent = True

            return True, event, f"Change detected: {analysis.classification.value}"

        finally:
            # Always release lock
            self.storage.release_rule_lock(rule_id, worker_id=effective_worker_id)
