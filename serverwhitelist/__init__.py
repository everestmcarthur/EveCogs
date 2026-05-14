"""ServerWhitelist v4.0 — The ultimate owner-only server management cog for Red-DiscordBot."""

from .serverwhitelist import ServerWhitelist

__red_end_user_data_statement__ = (
    "This cog stores guild IDs in a global whitelist, blacklist, join-attempt "
    "tracker, notes, tags, and whitelist request queue. No per-user data is "
    "collected or stored beyond requester IDs in the request queue."
)


async def setup(bot):
    cog = ServerWhitelist(bot)
    await bot.add_cog(cog)
