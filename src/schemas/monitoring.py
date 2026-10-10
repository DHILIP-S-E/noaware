"""Monitoring Rule and Source Snapshot Data Schemas."""

from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field


class RuleStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class SourceType(str, Enum):
    HTML = "html"
    RSS = "rss"
    ATOM = "atom"
    TEXT = "text"


class MonitoringRule(BaseModel):
    """Configuration and state for a user monitoring rule."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str = Field(default="default-user")
    name: str
    source_url: str
    source_type: SourceType = SourceType.HTML
    natural_language_goal: str
    criteria_categories: List[str] = Field(default_factory=list)
    specific_instructions: Optional[str] = ""
    check_interval_minutes: int = 30
    status: RuleStatus = RuleStatus.ACTIVE
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_checked_at: Optional[str] = None
    next_check_at: Optional[str] = None
    last_snapshot_id: Optional[str] = None
    error_message: Optional[str] = None
    consecutive_failures: int = 0
    is_demo_rule: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class SourceSnapshot(BaseModel):
    """Point-in-time normalized baseline or snapshot of a source."""

    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str
    captured_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    content_hash: str
    normalized_content: str
    summary: Optional[str] = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
