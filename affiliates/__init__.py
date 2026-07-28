"""
Affiliates - Ping on Join (POJ), a persistent affiliate-server board, and a
separate DM-affiliates list sent to new members on join.
"""

from redbot.core.bot import Red

from .affiliates import Affiliates

__red_end_user_data_statement__ = (
    "This cog stores configuration data (POJ channels/settings, the affiliate board channel, and the "
    "affiliate/DM-affiliate entries themselves) per server. Each affiliate entry records the server name, "
    "invite link, the Discord user ID of whoever added it, and a timestamp. This data is not sent anywhere "
    "off the host running the bot."
)


async def setup(bot: Red) -> None:
    await bot.add_cog(Affiliates(bot))

