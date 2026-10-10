"""Amazon DynamoDB Storage Implementation for AWS Mode."""

import json
from typing import List, Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError
from src.storage.base import BaseStorage
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

    def get_rule(self, rule_id: str) -> Optional[MonitoringRule]:
        try:
            resp = self.rules_table.get_item(Key={"id": rule_id})
            item = resp.get("Item")
            if not item:
                return None
            return MonitoringRule(**item)
        except ClientError:
            return None

    def list_rules(self, owner_id: str = "default-user") -> List[MonitoringRule]:
        try:
            resp = self.rules_table.scan()
            items = resp.get("Items", [])
            rules = [MonitoringRule(**item) for item in items if item.get("owner_id") == owner_id]
            rules.sort(key=lambda r: r.created_at, reverse=True)
            return rules
        except ClientError:
            return []

    def update_rule(self, rule: MonitoringRule) -> None:
        self.save_rule(rule)

    def delete_rule(self, rule_id: str) -> None:
        try:
            self.rules_table.delete_item(Key={"id": rule_id})
        except ClientError:
            pass

    def save_snapshot(self, snapshot: SourceSnapshot) -> None:
        item = snapshot.model_dump()
        # DynamoDB item limit is 400KB. Ensure normalized content does not exceed 300KB
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

    def save_change_event(self, event: ChangeEvent) -> None:
        item = event.model_dump()
        self.alerts_table.put_item(Item=item)

    def list_change_events(
        self,
        rule_id: Optional[str] = None,
        only_unread: bool = False,
        limit: int = 50,
    ) -> List[ChangeEvent]:
        try:
            resp = self.alerts_table.scan()
            items = resp.get("Items", [])
            filtered = []
            for item in items:
                if item.get("dismissed", False):
                    continue
                if rule_id and item.get("rule_id") != rule_id:
                    continue
                if only_unread and item.get("read", False):
                    continue
                filtered.append(ChangeEvent(**item))
            filtered.sort(key=lambda e: e.detected_at, reverse=True)
            return filtered[:limit]
        except ClientError:
            return []

    def get_change_event(self, event_id: str) -> Optional[ChangeEvent]:
        try:
            resp = self.alerts_table.get_item(Key={"event_id": event_id})
            item = resp.get("Item")
            if not item:
                return None
            return ChangeEvent(**item)
        except ClientError:
            return None

    def mark_event_read(self, event_id: str, read: bool = True) -> None:
        try:
            self.alerts_table.update_item(
                Key={"event_id": event_id},
                UpdateExpression="SET #r = :val",
                ExpressionAttributeNames={"#r": "read"},
                ExpressionAttributeValues={":val": read},
            )
        except ClientError:
            pass

    def dismiss_event(self, event_id: str) -> None:
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

    def get_stats(self) -> Dict[str, int]:
        rules = self.list_rules()
        events = self.list_change_events(limit=200)

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
