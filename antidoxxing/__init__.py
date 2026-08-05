from .antidoxxing import AntiDoxxing


async def setup(bot):
    await bot.add_cog(AntiDoxxing(bot))
