"""Staff management commands — assign roles, list staff, transfer ownership."""

from __future__ import annotations

import discord
from redbot.core import commands

from ..models.permissions import (
    Role,
    can_assign,
    get_role,
    has_role,
    list_staff,
    requires_role,
    role_from_str,
    role_name,
    set_staff_role,
    remove_staff,
)
from ..utils import ok_embed, err_embed, info_embed, COLOUR_INFO


class StaffCommands:
    """Mixin — staff management (per-network hierarchy)."""

    @commands.group(name="wh-staff", aliases=["whstaff"], invoke_without_command=True)
    async def wh_staff(self, ctx: commands.Context) -> None:
        """Manage network staff — add, remove, list, promote, demote."""
        await ctx.send_help(ctx.command)

    @wh_staff.command(name="add")
    async def wh_staff_add(self, ctx: commands.Context, name: str, user: discord.User, role_str: str = "moderator") -> None:
        """Assign a staff role to a user.

        Roles: ``admin``, ``moderator``, ``helper``
        """
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))

        target_role = role_from_str(role_str)
        if target_role is None or target_role <= Role.MEMBER or target_role >= Role.OWNER:
            return await ctx.send(embed=err_embed("Valid roles: `admin`, `moderator`, `helper`."))

        actor_role = get_role(nd, ctx.author.id)
        is_bot_owner = await self.bot.is_owner(ctx.author)
        if not is_bot_owner and not can_assign(actor_role, target_role):
            return await ctx.send(embed=err_embed(
                f"You need a higher role than **{role_name(target_role)}** to assign it.\n"
                f"Your role: **{role_name(actor_role)}**"
            ))

        async with self.config.networks() as ns:
            set_staff_role(ns[name], user.id, target_role)
        await ctx.send(embed=ok_embed(
            f"{user.mention} is now **{role_name(target_role)}** in `{name}`."
        ))
        await self._audit(name, "staff_add", str(ctx.author), str(user), f"role={role_name(target_role)}")

    @wh_staff.command(name="remove", aliases=["rm"])
    async def wh_staff_rm(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Remove a user from network staff."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))

        target_role = get_role(nd, user.id)
        if target_role <= Role.MEMBER:
            return await ctx.send(embed=err_embed(f"{user} isn't staff in `{name}`."))

        actor_role = get_role(nd, ctx.author.id)
        is_bot_owner = await self.bot.is_owner(ctx.author)
        if not is_bot_owner and not can_assign(actor_role, target_role):
            return await ctx.send(embed=err_embed(
                f"You can't remove a **{role_name(target_role)}** — "
                f"your role: **{role_name(actor_role)}**"
            ))

        async with self.config.networks() as ns:
            remove_staff(ns[name], user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} removed from staff in `{name}`."))
        await self._audit(name, "staff_rm", str(ctx.author), str(user))

    @wh_staff.command(name="promote")
    async def wh_staff_promote(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Promote a staff member one tier up."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))

        current = get_role(nd, user.id)
        if current >= Role.ADMIN:
            return await ctx.send(embed=err_embed(f"{user} is already **{role_name(current)}** — can't promote further."))
        new_role = Role(current + 1)
        if new_role >= Role.OWNER:
            return await ctx.send(embed=err_embed("Can't promote to Owner. Use `wh transfer` instead."))

        actor_role = get_role(nd, ctx.author.id)
        is_bot_owner = await self.bot.is_owner(ctx.author)
        if not is_bot_owner and not can_assign(actor_role, new_role):
            return await ctx.send(embed=err_embed(
                f"You can't assign **{role_name(new_role)}** — "
                f"your role: **{role_name(actor_role)}**"
            ))

        async with self.config.networks() as ns:
            set_staff_role(ns[name], user.id, new_role)
        await ctx.send(embed=ok_embed(
            f"{user.mention} promoted: **{role_name(current)}** → **{role_name(new_role)}** in `{name}`."
        ))
        await self._audit(name, "promote", str(ctx.author), str(user), f"{role_name(current)} → {role_name(new_role)}")

    @wh_staff.command(name="demote")
    async def wh_staff_demote(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Demote a staff member one tier down."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))

        current = get_role(nd, user.id)
        if current <= Role.MEMBER:
            return await ctx.send(embed=err_embed(f"{user} isn't staff in `{name}`."))
        if current >= Role.OWNER:
            return await ctx.send(embed=err_embed("Can't demote the Owner. Use `wh transfer` first."))

        new_role = Role(current - 1)

        actor_role = get_role(nd, ctx.author.id)
        is_bot_owner = await self.bot.is_owner(ctx.author)
        if not is_bot_owner and not can_assign(actor_role, current):
            return await ctx.send(embed=err_embed(
                f"You can't demote a **{role_name(current)}** — "
                f"your role: **{role_name(actor_role)}**"
            ))

        async with self.config.networks() as ns:
            if new_role <= Role.MEMBER:
                remove_staff(ns[name], user.id)
            else:
                set_staff_role(ns[name], user.id, new_role)
        label = role_name(new_role) if new_role > Role.MEMBER else "Member (removed from staff)"
        await ctx.send(embed=ok_embed(
            f"{user.mention} demoted: **{role_name(current)}** → **{label}** in `{name}`."
        ))
        await self._audit(name, "demote", str(ctx.author), str(user), f"{role_name(current)} → {label}")

    @wh_staff.command(name="list", aliases=["ls"])
    async def wh_staff_ls(self, ctx: commands.Context, name: str) -> None:
        """List all staff in a network with their roles."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))

        staff = list_staff(nd)
        if not staff:
            return await ctx.send(embed=info_embed(f"No staff in `{name}`."))

        lines = []
        for uid, role in sorted(staff.items(), key=lambda x: -x[1]):
            user = self.bot.get_user(uid)
            display = str(user) if user else f"Unknown ({uid})"
            emoji = {Role.OWNER: "👑", Role.ADMIN: "🛡️", Role.MODERATOR: "⚔️", Role.HELPER: "🤝"}.get(role, "")
            lines.append(f"{emoji} **{role_name(role)}** — {display}")

        em = discord.Embed(
            title=f"👥 Staff — {name}",
            description="\n".join(lines),
            colour=COLOUR_INFO,
        )
        await ctx.send(embed=em)

    @commands.hybrid_command(name="wh-transfer")
    async def wh_transfer(self, ctx: commands.Context, name: str, new_owner: discord.User) -> None:
        """Transfer network ownership (owner or bot owner only)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if not has_role(nd, ctx.author.id, Role.OWNER) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Only the network owner or bot owner can transfer ownership."))

        old_owner = nd["owner_id"]
        async with self.config.networks() as ns:
            ns[name]["owner_id"] = new_owner.id
            # Demote old owner to Admin if they're not the bot owner
            if old_owner != new_owner.id:
                set_staff_role(ns[name], old_owner, Role.ADMIN)
                # Remove new owner from staff dict (they're owner now)
                remove_staff(ns[name], new_owner.id)

        await ctx.send(embed=ok_embed(
            f"Ownership of `{name}` transferred to {new_owner.mention}.\n"
            f"Previous owner demoted to Admin."
        ))
        await self._audit(name, "transfer", str(ctx.author), str(new_owner))
