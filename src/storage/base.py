"""Abstract Storage Interface for NowAware."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from src.schemas.monitoring import MonitoringRule, SourceSnapshot
from src.schemas.changes import ChangeEvent


class AuthorizationError(Exception):
    """Raised when an operation attempts to access or mutate resources across tenant/user boundaries."""
    pass


class BaseStorage(ABC):
    """Interface providing storage abstractions for both SQLite and DynamoDB."""

    # Rules
    @abstractmethod
    def save_rule(self, rule: MonitoringRule) -> None:
        pass

    @abstractmethod
    def get_rule(self, rule_id: str, owner_id: Optional[str] = None) -> Optional[MonitoringRule]:
        """Fetches rule. If owner_id is provided, verifies caller is the owner."""
        pass

    @abstractmethod
    def list_rules(self, owner_id: Optional[str] = None) -> List[MonitoringRule]:
        """Lists rules belonging to owner_id. If None, lists all rules (e.g. for background scheduler)."""
        pass

    @abstractmethod
    def update_rule(self, rule: MonitoringRule, owner_id: Optional[str] = None) -> None:
        """Updates rule. If owner_id is provided, verifies caller is the owner."""
        pass

    @abstractmethod
    def delete_rule(self, rule_id: str, owner_id: Optional[str] = None) -> None:
        """Deletes rule and its cascade data. If owner_id is provided, verifies caller is the owner."""
        pass

    # Concurrency and Claiming Locks
    @abstractmethod
    def claim_rule_lock(self, rule_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        """
        Atomically claims a processing lease on a rule to prevent concurrent duplicate checks.
        Returns True if lease acquired, False if already claimed by another active worker.
        """
        pass

    @abstractmethod
    def release_rule_lock(self, rule_id: str, worker_id: str) -> None:
        """Releases a previously claimed processing lease."""
        pass

    # Snapshots
    @abstractmethod
    def save_snapshot(self, snapshot: SourceSnapshot) -> None:
        pass

    @abstractmethod
    def get_latest_snapshot(self, rule_id: str) -> Optional[SourceSnapshot]:
        pass

    @abstractmethod
    def list_snapshots(self, rule_id: str, limit: int = 10) -> List[SourceSnapshot]:
        pass

    # Change Events / Alerts
    @abstractmethod
    def save_change_event(self, event: ChangeEvent) -> bool:
        """
        Atomically persists a change event with unique constraint on (rule_id, change_fingerprint).
        Returns True if inserted, or False if duplicate was rejected under concurrent execution.
        """
        pass

    @abstractmethod
    def list_change_events(
        self,
        rule_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        only_unread: bool = False,
        limit: int = 50,
    ) -> List[ChangeEvent]:
        pass

    @abstractmethod
    def get_change_event(self, event_id: str, owner_id: Optional[str] = None) -> Optional[ChangeEvent]:
        pass

    @abstractmethod
    def mark_event_read(self, event_id: str, read: bool = True, owner_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def dismiss_event(self, event_id: str, owner_id: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def is_duplicate_event(self, rule_id: str, change_fingerprint: str) -> bool:
        pass

    @abstractmethod
    def get_stats(self, owner_id: Optional[str] = None) -> Dict[str, int]:
        pass
