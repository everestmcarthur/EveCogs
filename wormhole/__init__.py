from .wormhole import Wormhole


async def setup(bot):
    cog = Wormhole(bot)
    await bot.add_cog(cog)
