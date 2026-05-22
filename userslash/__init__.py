"""
UserSlash — User-installable slash-command bridge for Red-DiscordBot.

Replaces OneTrueSlash.  Registers a single proxy slash command (named after
the bot) that makes *every* Red text command accessible via slash — in
servers, DMs, and group DMs.  After syncing, all global commands are
automatically patched with ``integration_types: [0, 1]`` and
``contexts: [0, 1, 2]`` so the bot works as a user-installable app.

Owner commands:
    [p]userslash sync      — Sync the command tree + patch user-install flags
    [p]userslash patch     — Patch flags on already-synced commands
    [p]userslash status    — Show per-command user-install status
    [p]userslash whitelist — Manage the user-install whitelist
"""

import asyncio
import logging
from typing import Optional

import discord
from redbot.core import Config, app_commands, commands
from redbot.core.bot import Red
from redbot.core.errors import CogLoadError

from .slash_bridge import user_slash_command
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
        self.config = Config.get_conf(self, identifier=0x55534C41534800, force_registration=True)
        self.config.register_global(
            whitelist_enabled=False,
            whitelisted_users=[],
            description="",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def cog_load(self) -> None:
        # Expose config to the slash bridge module for whitelist checks
        user_slash_command.extras["_userslash_config"] = self.config
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

        # Clean up context variable to prevent leaks
        from .utils import contexts
        try:
            contexts.set(None)  # type: ignore
        except (LookupError, TypeError):
            pass  # Already empty

    async def _delayed_setup(self) -> None:
        """Wait for the bot to be fully ready, then register the slash command."""
        await self.bot.wait_until_red_ready()
        assert self.bot.user

        # Apply custom description if set
        custom_desc = await self.config.description()
        if custom_desc:
            user_slash_command.description = custom_desc

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

    @_userslash.command(name="setdescription", aliases=["setdesc"])
    async def _setdesc(self, ctx: commands.Context, *, description: str = "") -> None:
        """Set a custom description for the slash command.

        The description appears under the ``/botname`` command in the Discord UI.
        Pass no argument (or an empty string) to reset to the default.

        Run ``[p]userslash sync`` afterwards to push the change to Discord.

        Example: ``[p]userslash setdescription Shine bright like a Ruby``
        """
        if not description.strip():
            await self.config.description.set("")
            user_slash_command.description = (
                "Shine bright like a Ruby"
            )
            await ctx.send(
                "✅ Description reset to default.  "
                "Run `[p]userslash sync` to push the change."
            )
        else:
            description = description[:100]  # Discord limit
            await self.config.description.set(description)
            user_slash_command.description = description
            await ctx.send(
                f"✅ Description set to: *{description}*\n"
                "Run `[p]userslash sync` to push the change."
            )

    # ------------------------------------------------------------------
    # Whitelist commands
    # ------------------------------------------------------------------

    @_userslash.group(name="whitelist", aliases=["wl"])
    async def _whitelist(self, ctx: commands.Context) -> None:
        """Manage the user-install whitelist.

        When enabled, only whitelisted users can use the bot via user-install
        (DMs, group DMs, and non-member guilds).  Guild-installed usage is
        unaffected.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @_whitelist.command(name="enable")
    async def _wl_enable(self, ctx: commands.Context) -> None:
        """Enable the user-install whitelist."""
        await self.config.whitelist_enabled.set(True)
        await ctx.send("✅ User-install whitelist is now *enabled*. Only whitelisted users can use the bot outside of guilds.")

    @_whitelist.command(name="disable")
    async def _wl_disable(self, ctx: commands.Context) -> None:
        """Disable the user-install whitelist (anyone can use user-install)."""
        await self.config.whitelist_enabled.set(False)
        await ctx.send("✅ User-install whitelist is now *disabled*. Anyone can use the bot via user-install.")

    @_whitelist.command(name="add")
    async def _wl_add(self, ctx: commands.Context, *users: discord.User) -> None:
        """Add one or more users to the whitelist.

        Example: `[p]userslash whitelist add @User1 @User2`
        """
        if not users:
            await ctx.send("❌ Provide at least one user to add.")
            return
        async with self.config.whitelisted_users() as wl:
            added = []
            for user in users:
                if user.id not in wl:
                    wl.append(user.id)
                    added.append(str(user))
            if added:
                await ctx.send(f"✅ Added to whitelist: {', '.join(added)}")
            else:
                await ctx.send("ℹ️ All specified users are already whitelisted.")

    @_whitelist.command(name="remove", aliases=["rm"])
    async def _wl_remove(self, ctx: commands.Context, *users: discord.User) -> None:
        """Remove one or more users from the whitelist.

        Example: `[p]userslash whitelist remove @User1`
        """
        if not users:
            await ctx.send("❌ Provide at least one user to remove.")
            return
        async with self.config.whitelisted_users() as wl:
            removed = []
            for user in users:
                if user.id in wl:
                    wl.remove(user.id)
                    removed.append(str(user))
            if removed:
                await ctx.send(f"✅ Removed from whitelist: {', '.join(removed)}")
            else:
                await ctx.send("ℹ️ None of the specified users were on the whitelist.")

    @_whitelist.command(name="list", aliases=["ls"])
    async def _wl_list(self, ctx: commands.Context) -> None:
        """Show the current whitelist and its status."""
        enabled = await self.config.whitelist_enabled()
        wl = await self.config.whitelisted_users()
        status = "🟢 Enabled" if enabled else "🔴 Disabled"

        if not wl:
            await ctx.send(f"**Whitelist status:** {status}\n\nThe whitelist is empty.")
            return

        lines = []
        for uid in wl:
            user = self.bot.get_user(uid)
            lines.append(f"• {user} (`{uid}`)" if user else f"• Unknown user (`{uid}`)")

        header = f"**Whitelist status:** {status}\n**{len(wl)}** user(s):\n"
        page = [header]
        length = len(header)
        for line in lines:
            if length + len(line) + 1 > 1900:
                await ctx.send("\n".join(page))
                page = []
                length = 0
            page.append(line)
            length += len(line) + 1
        if page:
            await ctx.send("\n".join(page))

    @_whitelist.command(name="clear")
    async def _wl_clear(self, ctx: commands.Context) -> None:
        """Remove all users from the whitelist."""
        await self.config.whitelisted_users.set([])
        await ctx.send("✅ Whitelist has been cleared.")


async def setup(bot: Red) -> None:
    await bot.add_cog(UserSlash(bot))
