"""Abstract Storage Interface for NowAware."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from src.schemas.monitoring import MonitoringRule, SourceSnapshot
from src.schemas.changes import ChangeEvent


class BaseStorage(ABC):
    """Interface providing storage abstractions for both SQLite and DynamoDB."""

    # Rules
    @abstractmethod
    def save_rule(self, rule: MonitoringRule) -> None:
        pass

    @abstractmethod
    def get_rule(self, rule_id: str) -> Optional[MonitoringRule]:
        pass

    @abstractmethod
    def list_rules(self, owner_id: str = "default-user") -> List[MonitoringRule]:
        pass

    @abstractmethod
    def update_rule(self, rule: MonitoringRule) -> None:
        pass

    @abstractmethod
    def delete_rule(self, rule_id: str) -> None:
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
    def save_change_event(self, event: ChangeEvent) -> None:
        pass

    @abstractmethod
    def list_change_events(
        self,
        rule_id: Optional[str] = None,
        only_unread: bool = False,
        limit: int = 50,
    ) -> List[ChangeEvent]:
        pass

    @abstractmethod
    def get_change_event(self, event_id: str) -> Optional[ChangeEvent]:
        pass

    @abstractmethod
    def mark_event_read(self, event_id: str, read: bool = True) -> None:
        pass

    @abstractmethod
    def dismiss_event(self, event_id: str) -> None:
        pass

    @abstractmethod
    def is_duplicate_event(self, rule_id: str, change_fingerprint: str) -> bool:
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, int]:
        pass
