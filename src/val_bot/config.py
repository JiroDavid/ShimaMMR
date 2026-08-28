import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    discord_token: str
    db_path: str
    henrikdev_api_key: str | None
    sync_announce_channel_id: int | None = None

    @staticmethod
    def from_env() -> "Config":
        token = os.environ.get("DISCORD_TOKEN")
        if not token:
            raise ValueError("DISCORD_TOKEN environment variable is required")
        channel_id = os.environ.get("SYNC_ANNOUNCE_CHANNEL_ID")
        return Config(
            discord_token=token,
            db_path=os.environ.get("DB_PATH", "/data/bot.db"),
            henrikdev_api_key=os.environ.get("HENRIKDEV_API_KEY") or None,
            sync_announce_channel_id=int(channel_id) if channel_id else None,
        )
