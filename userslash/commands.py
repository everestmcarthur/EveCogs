"""
The proxy slash command and its autocomplete / error handler.

This is the heart of UserSlash: a single ``/botname`` command that bridges
*every* Red text command through Discord's slash-command interface, with
full support for DM / group-DM / non-member-guild contexts.
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

LOG = logging.getLogger("red.evecogs.userslash.commands")


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
    Run any bot command from anywhere — servers, DMs, and group DMs.

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

    if current:
        extracted = cast(
            List[str],
            await asyncio.get_event_loop().run_in_executor(
                None,
                heapq.nlargest,
                6,
                walk_aliases(
                    interaction.client, show_hidden=help_settings.show_hidden
                ),
                functools.partial(fuzz.token_sort_ratio, current),
            ),
        )
        extracted.append("help")
    else:
        extracted = ["help"]

    _filter: Callable[[commands.Command], Awaitable[bool]] = (
        operator.methodcaller(
            "can_run" if help_settings.show_hidden else "can_see", ctx
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
