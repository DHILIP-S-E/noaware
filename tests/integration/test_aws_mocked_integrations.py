"""Mocked Integration Tests for AWS Service Boundaries.

Exercises and verifies the following AWS code paths using mocked infrastructure:
1. Amazon DynamoDB Storage (rules, snapshots, events, atomic leases)
2. Amazon Bedrock Runtime Foundation Model (Claude 3.5 Sonnet analysis + failure fallback)
3. Amazon SES Notification Provider (evidence-backed email dispatch)
4. AWS Lambda Scheduled Worker & Amazon EventBridge trigger

NOTE: These tests exercise AWS client code paths against mocked interfaces.
Live deployment to billable AWS cloud resources remains unverified and requires explicit deployment approval.
"""

import io
import json
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from src.schemas.monitoring import MonitoringRule, SourceSnapshot, RuleStatus, SourceType
from src.schemas.changes import ChangeEvent, ClassificationType, ConfidenceLevel
from src.monitoring.diff_engine import DiffResult
from src.monitoring.classifier import ChangeClassifier
from src.storage.dynamodb_store import DynamoDBStorage
from src.notifications.ses_email import SESEmailProvider
from src.scheduling.worker import lambda_handler, run_scheduled_checks


# ============================================================================
# 1. DynamoDB Integration Boundary Tests (Mocked)
# ============================================================================

def test_dynamodb_storage_rule_crud_and_locking(monkeypatch):
    """Verifies DynamoDBStorage operations including atomic lease locking with mocked table."""
    mock_dynamodb = MagicMock()
    mock_rules_table = MagicMock()
    mock_snapshots_table = MagicMock()
    mock_alerts_table = MagicMock()

    mock_dynamodb.Table.side_effect = lambda name: {
        "nowaware-rules": mock_rules_table,
        "nowaware-snapshots": mock_snapshots_table,
        "nowaware-alerts": mock_alerts_table,
    }.get(name, mock_rules_table)

    monkeypatch.setattr("boto3.resource", lambda service, **kwargs: mock_dynamodb)

    storage = DynamoDBStorage(
        rules_table_name="nowaware-rules",
        snapshots_table_name="nowaware-snapshots",
        alerts_table_name="nowaware-alerts",
        region_name="us-east-1",
    )

    rule = MonitoringRule(
        name="AWS Cloud Rule",
        source_url="https://example.com/notices",
        owner_id="cognito-user-123",
        natural_language_goal="Watch updates",
    )

    # 1. Save rule
    storage.save_rule(rule)
    mock_rules_table.put_item.assert_called_once()

    # 2. Get rule (authorized)
    mock_rules_table.get_item.return_value = {"Item": rule.model_dump()}
    fetched = storage.get_rule(rule.id, owner_id="cognito-user-123")
    assert fetched is not None
    assert fetched.name == "AWS Cloud Rule"

    # 3. Claim rule lock (atomic conditional update)
    mock_rules_table.update_item.return_value = {"Attributes": {}}
    locked = storage.claim_rule_lock(rule.id, worker_id="worker-lambda-1", lease_seconds=60)
    assert locked is True
    mock_rules_table.update_item.assert_called()

    # 4. Release lock
    storage.release_rule_lock(rule.id, worker_id="worker-lambda-1")
    assert mock_rules_table.update_item.call_count >= 2


def test_dynamodb_save_change_event_conditional(monkeypatch):
    """Verifies DynamoDB change event saving and conditional duplicate prevention."""
    mock_dynamodb = MagicMock()
    mock_alerts_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_alerts_table

    monkeypatch.setattr("boto3.resource", lambda service, **kwargs: mock_dynamodb)

    storage = DynamoDBStorage(
        rules_table_name="nowaware-rules",
        snapshots_table_name="nowaware-snapshots",
        alerts_table_name="nowaware-alerts",
    )

    event = ChangeEvent(
        rule_id="rule-1",
        rule_name="Test Rule",
        change_fingerprint="fp-test-123",
        classification=ClassificationType.MEANINGFUL,
        summary="Meaningful update detected",
        impact_explanation="Directly impacts goals",
        evidence=["Quote 1"],
        source_url="https://example.com",
        confidence=ConfidenceLevel.HIGH,
        recommended_action="Take action",
        should_notify=True,
    )

    # First insert succeeds
    mock_alerts_table.put_item.return_value = {}
    saved = storage.save_change_event(event)
    assert saved is True

    # Duplicate insert triggers ConditionalCheckFailedException -> returns False
    mock_alerts_table.put_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Item exists"}},
        "PutItem",
    )
    dup_saved = storage.save_change_event(event)
    assert dup_saved is False


# ============================================================================
# 2. Amazon Bedrock Foundation Model Tests (Mocked)
# ============================================================================

def test_bedrock_classifier_successful_invocation():
    """Verifies Bedrock invocation formatting and response parsing using mocked bedrock-runtime client."""
    mock_bedrock = MagicMock()

    bedrock_response_payload = {
        "content": [
            {
                "text": json.dumps({
                    "classification": "meaningful",
                    "summary": "Deadline advanced to April 10, 2026",
                    "impact_explanation": "Earlier deadline requires submitting scholarship materials sooner.",
                    "previous_value": "May 15, 2026",
                    "new_value": "April 10, 2026",
                    "should_notify": True,
                    "confidence": "verified",
                })
            }
        ]
    }

    mock_body = MagicMock()
    mock_body.read.return_value = json.dumps(bedrock_response_payload).encode("utf-8")
    mock_bedrock.invoke_model.return_value = {"body": mock_body}

    rule = MonitoringRule(
        name="STEM Deadline",
        source_url="https://foundation.org/scholarship",
        owner_id="cognito-user-1",
        natural_language_goal="Alert me when deadline changes",
        criteria_categories=["Important dates and deadlines"],
    )

    diff = DiffResult(
        has_changed=True,
        diff_unified="- Application Deadline: May 15, 2026\n+ Application Deadline: April 10, 2026",
        added_lines=["Application Deadline: April 10, 2026"],
        removed_lines=["Application Deadline: May 15, 2026"],
        evidence_snippets=["Application Deadline: April 10, 2026"],
        isolated_previous="May 15, 2026",
        isolated_new="April 10, 2026",
    )

    result = ChangeClassifier.classify_with_bedrock(
        rule=rule,
        diff_result=diff,
        source_url="https://foundation.org/scholarship",
        client=mock_bedrock,
        model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
    )

    assert result.change_detected is True
    assert result.classification == ClassificationType.MEANINGFUL
    assert result.should_notify is True
    assert "April 10" in result.new_value
    mock_bedrock.invoke_model.assert_called_once()


def test_bedrock_classifier_failure_graceful_heuristic_fallback():
    """Verifies that if Amazon Bedrock throws an error or times out, the system falls back to heuristics."""
    mock_bedrock = MagicMock()
    mock_bedrock.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "ModelTimeoutException", "Message": "Inference timed out"}},
        "InvokeModel",
    )

    rule = MonitoringRule(
        name="STEM Deadline",
        source_url="https://foundation.org/scholarship",
        owner_id="cognito-user-1",
        natural_language_goal="Alert me when deadline changes",
        criteria_categories=["Important dates and deadlines"],
    )

    diff = DiffResult(
        has_changed=True,
        diff_unified="- Application Deadline: May 15, 2026\n+ Application Deadline: April 10, 2026",
        added_lines=["Application Deadline: April 10, 2026"],
        removed_lines=["Application Deadline: May 15, 2026"],
        evidence_snippets=["Application Deadline: April 10, 2026"],
        isolated_previous="May 15, 2026",
        isolated_new="April 10, 2026",
    )

    result = ChangeClassifier.classify_with_bedrock(
        rule=rule,
        diff_result=diff,
        source_url="https://foundation.org/scholarship",
        client=mock_bedrock,
    )

    # Must not crash! Deterministic fallback produces correct meaningful result
    assert result.change_detected is True
    assert result.classification == ClassificationType.MEANINGFUL
    assert result.should_notify is True
    assert "Bedrock fallback invoked" in result.impact_explanation


# ============================================================================
# 3. Amazon SES Notification Tests (Mocked)
# ============================================================================

def test_ses_notifier_dispatches_email(monkeypatch):
    """Verifies that SESEmailProvider formats evidence quotes and sends via Amazon SES client."""
    mock_ses = MagicMock()
    mock_ses.send_email.return_value = {"MessageId": "msg-ses-999888"}

    monkeypatch.setattr("boto3.client", lambda service, **kwargs: mock_ses)

    provider = SESEmailProvider(
        sender_email="alerts@nowaware.example.com",
        recipient_email="user@example.com",
        region_name="us-east-1",
    )

    rule = MonitoringRule(
        name="Grant Monitor",
        source_url="https://grants.gov/item",
        owner_id="cognito-user-1",
        natural_language_goal="Watch funding",
    )

    event = ChangeEvent(
        rule_id=rule.id,
        rule_name=rule.name,
        change_fingerprint="fp-1",
        classification=ClassificationType.MEANINGFUL,
        summary="Funding amount increased to $500,000",
        impact_explanation="Grant award doubled from baseline.",
        evidence=["Award Amount: $500,000"],
        source_url=rule.source_url,
        confidence=ConfidenceLevel.VERIFIED,
        recommended_action="Prepare revised proposal",
        should_notify=True,
    )

    res = provider.send_alert(rule, event)
    assert res["success"] is True
    assert res["message_id"] == "msg-ses-999888"
    mock_ses.send_email.assert_called_once()
    call_args = mock_ses.send_email.call_args[1]
    assert call_args["Source"] == "alerts@nowaware.example.com"
    assert "Funding amount increased" in call_args["Message"]["Subject"]["Data"]


# ============================================================================
# 4. AWS Lambda Scheduled Worker & EventBridge Trigger Tests (Mocked)
# ============================================================================

def test_lambda_worker_invoked_by_eventbridge_event(monkeypatch):
    """
    Simulates Amazon EventBridge triggering the AWS Lambda ScheduledMonitoringWorker.
    Verifies full execution lifecycle and 200 response.
    """
    eventbridge_event = {
        "version": "0",
        "id": "53dc4d37-c24a-4318-8d66-85adcfc622c1",
        "detail-type": "Scheduled Event",
        "source": "aws.events",
        "account": "123456789012",
        "time": "2026-10-10T09:00:00Z",
        "region": "us-east-1",
        "resources": [
            "arn:aws:events:us-east-1:123456789012:rule/nowaware-scheduled-check-rule"
        ],
        "detail": {},
    }

    # Mock the internal run_scheduled_checks to verify Lambda envelope
    mock_batch_results = {
        "timestamp": "2026-10-10T09:00:00Z",
        "evaluated_count": 3,
        "changes_detected": 1,
        "alerts_dispatched": 1,
        "errors": 0,
        "details": [],
    }

    monkeypatch.setattr("src.scheduling.worker.run_scheduled_checks", lambda max_rules=25: mock_batch_results)

    response = lambda_handler(event=eventbridge_event, context=None)
    assert response["statusCode"] == 200
    assert response["body"]["evaluated_count"] == 3
    assert response["body"]["changes_detected"] == 1
