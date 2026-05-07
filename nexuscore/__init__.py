"""NexusCore — The ultimate all-in-one server management cog for Red-DiscordBot."""

from .nexuscore import NexusCore

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs, guild IDs, and channel IDs for its functionality. "
    "Per-user data includes: ticket history, application submissions, suggestion authorship, "
    "moderation cases/warnings/notes, economy balances/inventories/pets/transactions, "
    "giveaway entries, and reaction role state."
)


async def setup(bot):
    cog = NexusCore(bot)
    await bot.add_cog(cog)
