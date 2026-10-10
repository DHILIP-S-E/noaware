"""NowAware Configuration Module."""

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Automatically load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    """Application settings with environment variable fallbacks."""

    mode: str = Field(
        default_factory=lambda: os.getenv("NOWAWARE_MODE", "demo").lower()
    )
    aws_region: str = Field(
        default_factory=lambda: os.getenv("AWS_REGION", "us-east-1")
    )
    bedrock_model_id: str = Field(
        default_factory=lambda: os.getenv(
            "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
    )

    dynamodb_rules_table: str = Field(
        default_factory=lambda: os.getenv(
            "DYNAMODB_RULES_TABLE", "nowaware-monitoring-rules"
        )
    )
    dynamodb_snapshots_table: str = Field(
        default_factory=lambda: os.getenv(
            "DYNAMODB_SNAPSHOTS_TABLE", "nowaware-source-snapshots"
        )
    )
    dynamodb_alerts_table: str = Field(
        default_factory=lambda: os.getenv(
            "DYNAMODB_ALERTS_TABLE", "nowaware-change-alerts"
        )
    )

    ses_sender_email: str = Field(
        default_factory=lambda: os.getenv("SES_SENDER_EMAIL", "")
    )
    ses_recipient_override: str = Field(
        default_factory=lambda: os.getenv("SES_RECIPIENT_OVERRIDE", "")
    )

    default_check_interval_minutes: int = Field(
        default_factory=lambda: int(
            os.getenv("DEFAULT_CHECK_INTERVAL_MINUTES", "30")
        )
    )
    min_check_interval_minutes: int = Field(
        default_factory=lambda: int(
            os.getenv("MIN_CHECK_INTERVAL_MINUTES", "5")
        )
    )
    request_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
    )
    max_response_bytes: int = Field(
        default_factory=lambda: int(
            os.getenv("MAX_RESPONSE_BYTES", "1048576")
        )  # 1 MB
    )
    local_db_path: str = Field(
        default_factory=lambda: os.getenv(
            "LOCAL_DB_PATH", str(BASE_DIR / "data" / "nowaware.db")
        )
    )
    log_level: str = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )

    @property
    def is_aws_mode(self) -> bool:
        return self.mode == "aws"

    @property
    def is_demo_mode(self) -> bool:
        return self.mode != "aws"

    def check_aws_credentials(self) -> bool:
        """Check if AWS credentials are active and usable."""
        try:
            import boto3

            session = boto3.Session(region_name=self.aws_region)
            credentials = session.get_credentials()
            return credentials is not None and credentials.access_key is not None
        except Exception:
            return False


settings = Settings()
