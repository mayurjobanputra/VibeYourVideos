# Configuration loading for OpenStoryMode

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables or .env file."""

    openrouter_api_key: str
    port: int

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment variables."""
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        port = int(os.environ.get("PORT", "8000"))
        return cls(openrouter_api_key=api_key, port=port)


def validate_config(config: Config) -> None:
    """Validate that required configuration values are present.

    Raises:
        ValueError: If the OpenRouter API key is missing.
    """
    if not config.openrouter_api_key:
        raise ValueError("Missing API key: OPENROUTER_API_KEY")


config = Config.load()
