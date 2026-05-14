"""
The proxy slash command and its autocomplete / error handler.

This is the heart of UserSlash: a single ``/botname`` command that bridges
*every* Red text command through Discord's slash-command interface, with
full support for DM / group-DM / non-member-guild contexts.

Renamed from ``commands.py`` to ``slash_bridge.py`` to avoid shadowing
``redbot.core.commands`` inside the package.
"""

import asyncio
import functools
import heapq
import logging
import operator
from copy import copy
from typing import Awaitable, Callable, Dict, List, Optional, Tuple, cast

import discord
from rapidfuzz import fuzz
from redbot.core import app_commands, commands
from redbot.core.bot import Red
from redbot.core.commands.help import HelpSettings
from redbot.core.i18n import set_contextual_locale

from .context import InterContext
from .utils import walk_aliases

LOG = logging.getLogger("red.evecogs.userslash.slash_bridge")


# ------------------------------------------------------------------
# Context helpers
# ------------------------------------------------------------------

def _is_user_install_context(interaction: discord.Interaction) -> bool:
    """True when the interaction originates outside a guild the bot is a member of."""
    return not interaction.guild or not getattr(interaction.guild, "me", None)


def _command_needs_guild(cmd: commands.Command) -> bool:
    """Heuristic: return True if *cmd* almost certainly requires a guild context.

    Walks the parent chain so subcommands inherit their parent's requirements.
    Checks:
    - ``@commands.guild_only()`` / ``@commands.no_pm()`` in discord.py checks
    - Red privilege levels (MOD, ADMIN, GUILD_OWNER)
    - Explicit ``user_perms`` on Red's ``Requires`` object
    """
    current: Optional[commands.Command] = cmd
    while current is not None:
        # discord.py @guild_only() / @no_pm()
        for check in getattr(current, "checks", ()):
            qn = getattr(check, "__qualname__", "")
            if "guild_only" in qn or "no_pm" in qn:
                return True

        # Red's Requires system
        requires = getattr(current, "requires", None)
        if requires is not None:
            # MOD=1, ADMIN=2, GUILD_OWNER=3 all require a guild
            priv = getattr(requires, "privilege_level", None)
            if priv is not None:
                try:
                    if priv.value in (1, 2, 3):
                        return True
                except (AttributeError, ValueError):
                    pass

            # Explicit user-permission requirements (manage_guild, etc.)
            user_perms = getattr(requires, "user_perms", None)
            if user_perms is not None:
                try:
                    if isinstance(user_perms, discord.Permissions) and user_perms.value != 0:
                        return True
                except Exception:
                    pass

        current = getattr(current, "parent", None)
    return False


# ------------------------------------------------------------------
# Whitelist helper
# ------------------------------------------------------------------

async def _check_whitelist(interaction: discord.Interaction) -> bool:
    """Return True if the user is allowed, False if blocked by the whitelist.

    The whitelist only applies to *user-install* contexts (no guild, or a guild
    the bot isn't a member of).  Guild-installed usage is always permitted.
    """
    config = getattr(
        interaction.command, "extras", {}
    ).get("_userslash_config")
    if config is None:
        return True  # config not wired yet — allow

    # If the bot is a full member of this guild, skip the whitelist
    if interaction.guild and interaction.guild.me:
        return True

    if not await config.whitelist_enabled():
        return True

    whitelist: list = await config.whitelisted_users()
    return interaction.user.id in whitelist


# ------------------------------------------------------------------
# The one true (user-installable) slash command
# ------------------------------------------------------------------

@app_commands.command(extras={"red_force_enable": True})
async def user_slash_command(
    interaction: discord.Interaction,
    command: str,
    arguments: Optional[str] = None,
    attachment: Optional[discord.Attachment] = None,
) -> None:
    """
    Shine bright like a Ruby

    Parameters
    -----------
    command: str
        The text-based command to run.
    arguments: Optional[str]
        The arguments to provide to the command, if any.
    attachment: Optional[Attachment]
        An attached file to provide to the command, if any.
    """
    assert isinstance(interaction.client, Red)
    set_contextual_locale(str(interaction.guild_locale or interaction.locale))

    # --- Whitelist gate ---
    if not await _check_whitelist(interaction):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ You are not authorised to use this bot via user-install. "
                "Ask a bot owner to add you with `[p]userslash whitelist add`.",
                ephemeral=True,
            )
        return

    # --- Block guild-only commands in user-install contexts ---
    if _is_user_install_context(interaction):
        probe = interaction.client.get_command(command)
        if probe and _command_needs_guild(probe):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ `{command}` requires a server context and can't be "
                    "used in DMs, group DMs, or servers the bot isn't in.",
                    ephemeral=True,
                )
            return

    actual = interaction.client.get_command(command)
    ctx = await InterContext.from_interaction(interaction, recreate_message=True)
    error = None

    if command == "help":
        ctx._deferring = True
        await interaction.response.defer(ephemeral=True)
        actual = None
        if arguments:
            actual = interaction.client.get_command(arguments)
            if actual and (signature := actual.signature):
                actual = copy(actual)
                actual.usage = f"arguments:{signature}"
        await interaction.client.send_help_for(
            ctx, actual or interaction.client, from_help_command=True
        )
    else:
        ferror: asyncio.Task[Tuple[InterContext, commands.CommandError]] = (
            asyncio.create_task(
                interaction.client.wait_for(
                    "command_error", check=lambda c, _: c is ctx
                )
            )
        )
        ferror.add_done_callback(
            lambda _: setattr(ctx, "interaction", interaction)
        )
        await interaction.client.invoke(ctx)
        if not interaction.response.is_done():
            ctx._deferring = True
            await interaction.response.defer(ephemeral=True)
        if ferror.done():
            error = ferror.exception() or ferror.result()[1]
        ferror.cancel()

    # ---- Followup / cleanup ----
    if ctx._deferring and not interaction.is_expired():
        if error is None:
            if ctx._ticked:
                await interaction.followup.send(ctx._ticked, ephemeral=True)
            else:
                await interaction.delete_original_response()

        elif isinstance(error, commands.CommandNotFound):
            await interaction.followup.send(
                f"❌ Command `{command}` was not found.", ephemeral=True
            )

        elif isinstance(error, commands.NoPrivateMessage):
            await interaction.followup.send(
                f"❌ `{command}` can only be used inside a server.",
                ephemeral=True,
            )

        elif isinstance(error, commands.CheckFailure):
            if not interaction.guild:
                await interaction.followup.send(
                    f"❌ `{command}` requires a server context or you lack the "
                    "needed permissions.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ You don't have permission to run `{command}`.",
                    ephemeral=True,
                )


# ------------------------------------------------------------------
# Autocomplete — fuzzy-matches available commands
# ------------------------------------------------------------------

@user_slash_command.autocomplete("command")
async def _autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    assert isinstance(interaction.client, Red)

    # --- Whitelist gate ---
    if not await _check_whitelist(interaction):
        return []

    try:
        if not await interaction.client.allowed_by_whitelist_blacklist(
            interaction.user
        ):
            return []
    except Exception:
        pass  # safety net for unusual DM contexts

    try:
        ctx = await InterContext.from_interaction(interaction)
        eligible = await interaction.client.message_eligible_as_command(
            ctx.message
        )
    except Exception:
        eligible = True  # slash interactions are always "eligible"
        ctx = await InterContext.from_interaction(interaction)

    if not eligible:
        # Still provide basic help for slash
        return [app_commands.Choice(name="help", value="help")]

    try:
        help_settings = await HelpSettings.from_context(ctx)
    except Exception:
        # Fallback settings when guild config is unavailable
        help_settings = await HelpSettings.from_context.__wrapped__(ctx)  # type: ignore

    user_install = _is_user_install_context(interaction)
    show_hidden = help_settings.show_hidden

    # Build the candidate pool — in user-install contexts, pre-filter to
    # commands that can actually work outside a guild.
    all_names = list(
        walk_aliases(interaction.client, show_hidden=show_hidden)
    )

    if user_install:
        pool: List[str] = []
        for n in all_names:
            cmd = interaction.client.get_command(n)
            if cmd and not _command_needs_guild(cmd):
                pool.append(n)
    else:
        pool = all_names

    if current:
        extracted = cast(
            List[str],
            await asyncio.get_event_loop().run_in_executor(
                None,
                heapq.nlargest,
                24 if user_install else 6,
                pool,
                functools.partial(fuzz.token_sort_ratio, current),
            ),
        )
        extracted.append("help")
    else:
        if user_install:
            # Show available DM-compatible commands when nothing is typed yet
            extracted = pool[:24]
            extracted.append("help")
        else:
            extracted = ["help"]

    _filter: Callable[[commands.Command], Awaitable[bool]] = (
        operator.methodcaller(
            "can_run" if show_hidden else "can_see", ctx
        )
    )
    matches: Dict[commands.Command, str] = {}
    for name in extracted:
        cmd = interaction.client.get_command(name)
        if not cmd or cmd in matches:
            continue
        try:
            if (name == "help" and await cmd.can_run(ctx)) or await _filter(cmd):
                if len(name) > 100:
                    name = name[:99] + "\N{HORIZONTAL ELLIPSIS}"
                matches[cmd] = name
        except commands.CommandError:
            pass
        except Exception:
            # Swallow unexpected errors in DM/group-DM contexts so autocomplete
            # still returns *something*.
            pass
    return [app_commands.Choice(name=n, value=n) for n in matches.values()]


# ------------------------------------------------------------------
# Error handler
# ------------------------------------------------------------------

@user_slash_command.error
async def _error(interaction: discord.Interaction, error: Exception):
    assert isinstance(interaction.client, Red)

    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original
    original = getattr(error, "original", error)

    # Friendly message for guild-only commands invoked outside a guild
    if isinstance(original, (commands.NoPrivateMessage, commands.CheckFailure)):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ This command cannot be used here (it may require a server).",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "❌ This command cannot be used here (it may require a server).",
                    ephemeral=True,
                )
        except discord.HTTPException:
            pass
        return

    # Everything else — forward to Red's built-in error handler
    ctx = await InterContext.from_interaction(
        interaction, recreate_message=True
    )
    await interaction.client.on_command_error(
        ctx, commands.CommandInvokeError(original)
    )
