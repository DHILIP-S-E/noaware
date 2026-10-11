"""SQLite Storage Implementation with Authorization Boundaries and Atomic Concurrency Controls."""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

from src.storage.base import BaseStorage, AuthorizationError
from src.schemas.monitoring import MonitoringRule, SourceSnapshot, RuleStatus, SourceType
from src.schemas.changes import ChangeEvent, ClassificationType, ConfidenceLevel


class SQLiteStorage(BaseStorage):
    """Local SQLite repository for rules, snapshots, and change alerts."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for high concurrency
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Rules table with lock columns
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monitoring_rules (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    natural_language_goal TEXT NOT NULL,
                    criteria_categories TEXT NOT NULL,
                    specific_instructions TEXT,
                    check_interval_minutes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    next_check_at TEXT,
                    last_snapshot_id TEXT,
                    error_message TEXT,
                    consecutive_failures INTEGER DEFAULT 0,
                    is_demo_rule INTEGER DEFAULT 0,
                    locked_until TEXT,
                    locked_by TEXT
                )
            """)

            # Snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS source_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    normalized_content TEXT NOT NULL,
                    summary TEXT,
                    metadata_json TEXT,
                    FOREIGN KEY(rule_id) REFERENCES monitoring_rules(id) ON DELETE CASCADE
                )
            """)

            # Change Events table with UNIQUE(rule_id, change_fingerprint) constraint
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS change_events (
                    event_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    rule_name TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    change_fingerprint TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    previous_value TEXT,
                    new_value TEXT,
                    impact_explanation TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    should_notify INTEGER NOT NULL,
                    notification_sent INTEGER NOT NULL,
                    read INTEGER DEFAULT 0,
                    dismissed INTEGER DEFAULT 0,
                    UNIQUE(rule_id, change_fingerprint),
                    FOREIGN KEY(rule_id) REFERENCES monitoring_rules(id) ON DELETE CASCADE
                )
            """)

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rules_owner ON monitoring_rules(owner_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_rule ON source_snapshots(rule_id, captured_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_rule ON change_events(rule_id, detected_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_fingerprint ON change_events(rule_id, change_fingerprint)")

            # Automatic column migration for existing databases
            cursor.execute("PRAGMA table_info(monitoring_rules)")
            existing_cols = {col[1] for col in cursor.fetchall()}
            if "locked_until" not in existing_cols:
                cursor.execute("ALTER TABLE monitoring_rules ADD COLUMN locked_until TEXT")
            if "locked_by" not in existing_cols:
                cursor.execute("ALTER TABLE monitoring_rules ADD COLUMN locked_by TEXT")

            conn.commit()

    def save_rule(self, rule: MonitoringRule) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO monitoring_rules (
                    id, owner_id, name, source_url, source_type,
                    natural_language_goal, criteria_categories, specific_instructions,
                    check_interval_minutes, status, created_at, last_checked_at,
                    next_check_at, last_snapshot_id, error_message, consecutive_failures,
                    is_demo_rule, locked_until, locked_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rule.id,
                rule.owner_id,
                rule.name,
                rule.source_url,
                rule.source_type.value,
                rule.natural_language_goal,
                json.dumps(rule.criteria_categories),
                rule.specific_instructions,
                rule.check_interval_minutes,
                rule.status.value,
                rule.created_at,
                rule.last_checked_at,
                rule.next_check_at,
                rule.last_snapshot_id,
                rule.error_message,
                rule.consecutive_failures,
                1 if rule.is_demo_rule else 0,
                rule.locked_until,
                rule.locked_by,
            ))
            conn.commit()

    def get_rule(self, rule_id: str, owner_id: Optional[str] = None) -> Optional[MonitoringRule]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM monitoring_rules WHERE id = ?", (rule_id,))
            row = cursor.fetchone()
            if not row:
                return None
            rule = self._row_to_rule(row)
            if owner_id and rule.owner_id != owner_id:
                raise AuthorizationError(
                    f"Access denied: user '{owner_id}' does not own rule '{rule_id}'."
                )
            return rule

    def list_rules(self, owner_id: Optional[str] = None) -> List[MonitoringRule]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if owner_id:
                cursor.execute(
                    "SELECT * FROM monitoring_rules WHERE owner_id = ? ORDER BY created_at DESC",
                    (owner_id,),
                )
            else:
                cursor.execute("SELECT * FROM monitoring_rules ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self._row_to_rule(r) for r in rows]

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

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM change_events WHERE rule_id = ?", (rule_id,))
            cursor.execute("DELETE FROM source_snapshots WHERE rule_id = ?", (rule_id,))
            cursor.execute("DELETE FROM monitoring_rules WHERE id = ?", (rule_id,))
            conn.commit()

    def claim_rule_lock(self, rule_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        """Atomically claims lease lock on rule in SQLite using atomic UPDATE with lock expiry."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE monitoring_rules
                SET locked_until = ?, locked_by = ?
                WHERE id = ? AND (locked_until IS NULL OR locked_until < ?)
            """, (lease_until, worker_id, rule_id, now_iso))
            conn.commit()
            return cursor.rowcount > 0

    def release_rule_lock(self, rule_id: str, worker_id: str) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE monitoring_rules
                SET locked_until = NULL, locked_by = NULL
                WHERE id = ? AND locked_by = ?
            """, (rule_id, worker_id))
            conn.commit()

    def save_snapshot(self, snapshot: SourceSnapshot) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO source_snapshots (
                    snapshot_id, rule_id, captured_at, content_hash,
                    normalized_content, summary, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.snapshot_id,
                snapshot.rule_id,
                snapshot.captured_at,
                snapshot.content_hash,
                snapshot.normalized_content,
                snapshot.summary,
                json.dumps(snapshot.metadata),
            ))
            conn.commit()

    def get_latest_snapshot(self, rule_id: str) -> Optional[SourceSnapshot]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM source_snapshots
                WHERE rule_id = ?
                ORDER BY captured_at DESC LIMIT 1
            """, (rule_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    def list_snapshots(self, rule_id: str, limit: int = 10) -> List[SourceSnapshot]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM source_snapshots
                WHERE rule_id = ?
                ORDER BY captured_at DESC LIMIT ?
            """, (rule_id, limit))
            rows = cursor.fetchall()
            return [self._row_to_snapshot(r) for r in rows]

    def save_change_event(self, event: ChangeEvent) -> bool:
        """
        Atomically saves change event. Returns True if inserted, False if duplicate rejected.
        Enforces UNIQUE(rule_id, change_fingerprint).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO change_events (
                        event_id, rule_id, rule_name, detected_at, change_fingerprint,
                        classification, summary, previous_value, new_value,
                        impact_explanation, evidence_json, source_url, confidence,
                        recommended_action, should_notify, notification_sent,
                        read, dismissed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.rule_id,
                    event.rule_name,
                    event.detected_at,
                    event.change_fingerprint,
                    event.classification.value,
                    event.summary,
                    event.previous_value,
                    event.new_value,
                    event.impact_explanation,
                    json.dumps(event.evidence),
                    event.source_url,
                    event.confidence.value,
                    event.recommended_action,
                    1 if event.should_notify else 0,
                    1 if event.notification_sent else 0,
                    1 if event.read else 0,
                    1 if event.dismissed else 0,
                ))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Concurrent or duplicate event with matching (rule_id, change_fingerprint)
                return False

    def list_change_events(
        self,
        rule_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        only_unread: bool = False,
        limit: int = 50,
    ) -> List[ChangeEvent]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT e.* FROM change_events e
                JOIN monitoring_rules r ON e.rule_id = r.id
                WHERE e.dismissed = 0
            """
            params: List[Any] = []
            if rule_id:
                query += " AND e.rule_id = ?"
                params.append(rule_id)
            if owner_id:
                query += " AND r.owner_id = ?"
                params.append(owner_id)
            if only_unread:
                query += " AND e.read = 0"

            query += " ORDER BY e.detected_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_event(r) for r in rows]

    def get_change_event(self, event_id: str, owner_id: Optional[str] = None) -> Optional[ChangeEvent]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if owner_id:
                cursor.execute("""
                    SELECT e.* FROM change_events e
                    JOIN monitoring_rules r ON e.rule_id = r.id
                    WHERE e.event_id = ? AND r.owner_id = ?
                """, (event_id, owner_id))
            else:
                cursor.execute("SELECT * FROM change_events WHERE event_id = ?", (event_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event(row)

    def mark_event_read(self, event_id: str, read: bool = True, owner_id: Optional[str] = None) -> None:
        if owner_id:
            ev = self.get_change_event(event_id, owner_id=owner_id)
            if not ev:
                raise AuthorizationError(f"Event '{event_id}' does not belong to user '{owner_id}'.")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE change_events SET read = ? WHERE event_id = ?", (1 if read else 0, event_id))
            conn.commit()

    def dismiss_event(self, event_id: str, owner_id: Optional[str] = None) -> None:
        if owner_id:
            ev = self.get_change_event(event_id, owner_id=owner_id)
            if not ev:
                raise AuthorizationError(f"Event '{event_id}' does not belong to user '{owner_id}'.")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE change_events SET dismissed = 1 WHERE event_id = ?", (event_id,))
            conn.commit()

    def is_duplicate_event(self, rule_id: str, change_fingerprint: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM change_events
                WHERE rule_id = ? AND change_fingerprint = ?
                LIMIT 1
            """, (rule_id, change_fingerprint))
            return cursor.fetchone() is not None

    def get_stats(self, owner_id: Optional[str] = None) -> Dict[str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if owner_id:
                cursor.execute("SELECT COUNT(*) FROM monitoring_rules WHERE status = 'active' AND owner_id = ?", (owner_id,))
                active_rules = cursor.fetchone()[0]

                cursor.execute("""
                    SELECT COUNT(*) FROM change_events e
                    JOIN monitoring_rules r ON e.rule_id = r.id
                    WHERE e.classification = 'meaningful' AND r.owner_id = ?
                """, (owner_id,))
                meaningful_changes = cursor.fetchone()[0]

                cursor.execute("""
                    SELECT COUNT(*) FROM change_events e
                    JOIN monitoring_rules r ON e.rule_id = r.id
                    WHERE e.read = 0 AND e.should_notify = 1 AND e.dismissed = 0 AND r.owner_id = ?
                """, (owner_id,))
                unread_alerts = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM monitoring_rules WHERE status = 'error' AND owner_id = ?", (owner_id,))
                needing_attention = cursor.fetchone()[0]
            else:
                cursor.execute("SELECT COUNT(*) FROM monitoring_rules WHERE status = 'active'")
                active_rules = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM change_events WHERE classification = 'meaningful'")
                meaningful_changes = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM change_events WHERE read = 0 AND should_notify = 1 AND dismissed = 0")
                unread_alerts = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM monitoring_rules WHERE status = 'error'")
                needing_attention = cursor.fetchone()[0]

            return {
                "active_rules": active_rules,
                "meaningful_changes": meaningful_changes,
                "unread_alerts": unread_alerts,
                "needing_attention": needing_attention,
            }

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> MonitoringRule:
        return MonitoringRule(
            id=row["id"],
            owner_id=row["owner_id"],
            name=row["name"],
            source_url=row["source_url"],
            source_type=SourceType(row["source_type"]),
            natural_language_goal=row["natural_language_goal"],
            criteria_categories=json.loads(row["criteria_categories"]),
            specific_instructions=row["specific_instructions"] or "",
            check_interval_minutes=row["check_interval_minutes"],
            status=RuleStatus(row["status"]),
            created_at=row["created_at"],
            last_checked_at=row["last_checked_at"],
            next_check_at=row["next_check_at"],
            last_snapshot_id=row["last_snapshot_id"],
            error_message=row["error_message"],
            consecutive_failures=row["consecutive_failures"],
            is_demo_rule=bool(row["is_demo_rule"]),
            locked_until=row["locked_until"] if "locked_until" in row.keys() else None,
            locked_by=row["locked_by"] if "locked_by" in row.keys() else None,
        )

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> SourceSnapshot:
        return SourceSnapshot(
            snapshot_id=row["snapshot_id"],
            rule_id=row["rule_id"],
            captured_at=row["captured_at"],
            content_hash=row["content_hash"],
            normalized_content=row["normalized_content"],
            summary=row["summary"] or "",
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> ChangeEvent:
        return ChangeEvent(
            event_id=row["event_id"],
            rule_id=row["rule_id"],
            rule_name=row["rule_name"],
            detected_at=row["detected_at"],
            change_fingerprint=row["change_fingerprint"],
            classification=ClassificationType(row["classification"]),
            summary=row["summary"],
            previous_value=row["previous_value"],
            new_value=row["new_value"],
            impact_explanation=row["impact_explanation"],
            evidence=json.loads(row["evidence_json"] or "[]"),
            source_url=row["source_url"],
            confidence=ConfidenceLevel(row["confidence"]),
            recommended_action=row["recommended_action"],
            should_notify=bool(row["should_notify"]),
            notification_sent=bool(row["notification_sent"]),
            read=bool(row["read"]),
            dismissed=bool(row["dismissed"]),
        )
