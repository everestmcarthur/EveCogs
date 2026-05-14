"""Network lifecycle commands — create, delete, open, close, list, discover, info."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

import discord
from redbot.core import commands

from ..models.config import DEFAULT_NETWORK
from ..models.permissions import Role, has_role, requires_role, role_name, get_role, list_staff
from ..utils import ok_embed, err_embed, info_embed, warn_embed, COLOUR_INFO, COLOUR_OK, truncate
from ._base import WormholeBase


class NetworkCommands(WormholeBase):
    """Mixin — network lifecycle commands."""

    @WormholeBase.wh.command(name="create")
    async def wh_create(self, ctx: commands.Context, name: str, *, description: str = "") -> None:
        """Create a new wormhole network."""
        nets = await self.config.networks()
        if name in nets:
            return await ctx.send(embed=err_embed(f"Network `{name}` already exists."))
        mx = await self.config.max_networks_per_user()
        if sum(1 for n in nets.values() if n["owner_id"] == ctx.author.id) >= mx:
            return await ctx.send(embed=err_embed(f"You've hit the limit of {mx} networks."))
        d = deepcopy(DEFAULT_NETWORK)
        d["owner_id"] = ctx.author.id
        d["description"] = description
        d["created_at"] = datetime.now(timezone.utc).isoformat()
        async with self.config.networks() as ns:
            ns[name] = d
        from ..utils import CooldownBucket
        self.cooldowns[name] = CooldownBucket(d["rate_limit_rate"], d["rate_limit_per"])
        await ctx.send(embed=ok_embed(
            f"Network `{name}` created!\n"
            f"Open channels with `wh open {name}` in target channels."
        ))
        await self._audit(name, "create", str(ctx.author))

    @WormholeBase.wh.command(name="delete")
    async def wh_delete(self, ctx: commands.Context, name: str) -> None:
        """Delete a network (owner or bot owner only)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if not await self.bot.is_owner(ctx.author):
            if not has_role(nd, ctx.author.id, Role.OWNER):
                return await ctx.send(embed=err_embed("Only the network owner or bot owner can delete a network."))
        async with self.config.networks() as ns:
            ns.pop(name, None)
        self.cooldowns.pop(name, None)
        await ctx.send(embed=ok_embed(f"Network `{name}` deleted."))

    @WormholeBase.wh.command(name="open")
    @requires_role(Role.ADMIN)
    async def wh_open(self, ctx: commands.Context, name: str) -> None:
        """Add the current channel to a network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if ctx.channel.id in nd.get("channels", []):
            return await ctx.send(embed=err_embed("This channel is already in the network."))
        existing = await self._net_for_ch(ctx.channel.id)
        if existing:
            return await ctx.send(embed=err_embed(f"This channel is already in network `{existing}`."))
        async with self.config.networks() as ns:
            ns[name].setdefault("channels", []).append(ctx.channel.id)
        await ctx.send(embed=ok_embed(f"Channel linked to `{name}`. Messages will now relay."))
        await self._audit(name, "open", str(ctx.author), str(ctx.channel.id))

    @WormholeBase.wh.command(name="close")
    async def wh_close(self, ctx: commands.Context, name: str = None) -> None:
        """Remove the current channel from a network."""
        if not name:
            name = await self._net_for_ch(ctx.channel.id)
        if not name:
            return await ctx.send(embed=err_embed("This channel isn't in any network."))
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if not has_role(nd, ctx.author.id, Role.ADMIN) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("You need Admin role or higher."))
        if ctx.channel.id not in nd.get("channels", []):
            return await ctx.send(embed=err_embed("This channel isn't in that network."))
        async with self.config.networks() as ns:
            ns[name]["channels"].remove(ctx.channel.id)
        await ctx.send(embed=ok_embed(f"Channel removed from `{name}`."))
        await self._audit(name, "close", str(ctx.author), str(ctx.channel.id))

    @WormholeBase.wh.command(name="list")
    async def wh_list(self, ctx: commands.Context) -> None:
        """List all networks you have access to."""
        nets = await self.config.networks()
        if not nets:
            return await ctx.send(embed=info_embed("No networks exist yet."))
        lines = []
        for n, d in sorted(nets.items()):
            status = "❄️" if d.get("frozen") else "🟢"
            ch_count = len(d.get("channels", []))
            role = get_role(d, ctx.author.id)
            role_tag = f" [{role_name(role)}]" if role > Role.MEMBER else ""
            lines.append(f"{status} **{n}** — {ch_count} channels, {d.get('total_messages', 0):,} msgs{role_tag}")
        em = discord.Embed(title="🌀 Wormhole Networks", description="\n".join(lines), colour=COLOUR_INFO)
        await ctx.send(embed=em)

    @WormholeBase.wh.command(name="discover")
    async def wh_discover(self, ctx: commands.Context) -> None:
        """Browse public networks."""
        nets = await self.config.networks()
        public = [(n, d) for n, d in nets.items() if d.get("public")]
        if not public:
            return await ctx.send(embed=info_embed("No public networks available."))
        lines = []
        for n, d in public:
            desc = truncate(d.get("description", ""), 60) or "No description"
            tags = ", ".join(d.get("tags", [])) or "—"
            lines.append(f"**{n}** — {desc}\n  Tags: {tags} · {len(d.get('channels', []))} ch")
        em = discord.Embed(title="🔍 Public Networks", description="\n".join(lines), colour=COLOUR_INFO)
        await ctx.send(embed=em)

    @WormholeBase.wh.command(name="info")
    async def wh_info(self, ctx: commands.Context, name: str) -> None:
        """Show detailed info about a network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))

        colour = discord.Colour(nd["colour"]) if nd.get("colour") else COLOUR_INFO
        status = "❄️ Frozen" if nd.get("frozen") else "🟢 Active"
        owner = self.bot.get_user(nd["owner_id"])

        em = discord.Embed(title=f"🌀 {name}", description=nd.get("description") or "No description", colour=colour)
        em.add_field(name="Status", value=status, inline=True)
        em.add_field(name="Owner", value=str(owner or nd["owner_id"]), inline=True)

        staff = list_staff(nd)
        staff_summary = []
        for role in (Role.ADMIN, Role.MODERATOR, Role.HELPER):
            count = sum(1 for r in staff.values() if r == role)
            if count:
                staff_summary.append(f"{role_name(role)}: {count}")
        em.add_field(name="Staff", value="\n".join(staff_summary) if staff_summary else "None", inline=True)

        em.add_field(name="Channels", value=str(len(nd.get("channels", []))), inline=True)
        em.add_field(name="Messages", value=f"{nd.get('total_messages', 0):,}", inline=True)
        em.add_field(name="Relay Mode", value=nd.get("relay_mode", "webhook"), inline=True)

        features = []
        for key, label in [
            ("sync_edits", "Edit sync"), ("sync_deletes", "Delete sync"),
            ("sync_reactions", "Reaction sync"), ("sync_replies", "Reply sync"),
            ("dm_enabled", "DM relay"), ("anonymous", "Anonymous"),
            ("rules_required", "ToS gate"), ("media_only", "Media-only"),
        ]:
            if nd.get(key):
                features.append(f"✅ {label}")
        if features:
            em.add_field(name="Features", value=" · ".join(features), inline=False)

        your_role = get_role(nd, ctx.author.id)
        em.set_footer(text=f"Your role: {role_name(your_role)} · Created {(nd.get('created_at') or '?')[:10]}")
        await ctx.send(embed=em)
