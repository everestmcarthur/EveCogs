"""New Help Menu — Fully customisable interactive help system for Red-DiscordBot."""

from .newhelpmenu import NewHelpMenu

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs and guild IDs for per-user favourite commands "
    "and per-guild help menu configuration."
)


async def setup(bot):
    cog = NewHelpMenu(bot)
    await bot.add_cog(cog)
