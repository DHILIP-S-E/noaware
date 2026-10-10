"""Amazon SES Notification Provider."""

import logging
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError
from src.notifications.base import BaseNotificationProvider
from src.schemas.changes import ChangeEvent
from src.schemas.monitoring import MonitoringRule
from src.config import settings

logger = logging.getLogger(__name__)


class SESEmailProvider(BaseNotificationProvider):
    """Sends evidence-backed monitoring alert emails via Amazon SES."""

    def __init__(
        self,
        sender_email: Optional[str] = None,
        recipient_email: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        self.sender = sender_email or settings.ses_sender_email
        self.recipient = recipient_email or settings.ses_recipient_override
        self.region = region_name or settings.aws_region

    def is_configured(self) -> bool:
        return bool(self.sender and self.recipient)

    def send_alert(self, rule: MonitoringRule, event: ChangeEvent) -> Dict[str, Any]:
        """Sends structured alert email if SES is configured, or logs non-configured state safely."""
        if not self.is_configured():
            logger.info("SES email notification skipped: SES sender or recipient email not configured.")
            return {
                "success": False,
                "reason": "SES not configured. Configure SES_SENDER_EMAIL and SES_RECIPIENT_OVERRIDE in settings.",
                "message_id": None,
            }

        # Format email contents
        subject = f"[NowAware Alert] {rule.name}: {event.summary}"
        
        evidence_text = "\n".join(f"  • {e}" for e in event.evidence) if event.evidence else "  (No direct quote)"
        before_after_section = ""
        if event.previous_value or event.new_value:
            before_after_section = (
                f"\n--- Changes ---\n"
                f"Previous: {event.previous_value or 'N/A'}\n"
                f"New:      {event.new_value or 'N/A'}\n"
            )

        body_text = f"""NowAware Alert: Meaningful Change Detected
===============================================

Monitor:     {rule.name}
Source URL:  {rule.source_url}
Detected At: {event.detected_at}
Confidence:  {event.confidence.value.upper()}

Summary:
{event.summary}

Why this matters:
{event.impact_explanation}
{before_after_section}
Supporting Evidence from Source:
{evidence_text}

Recommended Next Action:
{event.recommended_action}

-----------------------------------------------
This alert was sent by your personal NowAware agent because it matched your monitoring criteria.
"""

        try:
            client = boto3.client("ses", region_name=self.region)
            response = client.send_email(
                Source=self.sender,
                Destination={"ToAddresses": [self.recipient]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
                },
            )
            msg_id = response.get("MessageId")
            logger.info(f"SES Alert successfully dispatched. Message ID: {msg_id}")
            return {"success": True, "message_id": msg_id, "error": None}
        except ClientError as e:
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            logger.error(f"Failed to send SES alert: {error_msg}")
            return {"success": False, "message_id": None, "error": error_msg}
        except Exception as e:
            logger.error(f"Unexpected error sending SES alert: {e}")
            return {"success": False, "message_id": None, "error": str(e)}
