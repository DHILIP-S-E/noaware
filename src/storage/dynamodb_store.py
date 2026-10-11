"""Amazon DynamoDB Storage Implementation with Authorization Boundaries and Concurrency Controls."""

import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError
from src.storage.base import BaseStorage, AuthorizationError
from src.schemas.monitoring import MonitoringRule, SourceSnapshot, RuleStatus, SourceType
from src.schemas.changes import ChangeEvent, ClassificationType, ConfidenceLevel
from src.config import settings


class DynamoDBStorage(BaseStorage):
    """DynamoDB repository for rules, snapshots, and change alerts."""

    def __init__(
        self,
        rules_table_name: Optional[str] = None,
        snapshots_table_name: Optional[str] = None,
        alerts_table_name: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        self.region = region_name or settings.aws_region
        self.rules_table_name = rules_table_name or settings.dynamodb_rules_table
        self.snapshots_table_name = snapshots_table_name or settings.dynamodb_snapshots_table
        self.alerts_table_name = alerts_table_name or settings.dynamodb_alerts_table

        self.dynamodb = boto3.resource("dynamodb", region_name=self.region)
        self.rules_table = self.dynamodb.Table(self.rules_table_name)
        self.snapshots_table = self.dynamodb.Table(self.snapshots_table_name)
        self.alerts_table = self.dynamodb.Table(self.alerts_table_name)

    def save_rule(self, rule: MonitoringRule) -> None:
        item = rule.model_dump()
        self.rules_table.put_item(Item=item)

    def get_rule(self, rule_id: str, owner_id: Optional[str] = None) -> Optional[MonitoringRule]:
        try:
            resp = self.rules_table.get_item(Key={"id": rule_id})
            item = resp.get("Item")
            if not item:
                return None
            rule = MonitoringRule(**item)
            if owner_id and rule.owner_id != owner_id:
                raise AuthorizationError(
                    f"Access denied: user '{owner_id}' does not own rule '{rule_id}'."
                )
            return rule
        except ClientError:
            return None

    def list_rules(self, owner_id: Optional[str] = None) -> List[MonitoringRule]:
        try:
            resp = self.rules_table.scan()
            items = resp.get("Items", [])
            rules = [MonitoringRule(**item) for item in items]
            if owner_id:
                rules = [r for r in rules if r.owner_id == owner_id]
            rules.sort(key=lambda r: r.created_at, reverse=True)
            return rules
        except ClientError:
            return []

    def update_rule(self, rule: MonitoringRule, owner_id: Optional[str] = None) -> None:
        if owner_id:
            existing = self.get_rule(rule.id, owner_id=owner_id)
            if not existing:
                raise AuthorizationError(f"Rule '{rule.id}' not found for user '{owner_id}'.")
            if rule.owner_id != owner_id:
                raise AuthorizationError("Cannot reassign rule owner_id.")
        self.save_rule(rule)

    def delete_rule(self, rule_id: str, owner_id: Optional[str] = None) -> None:
        if owner_id:
            existing = self.get_rule(rule_id, owner_id=owner_id)
            if not existing:
                raise AuthorizationError(f"Rule '{rule_id}' not found for user '{owner_id}'.")
        try:
            self.rules_table.delete_item(Key={"id": rule_id})
        except ClientError:
            pass

    def claim_rule_lock(self, rule_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        """Atomically claims a lease lock on the rule in DynamoDB via conditional update."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()

        try:
            self.rules_table.update_item(
                Key={"id": rule_id},
                UpdateExpression="SET locked_until = :lu, locked_by = :lb",
                ConditionExpression="attribute_not_exists(locked_until) OR locked_until < :now",
                ExpressionAttributeValues={
                    ":lu": lease_until,
                    ":lb": worker_id,
                    ":now": now_iso,
                },
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            return False

    def release_rule_lock(self, rule_id: str, worker_id: str) -> None:
        try:
            self.rules_table.update_item(
                Key={"id": rule_id},
                UpdateExpression="REMOVE locked_until, locked_by",
                ConditionExpression="locked_by = :lb",
                ExpressionAttributeValues={":lb": worker_id},
            )
        except ClientError:
            pass

    def save_snapshot(self, snapshot: SourceSnapshot) -> None:
        item = snapshot.model_dump()
        if len(item["normalized_content"]) > 300000:
            item["normalized_content"] = item["normalized_content"][:300000] + "\n[Content truncated for storage size]"
        self.snapshots_table.put_item(Item=item)

    def get_latest_snapshot(self, rule_id: str) -> Optional[SourceSnapshot]:
        try:
            resp = self.snapshots_table.scan(
                FilterExpression="rule_id = :rid",
                ExpressionAttributeValues={":rid": rule_id},
            )
            items = resp.get("Items", [])
            if not items:
                return None
            items.sort(key=lambda s: s.get("captured_at", ""), reverse=True)
            return SourceSnapshot(**items[0])
        except ClientError:
            return None

    def list_snapshots(self, rule_id: str, limit: int = 10) -> List[SourceSnapshot]:
        try:
            resp = self.snapshots_table.scan(
                FilterExpression="rule_id = :rid",
                ExpressionAttributeValues={":rid": rule_id},
            )
            items = resp.get("Items", [])
            items.sort(key=lambda s: s.get("captured_at", ""), reverse=True)
            return [SourceSnapshot(**item) for item in items[:limit]]
        except ClientError:
            return []

    def save_change_event(self, event: ChangeEvent) -> bool:
        """Atomically saves change event ensuring fingerprint deduplication."""
        if self.is_duplicate_event(event.rule_id, event.change_fingerprint):
            return False

        item = event.model_dump()
        try:
            self.alerts_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(event_id)",
            )
            return True
        except ClientError:
            return False

    def list_change_events(
        self,
        rule_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        only_unread: bool = False,
        limit: int = 50,
    ) -> List[ChangeEvent]:
        try:
            resp = self.alerts_table.scan()
            items = resp.get("Items", [])
            events = [ChangeEvent(**item) for item in items if not item.get("dismissed", False)]

            if rule_id:
                events = [e for e in events if e.rule_id == rule_id]

            if owner_id:
                user_rules = {r.id for r in self.list_rules(owner_id=owner_id)}
                events = [e for e in events if e.rule_id in user_rules]

            if only_unread:
                events = [e for e in events if not e.read]

            events.sort(key=lambda e: e.detected_at, reverse=True)
            return events[:limit]
        except ClientError:
            return []

    def get_change_event(self, event_id: str, owner_id: Optional[str] = None) -> Optional[ChangeEvent]:
        try:
            resp = self.alerts_table.get_item(Key={"event_id": event_id})
            item = resp.get("Item")
            if not item:
                return None
            event = ChangeEvent(**item)
            if owner_id:
                rule = self.get_rule(event.rule_id, owner_id=owner_id)
                if not rule:
                    raise AuthorizationError(f"Event '{event_id}' does not belong to user '{owner_id}'.")
            return event
        except ClientError:
            return None

    def mark_event_read(self, event_id: str, read: bool = True, owner_id: Optional[str] = None) -> None:
        if owner_id:
            ev = self.get_change_event(event_id, owner_id=owner_id)
            if not ev:
                raise AuthorizationError(f"Event '{event_id}' does not belong to user '{owner_id}'.")

        try:
            self.alerts_table.update_item(
                Key={"event_id": event_id},
                UpdateExpression="SET #r = :val",
                ExpressionAttributeNames={"#r": "read"},
                ExpressionAttributeValues={":val": read},
            )
        except ClientError:
            pass

    def dismiss_event(self, event_id: str, owner_id: Optional[str] = None) -> None:
        if owner_id:
            ev = self.get_change_event(event_id, owner_id=owner_id)
            if not ev:
                raise AuthorizationError(f"Event '{event_id}' does not belong to user '{owner_id}'.")

        try:
            self.alerts_table.update_item(
                Key={"event_id": event_id},
                UpdateExpression="SET dismissed = :val",
                ExpressionAttributeValues={":val": True},
            )
        except ClientError:
            pass

    def is_duplicate_event(self, rule_id: str, change_fingerprint: str) -> bool:
        try:
            resp = self.alerts_table.scan(
                FilterExpression="rule_id = :rid AND change_fingerprint = :fp",
                ExpressionAttributeValues={":rid": rule_id, ":fp": change_fingerprint},
            )
            return len(resp.get("Items", [])) > 0
        except ClientError:
            return False

    def get_stats(self, owner_id: Optional[str] = None) -> Dict[str, int]:
        rules = self.list_rules(owner_id=owner_id)
        events = self.list_change_events(owner_id=owner_id, limit=200)

        active = sum(1 for r in rules if r.status == RuleStatus.ACTIVE)
        errors = sum(1 for r in rules if r.status == RuleStatus.ERROR)
        meaningful = sum(1 for e in events if e.classification == ClassificationType.MEANINGFUL)
        unread = sum(1 for e in events if not e.read and e.should_notify)

        return {
            "active_rules": active,
            "meaningful_changes": meaningful,
            "unread_alerts": unread,
            "needing_attention": errors,
        }
