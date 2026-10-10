"""Change Detection and Agent Analysis Data Schemas."""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field


class ClassificationType(str, Enum):
    MEANINGFUL = "meaningful"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


class ConfidenceLevel(str, Enum):
    VERIFIED = "verified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChangeAnalysisResult(BaseModel):
    """Structured Pydantic schema for Agent / Bedrock model evaluation."""

    change_detected: bool = Field(
        description="Whether an actual textual or structural change was detected."
    )
    classification: ClassificationType = Field(
        description="Meaningful (matters to user), Irrelevant (formatting/noise), or Uncertain."
    )
    summary: str = Field(
        description="Clear one-sentence summary of what changed."
    )
    previous_value: Optional[str] = Field(
        default=None, description="Previous text/date/value if isolated, or None."
    )
    new_value: Optional[str] = Field(
        default=None, description="New text/date/value if isolated, or None."
    )
    impact_explanation: str = Field(
        description="Clear evidence-based explanation of why this matters to the user's specific goal."
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Direct quotes or diff snippets from the source proving the change.",
    )
    source_url: str = Field(
        default="", description="The URL of the monitored source."
    )
    confidence: ConfidenceLevel = Field(
        default=ConfidenceLevel.HIGH,
        description="Confidence or verification status based on evidence.",
    )
    recommended_action: str = Field(
        description="Concrete suggestion on what the user should do next."
    )
    should_notify: bool = Field(
        default=False,
        description="True ONLY if change is meaningful and meets notification criteria.",
    )


class ChangeEvent(BaseModel):
    """Persisted event record for alerts and audit logs."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str
    rule_name: str
    detected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    change_fingerprint: str = Field(
        description="Hash/fingerprint used for deduplication of repeated checks."
    )
    classification: ClassificationType
    summary: str
    previous_value: Optional[str] = None
    new_value: Optional[str] = None
    impact_explanation: str
    evidence: List[str] = Field(default_factory=list)
    source_url: str
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    recommended_action: str
    should_notify: bool = False
    notification_sent: bool = False
    read: bool = False
    dismissed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
