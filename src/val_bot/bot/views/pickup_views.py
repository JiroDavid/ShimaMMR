from dataclasses import dataclass, field
import re
import discord

JOIN_EMOJI = "‼️"
CONFIRMED_CAPACITY = 10

_MESSAGE_PATTERN = re.compile(r"^🎯 Pickup game — \*\*(.+?)\*\*\n\n🕒 (.+?)\n\n")


def parse_pickup_message(content: str) -> tuple[str, str] | None:
    """Pulls (region, time) back out of a message built by
    build_pickup_message - used to rebuild a PickupSession that's been lost
    (e.g. a bot restart) from the message's own text plus its live reactions,
    rather than silently ignoring further reactions on it forever."""
    match = _MESSAGE_PATTERN.match(content)
    if match is None:
        return None
    return match.group(1), match.group(2)


@dataclass
class PickupSession:
    """Tracks sign-up order for one pickup announcement message. Reaction
    add/remove events mutate `order`; confirmed/waitlist are just the first
    CONFIRMED_CAPACITY vs. the rest, so someone leaving automatically
    promotes the next waitlisted person."""

    region: str
    time: str
    order: list[str] = field(default_factory=list)
    bot_reaction_removed: bool = False

    def join(self, discord_id: str) -> None:
        if discord_id not in self.order:
            self.order.append(discord_id)

    def leave(self, discord_id: str) -> None:
        if discord_id in self.order:
            self.order.remove(discord_id)

    def confirmed(self) -> list[str]:
        return self.order[:CONFIRMED_CAPACITY]

    def waitlist(self) -> list[str]:
        return self.order[CONFIRMED_CAPACITY:]


def build_pickup_message(
    region: str, time: str, confirmed_ids: list[str], waitlist_ids: list[str]
) -> str:
    confirmed_lines = "\n".join(f"<@{d}>" for d in confirmed_ids) or "*(none yet)*"
    waitlist_lines = "\n".join(f"<@{d}>" for d in waitlist_ids) or "*(none yet)*"
    return (
        f"🎯 Pickup game — **{region}**\n\n"
        f"🕒 {time}\n\n"
        f"React with anything to join (or click {JOIN_EMOJI} below)\n"
        f"(first {CONFIRMED_CAPACITY} are Confirmed, the rest go to the Waitlist)\n\n"
        f"**Confirmed ({len(confirmed_ids)}/{CONFIRMED_CAPACITY}):**\n{confirmed_lines}\n\n"
        f"**Waitlist:**\n{waitlist_lines}\n\n"
        f"@everyone"
    )


class PickupModal(discord.ui.Modal, title="Announce Pickup"):
    time = discord.ui.TextInput(label="Time", placeholder="e.g. Tonight 7:30pm BST")
    region = discord.ui.TextInput(label="Region", placeholder="e.g. EU", max_length=20)

    def __init__(self, on_built):
        super().__init__()
        self.on_built = on_built

    async def on_submit(self, interaction: discord.Interaction):
        region = str(self.region)
        time = str(self.time)
        content = build_pickup_message(region, time, [], [])
        await interaction.response.send_message(
            content, allowed_mentions=discord.AllowedMentions(everyone=True)
        )
        message = await interaction.original_response()
        await self.on_built(message, region, time)


class StartPickupView(discord.ui.View):
    """Entry point for v!pickup: a modal can only be opened in response to
    an interaction (never a plain text command), so the prefix command
    posts this button instead - clicking it opens the exact same
    PickupModal the slash command opens directly."""

    def __init__(self, on_built):
        super().__init__(timeout=300)
        self.on_built = on_built

    @discord.ui.button(label="Start Pickup", style=discord.ButtonStyle.primary)
    async def start_pickup(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = PickupModal(self.on_built)
        await interaction.response.send_modal(modal)
