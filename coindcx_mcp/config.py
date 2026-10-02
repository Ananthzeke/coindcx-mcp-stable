import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment() -> None:
    """Load a deterministic .env path without overriding process environment."""
    path = os.getenv("COINDCX_ENV_FILE")
    load_dotenv(Path(path).expanduser() if path else PROJECT_ROOT / ".env", override=False)


class Config:
    """Configuration settings for CoinDCX MCP server."""

    def __init__(self):
        load_environment()
        self.api_key = os.getenv("COINDCX_API_KEY", "")
        self.secret_key = os.getenv("COINDCX_SECRET_KEY", "")
        self.base_url = os.getenv("COINDCX_BASE_URL", "https://api.coindcx.com")
        if os.getenv("COINDCX_SANDBOX_MODE", "false").lower() == "true":
            raise ValueError(
                "COINDCX_SANDBOX_MODE is unsupported; use mocked tests for simulation."
            )
        self.public_base_url = os.getenv("COINDCX_PUBLIC_BASE_URL", "https://public.coindcx.com")

    def validate(self) -> bool:
        """Validate that required configuration is present."""
        return bool(self.api_key and self.secret_key)

    def get_missing_config(self) -> list[str]:
        """Get list of missing required configuration items."""
        missing = []
        if not self.api_key:
            missing.append("COINDCX_API_KEY")
        if not self.secret_key:
            missing.append("COINDCX_SECRET_KEY")
        return missing
