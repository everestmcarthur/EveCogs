from .newhelpmenu import NewHelpMenu


async def setup(bot):
    # Red's own default help command (and any cog's ctx.send_help()) already
    # routes through bot.send_help_for() internally — see
    # redbot/core/commands/help.py. That's exactly the method this cog hooks
    # to render CV2 output, so the built-in help command must stay in place
    # for that hook to ever fire. Removing it here used to just delete
    # [p]help bot-wide with nothing to replace it (there was never an actual
    # replacement `help` command defined), and cog_unload never restored it
    # either — simplest correct fix is to not remove it at all.
    cog = NewHelpMenu(bot)
    await bot.add_cog(cog)
    await cog.initialize()
