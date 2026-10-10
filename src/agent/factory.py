"""Strands Agent Factory for Bedrock and Demo Modes."""

import logging
from typing import Optional, List, Any
from strands import Agent
from strands.models import BedrockModel

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS, set_global_context
from src.schemas.changes import ChangeAnalysisResult
from src.config import settings
from src.storage.base import BaseStorage
from src.monitoring.fetcher import SourceFetcher

logger = logging.getLogger(__name__)


def create_agent(
    storage: Optional[BaseStorage] = None,
    fetcher: Optional[SourceFetcher] = None,
    model_id: Optional[str] = None,
    region_name: Optional[str] = None,
) -> Agent:
    """
    Creates and configures a Strands Agent instance.
    Uses BedrockModel when AWS is configured, or local fallback model when in demo mode.
    """
    # Link dependencies to tools
    if storage and fetcher:
        set_global_context(storage, fetcher)

    target_model_id = model_id or settings.bedrock_model_id
    target_region = region_name or settings.aws_region

    model = None
    if settings.is_aws_mode and settings.check_aws_credentials():
        try:
            logger.info(f"Initializing Amazon Bedrock model: {target_model_id} in {target_region}")
            model = BedrockModel(
                region_name=target_region,
                model_id=target_model_id,
            )
        except Exception as e:
            logger.warning(f"Could not initialize BedrockModel ({e}). Falling back to local agent.")
            model = None

    agent = Agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        name="NowAwareAgent",
        description="Personal AI Agent that monitors what matters and explains critical changes.",
    )
    return agent
