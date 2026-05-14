"""
UserSlash — User-installable slash-command bridge for Red-DiscordBot.

Replaces OneTrueSlash.  Registers a single proxy slash command (named after
the bot) that makes *every* Red text command accessible via slash — in
servers, DMs, and group DMs.  After syncing, all global commands are
automatically patched with ``integration_types: [0, 1]`` and
``contexts: [0, 1, 2]`` so the bot works as a user-installable app.

Owner commands:
    [p]userslash sync   — Sync the command tree + patch user-install flags
    [p]userslash patch  — Patch flags on already-synced commands
    [p]userslash status — Show per-command user-install status
"""

import asyncio
import logging
from typing import Optional

import discord
from redbot.core import app_commands, commands
from redbot.core.bot import Red
from redbot.core.errors import CogLoadError

from .commands import user_slash_command
from .context import InterContext
from .patcher import apply_user_install_native, patch_all_commands
from .utils import valid_app_name

LOG = logging.getLogger("red.evecogs.userslash")

__red_end_user_data_statement__ = (
    "This cog does not persistently store any data or metadata about users."
)


class UserSlash(commands.Cog):
    """User-installable slash commands for every Red command."""

    def __init__(self, bot: Red):
        self.bot = bot
        self._slash_registered = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def cog_load(self) -> None:
        self.bot.before_invoke(self._before_hook)
        self.bot.add_dev_env_value(
            "interaction", lambda ctx: getattr(ctx, "interaction", None)
        )
        asyncio.create_task(self._delayed_setup())  # noqa: RUF006

    async def cog_unload(self) -> None:
        self.bot.remove_before_invoke_hook(self._before_hook)
        try:
            self.bot.remove_dev_env_value("interaction")
        except Exception:
            pass
        if self._slash_registered:
            self.bot.tree.remove_command(user_slash_command.name, guild=None)

    async def _delayed_setup(self) -> None:
        """Wait for the bot to be fully ready, then register the slash command."""
        await self.bot.wait_until_red_ready()
        assert self.bot.user

        # Apply native user-install flags (discord.py 2.4+)
        apply_user_install_native(user_slash_command)

        try:
            user_slash_command.name = valid_app_name(self.bot.user.name)
            self.bot.tree.add_command(user_slash_command, guild=None)
            self._slash_registered = True
            LOG.info(
                "Registered /%s as user-installable proxy command.",
                user_slash_command.name,
            )
        except ValueError:
            await self.bot.send_to_owners(
                f"`userslash` could not convert the name {self.bot.user.name!r} "
                "into a valid slash-command name.  The name was left unchanged."
            )
        except app_commands.CommandAlreadyRegistered:
            raise CogLoadError(
                f"A slash command named `{user_slash_command.name}` is already "
                "registered.  Unload **OneTrueSlash** (or the conflicting cog) first."
            ) from None
        except app_commands.CommandLimitReached:
            raise CogLoadError(
                f"{self.bot.user.name} has reached the 100-command global limit."
            ) from None

    # ------------------------------------------------------------------
    # Hooks & listeners
    # ------------------------------------------------------------------

    @staticmethod
    async def _before_hook(ctx: commands.Context) -> None:
        """Attach the real Interaction to the context so hybrid commands work."""
        interaction: Optional[discord.Interaction] = getattr(
            ctx, "_interaction", None
        )
        if not interaction or getattr(ctx.command, "__commands_is_hybrid__", False):
            return
        ctx.interaction = interaction  # type: ignore[attr-defined]
        if not interaction.response.is_done():
            ctx._deferring = True  # type: ignore[attr-defined]
            await interaction.response.defer(ephemeral=False)

    @commands.Cog.listener()
    async def on_user_update(
        self, before: discord.User, after: discord.User
    ) -> None:
        """Update the slash-command name when the bot's username changes."""
        assert self.bot.user
        if after.id != self.bot.user.id or before.name == after.name:
            return

        old_name = user_slash_command.name
        try:
            user_slash_command.name = valid_app_name(after.name)
        except ValueError:
            await self.bot.send_to_owners(
                f"`userslash` could not convert {after.name!r} into a valid "
                "slash-command name.  The name was left unchanged."
            )
            return

        self.bot.tree.remove_command(old_name)
        apply_user_install_native(user_slash_command)
        self.bot.tree.add_command(user_slash_command, guild=None)
        await self.bot.send_to_owners(
            "The bot's username changed.  `userslash`'s slash command has been "
            "updated.\n**Run `[p]userslash sync` to push the change to Discord.**"
        )

    # ------------------------------------------------------------------
    # Owner commands
    # ------------------------------------------------------------------

    @commands.is_owner()
    @commands.group(name="userslash")
    async def _userslash(self, ctx: commands.Context) -> None:
        """Manage UserSlash — the user-installable slash bridge."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @_userslash.command(name="sync")
    async def _sync(self, ctx: commands.Context) -> None:
        """Sync the command tree, then patch every command for user-install."""
        msg = await ctx.send("⏳ Syncing command tree…")

        try:
            synced = await self.bot.tree.sync()
        except discord.HTTPException as exc:
            await msg.edit(content=f"❌ Sync failed: {exc}")
            return

        await msg.edit(
            content=f"✅ Synced **{len(synced)}** commands.  Patching user-install flags…"
        )

        try:
            patched, total = await patch_all_commands(self.bot)
            await msg.edit(
                content=(
                    f"✅ **Done!**  Synced {len(synced)} commands — "
                    f"patched {patched}/{total} with user-install flags.\n"
                    "Users can now install the bot to their profile and use "
                    "commands in DMs & group DMs."
                )
            )
        except discord.HTTPException as exc:
            await msg.edit(
                content=(
                    f"⚠️ Synced {len(synced)} commands but patching failed: {exc}\n"
                    "Try `[p]userslash patch` again in a moment."
                )
            )

    @_userslash.command(name="patch")
    async def _patch(self, ctx: commands.Context) -> None:
        """Patch already-registered commands with user-install flags (no full sync)."""
        msg = await ctx.send("⏳ Patching commands…")
        try:
            patched, total = await patch_all_commands(self.bot)
            await msg.edit(
                content=f"✅ Patched **{patched}/{total}** commands with user-install flags."
            )
        except discord.HTTPException as exc:
            await msg.edit(content=f"❌ Patching failed: {exc}")

    @_userslash.command(name="status")
    async def _status(self, ctx: commands.Context) -> None:
        """Show user-install status for every registered global command."""
        try:
            from .patcher import get_global_commands

            cmds = await get_global_commands(self.bot)
        except Exception as exc:
            await ctx.send(f"❌ Could not fetch commands: {exc}")
            return

        if not cmds:
            await ctx.send("No global commands are registered.")
            return

        lines = []
        for cmd in cmds:
            types = cmd.get("integration_types", [0])
            ctxs = cmd.get("contexts") or [0]
            user_ok = 1 in types
            dm_ok = 1 in ctxs
            gdm_ok = 2 in ctxs
            ok = user_ok and dm_ok and gdm_ok
            lines.append(
                f"{'✅' if ok else '⚠️'} `/{cmd['name']}` — "
                f"User: {'Yes' if user_ok else 'No'} · "
                f"DM: {'Yes' if dm_ok else 'No'} · "
                f"Group: {'Yes' if gdm_ok else 'No'}"
            )

        # Paginate if needed (2000 char limit)
        page = []
        length = 0
        for line in lines:
            if length + len(line) + 1 > 1900:
                await ctx.send("\n".join(page))
                page = []
                length = 0
            page.append(line)
            length += len(line) + 1
        if page:
            await ctx.send("\n".join(page))


async def setup(bot: Red) -> None:
    await bot.add_cog(UserSlash(bot))
