from .newhelpmenu import NewHelpMenu


async def setup(bot):
    # Remove Red's built-in help command BEFORE adding the cog,
    # so our cog's @commands.command(name="help") doesn't conflict.
    original_help = bot.remove_command("help")

    cog = NewHelpMenu(bot)
    cog._original_help_command = original_help  # store for restore on unload
    await bot.add_cog(cog)
    await cog.initialize()
