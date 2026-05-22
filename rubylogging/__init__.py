"""
RubyLogging - Comprehensive Discord event logging system.

Captures every single Discord event with individual toggles, advanced filtering,
and customizable output formats. Built for Red-DiscordBot.
"""

from redbot.core.bot import Red

from .rubylogging import RubyLogging

__red_end_user_data_statement__ = (
    "This cog stores configuration data (enabled events, log channels) but does not "
    "persistently store user messages or personal data beyond event metadata."
)


async def setup(bot: Red) -> None:
    await bot.add_cog(RubyLogging(bot))
