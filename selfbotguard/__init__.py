"""SelfbotGuard — Advanced selfbot detection & punishment for Red-DiscordBot."""

from .selfbotguard import SelfbotGuard

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs and guild IDs for selfbot detection. "
    "Per-user data includes message timestamps, response timing, activity windows, "
    "and suspicion scores. Users may request deletion via the bot owner."
)


async def setup(bot):
    cog = SelfbotGuard(bot)
    await bot.add_cog(cog)
