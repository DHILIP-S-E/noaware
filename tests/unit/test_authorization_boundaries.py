"""Unit tests for multi-tenant authorization boundaries."""

import os
import tempfile
import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.storage.base import AuthorizationError
from src.schemas.monitoring import MonitoringRule, SourceType
from src.schemas.changes import ChangeEvent, ClassificationType
from src.agent.tools import set_global_context, get_monitoring_rule, pause_monitor, update_monitor
from src.monitoring.fetcher import SourceFetcher


@pytest.fixture
def auth_storage():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage = SQLiteStorage(path)
    yield storage
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def test_tenant_rule_isolation(auth_storage):
    alice_rule = MonitoringRule(
        name="Alice Scholarship",
        source_url="https://example.com/scholarship",
        owner_id="user-alice",
        natural_language_goal="Watch deadline",
    )
    auth_storage.save_rule(alice_rule)

    # Alice can retrieve her rule
    fetched = auth_storage.get_rule(alice_rule.id, owner_id="user-alice")
    assert fetched is not None
    assert fetched.owner_id == "user-alice"

    # Bob is unauthorized to retrieve Alice's rule
    with pytest.raises(AuthorizationError, match="Access denied"):
        auth_storage.get_rule(alice_rule.id, owner_id="user-bob")

    # Bob's rule list does not leak Alice's rule
    bob_rules = auth_storage.list_rules(owner_id="user-bob")
    assert len(bob_rules) == 0

    # Bob cannot update Alice's rule
    alice_rule.name = "Hacked Name"
    with pytest.raises(AuthorizationError):
        auth_storage.update_rule(alice_rule, owner_id="user-bob")

    # Bob cannot delete Alice's rule
    with pytest.raises(AuthorizationError):
        auth_storage.delete_rule(alice_rule.id, owner_id="user-bob")

    # Alice's rule remains intact
    still_there = auth_storage.get_rule(alice_rule.id, owner_id="user-alice")
    assert still_there is not None
    assert still_there.name == "Alice Scholarship"


def test_tenant_alert_isolation(auth_storage):
    alice_rule = MonitoringRule(
        name="Alice Scholarship",
        source_url="https://example.com/scholarship",
        owner_id="user-alice",
        natural_language_goal="Watch deadline",
    )
    auth_storage.save_rule(alice_rule)

    event = ChangeEvent(
        rule_id=alice_rule.id,
        rule_name=alice_rule.name,
        change_fingerprint="fp-alice-1",
        classification=ClassificationType.MEANINGFUL,
        summary="Deadline moved",
        impact_explanation="Explanation",
        source_url=alice_rule.source_url,
        recommended_action="Act",
        should_notify=True,
    )
    auth_storage.save_change_event(event)

    # Alice can see her event
    alice_events = auth_storage.list_change_events(owner_id="user-alice")
    assert len(alice_events) == 1

    # Bob cannot see Alice's alerts
    bob_events = auth_storage.list_change_events(owner_id="user-bob")
    assert len(bob_events) == 0

    # Bob cannot mark Alice's alert as read or dismiss it
    with pytest.raises(AuthorizationError):
        auth_storage.mark_event_read(event.event_id, read=True, owner_id="user-bob")

    with pytest.raises(AuthorizationError):
        auth_storage.dismiss_event(event.event_id, owner_id="user-bob")


def test_agent_tools_respect_active_owner_boundary(auth_storage):
    fetcher = SourceFetcher()
    # Configure context as Alice
    set_global_context(auth_storage, fetcher, owner_id="user-alice")

    alice_rule = MonitoringRule(
        name="Alice Confidential Monitor",
        source_url="mock://foundation.org/scholarship",
        owner_id="user-alice",
        natural_language_goal="Goal",
    )
    auth_storage.save_rule(alice_rule)

    # Switch context to Bob
    set_global_context(auth_storage, fetcher, owner_id="user-bob")

    # Bob attempts to inspect Alice's rule via agent tool
    res = get_monitoring_rule(rule_id=alice_rule.id)
    assert "Authorization error" in res or "not found" in res

    # Bob attempts to pause Alice's rule via agent tool
    pause_res = pause_monitor(rule_id=alice_rule.id)
    assert "Authorization error" in pause_res or "not found" in pause_res


def test_auth_identity_resolution_local_and_cloud(monkeypatch):
    from src.security.auth import resolve_request_identity, is_cloud_multi_user_enabled
    from src.config import settings

    # In local demo mode: Simulated tenant selection is permitted
    monkeypatch.setattr(settings, "mode", "demo")
    owner, verified, desc = resolve_request_identity(session_user="user-alice")
    assert owner == "user-alice"
    assert verified is True
    assert "LOCAL_DEMO" in desc

    # In AWS cloud mode without verified identity: Untrusted frontend parameter is ignored
    monkeypatch.setattr(settings, "mode", "aws")
    monkeypatch.delenv("VERIFIED_CLOUD_USER_ID", raising=False)
    monkeypatch.delenv("AWS_CALLER_ARN", raising=False)
    owner, verified, desc = resolve_request_identity(session_user="user-attacker-trying-to-spoof")
    assert owner is None
    assert verified is False
    assert is_cloud_multi_user_enabled() is False
    assert "disabled" in desc.lower()

    # In AWS cloud mode with verified OIDC header: Authenticated owner derived from identity
    owner_oidc, verified_oidc, desc_oidc = resolve_request_identity(
        headers={"x-amzn-oidc-identity": "sub-12345-verified"}
    )
    assert owner_oidc == "cognito-sub-12345-verified"
    assert verified_oidc is True
    assert "AWS_VERIFIED" in desc_oidc
