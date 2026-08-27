from val_bot.config import Config
from val_bot.bot.main import build_bot

def test_build_bot_registers_ping_command():
    cfg = Config(discord_token="x", db_path=":memory:", henrikdev_api_key=None)
    bot = build_bot(cfg, session_factory=None)
    command_names = {cmd.name for cmd in bot.tree.get_commands()}
    assert "ping" in command_names
