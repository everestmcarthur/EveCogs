"""Wormhole v4.0.0 — the ultimate cross-server relay cog for Red-DiscordBot."""

from .core import Wormhole

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs, guild IDs, and channel IDs for relay functionality. "
    "Per-user data includes message counts, karma scores, keyword highlights, and DM relay subscriptions. "
    "Users may request deletion of their data via the bot owner."
)


async def setup(bot):
    cog = Wormhole(bot)
    await bot.add_cog(cog)
    await cog._init()
