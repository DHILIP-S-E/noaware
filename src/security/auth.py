"""Authentication and Identity Verification Module for NowAware.

Strictly enforces identity boundaries:
1. Local Demo Mode: Permitted to use clearly-labelled simulated tenant contexts for UI testing.
2. AWS-Backed Mode: Prohibits trusting user/tenant IDs supplied by frontend inputs.
   Requires verified identity derived from infrastructure headers (AWS ALB / Cognito OIDC / IAM).
   If verified identity is absent, multi-user cloud access is disabled to prevent tenant spoofing.
"""

import os
import logging
from typing import Optional, Tuple, Dict, Any
from src.config import settings

logger = logging.getLogger(__name__)


class IdentityVerificationError(Exception):
    """Raised when an unauthenticated or invalid identity attempts to access cloud monitoring data."""
    pass


def resolve_request_identity(
    headers: Optional[Dict[str, str]] = None,
    session_user: Optional[str] = None,
) -> Tuple[Optional[str], bool, str]:
    """
    Resolves caller identity and tenant isolation boundary.
    Returns: (owner_id: Optional[str], is_verified: bool, status_description: str)
    """
    headers = headers or {}

    # Case 1: Local Demo Mode
    if not settings.is_aws_mode:
        selected_tenant = session_user or "user-alice"
        return (
            selected_tenant,
            True,
            f"LOCAL_DEMO_SIMULATED: Operating in local demonstration mode. Active tenant: '{selected_tenant}'.",
        )

    # Case 2: AWS-Backed Mode - Strictly verify infrastructure identity
    # Check for Amazon ALB / API Gateway / Cognito OIDC verified identity headers
    oidc_identity = (
        headers.get("x-amzn-oidc-identity")
        or headers.get("X-Amzn-Oidc-Identity")
        or headers.get("x-amzn-oidc-sub")
        or headers.get("X-Amzn-Oidc-Sub")
        or os.environ.get("VERIFIED_CLOUD_USER_ID")
    )

    if oidc_identity:
        # Verified identity from trusted ingress proxy
        derived_owner = f"cognito-{oidc_identity.strip()}"
        logger.info(f"Verified cloud identity authenticated: {derived_owner}")
        return (
            derived_owner,
            True,
            f"AWS_VERIFIED: Authenticated via AWS OIDC/Cognito identity: '{derived_owner}'.",
        )

    # Check for explicit IAM Principal context
    iam_caller_arn = os.environ.get("AWS_CALLER_ARN") or os.environ.get("AWS_ROLE_ARN")
    if iam_caller_arn:
        derived_owner = f"iam-{iam_caller_arn.split('/')[-1]}"
        return (
            derived_owner,
            True,
            f"AWS_VERIFIED: Authenticated via IAM Principal identity: '{derived_owner}'.",
        )

    # Multi-user cloud access is DISABLED when verified identity is absent
    # We do NOT trust any user/tenant ID provided by frontend dropdowns or query params!
    logger.warning("AWS Mode active but no verified OIDC/IAM identity found. Multi-user cloud access disabled.")
    return (
        None,
        False,
        "AWS_UNAUTHENTICATED: Multi-user cloud access is disabled. "
        "No verified identity provider (e.g., AWS Cognito, ALB OIDC, or IAM) is attached. "
        "Frontend tenant-switching is rejected in cloud mode to prevent tenant-spoofing.",
    )


def is_cloud_multi_user_enabled() -> bool:
    """Returns True only if running with an active, verified identity provider in cloud mode."""
    if not settings.is_aws_mode:
        return True  # Local demo simulator enabled
    owner_id, is_verified, _ = resolve_request_identity()
    return is_verified and (owner_id is not None)
