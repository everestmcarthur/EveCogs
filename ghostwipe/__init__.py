"""
GhostWipe - Auto-deletes a departing member's messages server-wide and
produces a full HTML audit log of what was removed.
"""

from redbot.core.bot import Red

from .ghostwipe import GhostWipe

__red_end_user_data_statement__ = (
    "This cog stores configuration data (enabled state, log channel, exemption lists) per server. "
    "When a member leaves, is kicked, or is banned, it deletes their messages across the server and "
    "saves the deleted message content, attachments metadata, and timestamps to local disk as an HTML/JSON "
    "audit report so staff can review what was removed. This data is not sent anywhere off the host "
    "running the bot. Server staff can disable content capture (redacted reports) or set a retention "
    "period to auto-delete old reports via `[p]ghostwipe report content` and `[p]ghostwipe retention`."
)


async def setup(bot: Red) -> None:
    await bot.add_cog(GhostWipe(bot))

