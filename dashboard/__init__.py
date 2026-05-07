from .dashboard import EveDash


async def setup(bot):
    await bot.add_cog(EveDash(bot))
