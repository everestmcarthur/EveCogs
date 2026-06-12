"""Support — Modernized contact/DM system replacing Red's built-in commands."""

from .support import Support

__red_end_user_data_statement__ = (
    "This cog stores Discord user IDs, guild IDs, channel IDs, and message content "
    "for support ticket/DM functionality. Data includes: support messages, categories, "
    "conversation history, and user preferences."
)

# Store removed commands for restoration
_removed_commands = {}


async def setup(bot):
    # Remove Red's built-in commands BEFORE loading the cog
    for cmd_name in ["contact", "dm"]:
        cmd = bot.get_command(cmd_name)
        if cmd:
            _removed_commands[cmd_name] = cmd
            bot.remove_command(cmd_name)

    cog = Support(bot)
    await bot.add_cog(cog)


async def teardown(bot):
    # Restore Red's built-in commands when unloading
    for cmd_name, cmd in _removed_commands.items():
        if cmd_name not in bot.all_commands:
            bot.add_command(cmd)
    _removed_commands.clear()
