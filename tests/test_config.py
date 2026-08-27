import os
from val_bot.config import Config

def test_from_env_reads_required_and_optional_vars(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "abc123")
    monkeypatch.setenv("DB_PATH", "/data/bot.db")
    monkeypatch.delenv("HENRIKDEV_API_KEY", raising=False)
    cfg = Config.from_env()
    assert cfg.discord_token == "abc123"
    assert cfg.db_path == "/data/bot.db"
    assert cfg.henrikdev_api_key is None

def test_from_env_missing_token_raises(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    try:
        Config.from_env()
        assert False, "expected ValueError"
    except ValueError as e:
        assert "DISCORD_TOKEN" in str(e)
