"""ServerWhitelist v3.0 — Ultimate owner-only server management for Red-DiscordBot."""

from .serverwhitelist import ServerWhitelist

__red_end_user_data_statement__ = (
    "This cog stores guild IDs in a global whitelist, blacklist, and "
    "join-attempt tracker. No per-user data is collected or stored."
)


async def setup(bot):
    cog = ServerWhitelist(bot)
    await bot.add_cog(cog)
