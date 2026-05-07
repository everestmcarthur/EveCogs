from .newhelpmenu import NewHelpMenu


async def setup(bot):
    cog = NewHelpMenu(bot)
    await bot.add_cog(cog)
    await cog.initialize()
