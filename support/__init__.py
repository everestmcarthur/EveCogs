"""Support — Modernized contact/DM system replacing Red's built-in commands."""

from .support import Support

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs, guild IDs, channel IDs, and message content "
    "for support ticket/DM functionality. Data includes: support messages, categories, "
    "conversation history, and user preferences."
)


async def setup(bot):
    cog = Support(bot)
    await bot.add_cog(cog)
