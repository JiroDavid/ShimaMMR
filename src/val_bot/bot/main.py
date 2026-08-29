import discord
from discord import app_commands
from discord.ext import commands
from val_bot.config import Config
from val_bot.db.session import make_engine, make_session_factory

class ValBot(commands.Bot):
    def __init__(self, session_factory, henrikdev_api_key: str | None):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="v!", intents=intents)
        self.session_factory = session_factory
        self.henrikdev_api_key = henrikdev_api_key

    async def setup_hook(self):
        from val_bot.bot.cogs.linking import setup as setup_linking
        await setup_linking(self)
        from val_bot.bot.cogs.report import setup as setup_report
        await setup_report(self)
        from val_bot.bot.cogs.mmr import setup as setup_mmr
        await setup_mmr(self)
        from val_bot.bot.cogs.leaderboard import setup as setup_leaderboard
        await setup_leaderboard(self)
        from val_bot.bot.cogs.history import setup as setup_history
        await setup_history(self)
        from val_bot.bot.cogs.admin import setup as setup_admin
        await setup_admin(self)
        from val_bot.bot.cogs.sync import setup as setup_sync
        await setup_sync(self)
        from val_bot.bot.cogs.pickup import setup as setup_pickup
        await setup_pickup(self)
        await self.tree.sync()

def build_bot(config: Config, session_factory) -> ValBot:
    bot = ValBot(session_factory=session_factory, henrikdev_api_key=config.henrikdev_api_key)

    @bot.tree.command(name="ping", description="Check that the bot is alive")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("pong", ephemeral=True)

    @bot.command(name="ping")
    async def ping_prefix(ctx: commands.Context):
        await ctx.send("pong")

    return bot

def main():
    config = Config.from_env()
    engine = make_engine(config.db_path)
    session_factory = make_session_factory(engine)
    bot = build_bot(config, session_factory)
    bot.run(config.discord_token)

if __name__ == "__main__":
    main()
