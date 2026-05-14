"""
Per-network hierarchical permission system for Wormhole.

Roles are scoped to individual networks — a user can be Admin in one
network and have no role in another.  Bot owners (Red's built-in
``bot.is_owner()``) bypass all checks globally.

Hierarchy (highest → lowest):
    Owner → Admin → Moderator → Helper → Member

Higher roles can assign any role below them.
"""

from __future__ import annotations

import enum
import functools
from typing import Optional

import discord
from redbot.core import commands


class Role(enum.IntEnum):
    """Network permission tiers.  Higher value = more power."""

    MEMBER = 0
    HELPER = 1
    MODERATOR = 2
    ADMIN = 3
    OWNER = 4


_ROLE_NAMES = {
    Role.OWNER: "Owner",
    Role.ADMIN: "Admin",
    Role.MODERATOR: "Moderator",
    Role.HELPER: "Helper",
    Role.MEMBER: "Member",
}

_ROLE_LOOKUP = {v.lower(): k for k, v in _ROLE_NAMES.items()}


def role_name(role: Role) -> str:
    """Human-friendly name for a role."""
    return _ROLE_NAMES.get(role, "Unknown")


def role_from_str(name: str) -> Optional[Role]:
    """Parse a role name (case-insensitive).  Returns ``None`` on failure."""
    return _ROLE_LOOKUP.get(name.strip().lower())


def _get_user_role(net_data: dict, user_id: int) -> Role:
    """Determine a user's role in a network from its config dict."""
    if user_id == net_data.get("owner_id"):
        return Role.OWNER
    staff = net_data.get("staff", {})
    uid_str = str(user_id)
    if uid_str in staff:
        return Role(staff[uid_str])
    # Legacy flat list migration: treat old staff_ids entries as Admin
    if user_id in net_data.get("staff_ids", []):
        return Role.ADMIN
    return Role.MEMBER


def has_role(net_data: dict, user_id: int, minimum: Role) -> bool:
    """Check whether *user_id* meets *minimum* role in this network."""
    return _get_user_role(net_data, user_id) >= minimum


def get_role(net_data: dict, user_id: int) -> Role:
    """Return the user's role in a network."""
    return _get_user_role(net_data, user_id)


def can_assign(actor_role: Role, target_role: Role) -> bool:
    """Whether *actor_role* is allowed to assign/revoke *target_role*."""
    return actor_role > target_role


def set_staff_role(net_data: dict, user_id: int, role: Role) -> None:
    """Assign *role* to *user_id* in the network config (mutates in place).

    Setting ``Role.MEMBER`` removes the user from the staff dict.
    """
    staff = net_data.setdefault("staff", {})
    uid_str = str(user_id)
    if role <= Role.MEMBER:
        staff.pop(uid_str, None)
    else:
        staff[uid_str] = int(role)


def remove_staff(net_data: dict, user_id: int) -> None:
    """Remove a user from network staff entirely."""
    set_staff_role(net_data, user_id, Role.MEMBER)


def list_staff(net_data: dict) -> dict[int, Role]:
    """Return ``{user_id: Role}`` for all staff (including owner)."""
    result: dict[int, Role] = {}
    owner = net_data.get("owner_id")
    if owner:
        result[owner] = Role.OWNER
    for uid_str, level in net_data.get("staff", {}).items():
        try:
            result[int(uid_str)] = Role(level)
        except (ValueError, KeyError):
            pass
    # Legacy migration
    for uid in net_data.get("staff_ids", []):
        if uid not in result:
            result[uid] = Role.ADMIN
    return result


# ── Decorator for commands ─────────────────────────────────────────────────

def requires_role(minimum: Role):
    """Decorator factory — the command must supply *name* as first arg.

    Usage inside a cog::

        @commands.command()
        @requires_role(Role.MODERATOR)
        async def wh_mod_ban(self, ctx, name: str, user: discord.User):
            ...

    The decorator fetches the network data for *name*, checks the
    invoker's role, and short-circuits with an error embed if they
    lack permission.  Bot owners always pass.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, ctx: commands.Context, name: str, *args, **kwargs):
            # Bot owner bypasses everything
            if await self.bot.is_owner(ctx.author):
                return await func(self, ctx, name, *args, **kwargs)
            # Fetch network
            nd = await self._net(name)
            if nd is None:
                from ..utils import err_embed
                await ctx.send(embed=err_embed(f"Network `{name}` not found."))
                return
            if not has_role(nd, ctx.author.id, minimum):
                from ..utils import err_embed
                await ctx.send(
                    embed=err_embed(
                        f"You need at least **{role_name(minimum)}** "
                        f"role in `{name}` to use this command."
                    )
                )
                return
            return await func(self, ctx, name, *args, **kwargs)

        return wrapper

    return decorator
