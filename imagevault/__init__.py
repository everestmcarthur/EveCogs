"""
ImageVault - Auto-deletes posted images, re-hosting them in a private vault
channel first so they can be retrieved on request. Spoilered images stay
spoilered when sent back.
"""

from redbot.core.bot import Red

from .imagevault import ImageVault

__red_end_user_data_statement__ = (
    "This cog stores configuration data (enabled state, vault channel, watch/ignore lists) per server. "
    "When a member posts an image in a watched channel, this cog reposts that image (and the message's "
    "text content) into a staff-configured private vault channel, then deletes the original message. "
    "A small per-server index (author ID/name, channel and message IDs, timestamp, and a copy of the "
    "message text) is kept on local disk so the image can be located and re-sent on request via "
    "`[p]imagevault show`. This data is not sent anywhere off the host running the bot. Staff can remove "
    "an index entry at any time with `[p]imagevault forget`."
)


async def setup(bot: Red) -> None:
    await bot.add_cog(ImageVault(bot))

