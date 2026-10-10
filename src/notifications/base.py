"""Notification Provider Base Interface."""

from abc import ABC, abstractmethod
from typing import Dict, Any
from src.schemas.changes import ChangeEvent
from src.schemas.monitoring import MonitoringRule


class BaseNotificationProvider(ABC):
    """Abstract interface for notification dispatchers."""

    @abstractmethod
    def send_alert(self, rule: MonitoringRule, event: ChangeEvent) -> Dict[str, Any]:
        """
        Sends alert notification.
        Returns: Dict containing success: bool, message_id: Optional[str], error: Optional[str]
        """
        pass
