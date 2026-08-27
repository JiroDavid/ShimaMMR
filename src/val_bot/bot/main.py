import discord
from discord import app_commands
from discord.ext import commands
from val_bot.config import Config
from val_bot.db.session import make_engine, make_session_factory

class ValBot(commands.Bot):
    def __init__(self, session_factory, henrikdev_api_key: str | None):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.session_factory = session_factory
        self.henrikdev_api_key = henrikdev_api_key

    async def setup_hook(self):
        await self.tree.sync()

def build_bot(config: Config, session_factory) -> ValBot:
    bot = ValBot(session_factory=session_factory, henrikdev_api_key=config.henrikdev_api_key)

    @bot.tree.command(name="ping", description="Check that the bot is alive")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("pong", ephemeral=True)

    return bot

def main():
    config = Config.from_env()
    engine = make_engine(config.db_path)
    session_factory = make_session_factory(engine)
    bot = build_bot(config, session_factory)
    bot.run(config.discord_token)

if __name__ == "__main__":
    main()
