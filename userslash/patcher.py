"""
REST-API patcher — ensures every global application command carries
``integration_types: [0, 1]`` and ``contexts: [0, 1, 2]`` so the bot
is user-installable and works in guilds, DMs, and group DMs.
"""

import logging
from typing import Any, Dict, List, Tuple

import discord
from redbot.core.bot import Red

LOG = logging.getLogger("red.evecogs.userslash.patcher")

# 0 = GUILD_INSTALL, 1 = USER_INSTALL
INTEGRATION_TYPES: List[int] = [0, 1]
# 0 = GUILD, 1 = BOT_DM, 2 = PRIVATE_CHANNEL (group DMs)
CONTEXTS: List[int] = [0, 1, 2]


# ------------------------------------------------------------------
# Native discord.py 2.4+ helpers (best-effort)
# ------------------------------------------------------------------

def apply_user_install_native(command: Any) -> bool:
    """
    Try to set ``allowed_installs`` / ``allowed_contexts`` using the
    native discord.py 2.4+ API.  Returns ``True`` on success.
    """
    try:
        from discord.app_commands import AppInstallationType, AppCommandContext

        command.allowed_installs = AppInstallationType(guild=True, user=True)
        command.allowed_contexts = AppCommandContext(
            guild=True, dm_channel=True, private_channel=True
        )
        return True
    except (ImportError, AttributeError, TypeError):
        return False


# ------------------------------------------------------------------
# REST fallback — works with any discord.py version
# ------------------------------------------------------------------

async def get_global_commands(bot: Red) -> List[Dict[str, Any]]:
    """Fetch every registered global command from the Discord API."""
    app_id = bot.application_id
    if not app_id:
        raise RuntimeError("Bot application_id is not available yet.")
    route = discord.http.Route(
        "GET",
        "/applications/{application_id}/commands",
        application_id=app_id,
    )
    return await bot.http.request(route)


async def patch_command(
    bot: Red,
    command_id: int | str,
    *,
    integration_types: List[int] = INTEGRATION_TYPES,
    cmd_contexts: List[int] = CONTEXTS,
) -> Dict[str, Any]:
    """PATCH a single global command with user-install flags."""
    route = discord.http.Route(
        "PATCH",
        "/applications/{application_id}/commands/{command_id}",
        application_id=bot.application_id,
        command_id=command_id,
    )
    return await bot.http.request(
        route,
        json={
            "integration_types": integration_types,
            "contexts": cmd_contexts,
        },
    )


async def patch_all_commands(bot: Red) -> Tuple[int, int]:
    """
    Patch **all** global commands that are missing user-install flags.

    Returns ``(patched_count, total_count)``.
    """
    commands = await get_global_commands(bot)
    target_types = set(INTEGRATION_TYPES)
    target_contexts = set(CONTEXTS)

    patched = 0
    for cmd in commands:
        current_types = set(cmd.get("integration_types", [0]))
        current_contexts = set(cmd.get("contexts") or [0])

        if current_types == target_types and current_contexts == target_contexts:
            continue  # already good

        try:
            await patch_command(bot, cmd["id"])
            patched += 1
            LOG.info(
                "Patched command /%s (%s) with user-install flags.",
                cmd["name"],
                cmd["id"],
            )
        except discord.HTTPException as exc:
            LOG.warning("Failed to patch /%s: %s", cmd["name"], exc)

    return patched, len(commands)
