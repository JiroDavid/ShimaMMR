import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    discord_token: str
    db_path: str
    henrikdev_api_key: str | None

    @staticmethod
    def from_env() -> "Config":
        token = os.environ.get("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable is required")
        return Config(
            discord_token=token,
            db_path=os.environ.get("DB_PATH", "/data/bot.db"),
            henrikdev_api_key=os.environ.get("HENRIKDEV_API_KEY") or None,
        )
