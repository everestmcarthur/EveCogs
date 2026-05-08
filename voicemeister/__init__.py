"""VoiceMeister — Ultimate temporary voice channel management for Red-DiscordBot."""

from .voicemeister import VoiceMeister

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs, guild IDs, and channel IDs for voice channel "
    "ownership and settings. Per-user data includes channel ownership, ban/permit lists, "
    "and usage cooldowns. Data is cleaned up when channels are deleted."
)


async def setup(bot):
    cog = VoiceMeister(bot)
    await bot.add_cog(cog)
