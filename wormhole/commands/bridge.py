"""Bridge commands — cross-network bridging and mirror channels."""

from __future__ import annotations

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role
from ..utils import ok_embed, err_embed, info_embed, COLOUR_INFO


class BridgeCommands:
    """Mixin — network bridging and mirror channels."""

    @commands.group(name="wh-bridge", aliases=["whbridge"], invoke_without_command=True)
    async def wh_bridge(self, ctx: commands.Context) -> None:
        """Cross-network bridging."""
        await ctx.send_help(ctx.command)

    @wh_bridge.command(name="link")
    @requires_role(Role.OWNER)
    async def wh_bridge_link(self, ctx: commands.Context, source: str, target: str) -> None:
        """Bridge messages from one network to another (one-way)."""
        nd_src = await self._net(source)
        nd_tgt = await self._net(target)
        if not nd_src:
            return await ctx.send(embed=err_embed(f"Network `{source}` not found."))
        if not nd_tgt:
            return await ctx.send(embed=err_embed(f"Network `{target}` not found."))
        async with self.config.networks() as ns:
            bridge_to = ns[source].setdefault("bridge_to", [])
            if target not in bridge_to:
                bridge_to.append(target)
            bridge_from = ns[target].setdefault("bridge_from", [])
            if source not in bridge_from:
                bridge_from.append(source)
        await ctx.send(embed=ok_embed(f"Bridge: `{source}` → `{target}` (one-way)."))
        await self._audit(source, "bridge_link", str(ctx.author), target)

    @wh_bridge.command(name="unlink")
    @requires_role(Role.OWNER)
    async def wh_bridge_unlink(self, ctx: commands.Context, source: str, target: str) -> None:
        """Remove a bridge."""
        async with self.config.networks() as ns:
            if source in ns:
                bt = ns[source].get("bridge_to", [])
                if target in bt:
                    bt.remove(target)
            if target in ns:
                bf = ns[target].get("bridge_from", [])
                if source in bf:
                    bf.remove(source)
        await ctx.send(embed=ok_embed(f"Bridge `{source}` → `{target}` removed."))
        await self._audit(source, "bridge_unlink", str(ctx.author), target)

    @wh_bridge.command(name="list")
    async def wh_bridge_list(self, ctx: commands.Context, name: str) -> None:
        """List bridges for a network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        lines = []
        for t in nd.get("bridge_to", []):
            lines.append(f"➡️ `{name}` → `{t}`")
        for f in nd.get("bridge_from", []):
            lines.append(f"⬅️ `{f}` → `{name}`")
        if not lines:
            lines.append("No bridges configured.")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"🌉 Bridges — {name}"))

    # ── Mirror channels ────────────────────────────────────────────────────

    @commands.group(name="wh-mirror", aliases=["whmirror"], invoke_without_command=True)
    async def wh_mirror(self, ctx: commands.Context) -> None:
        """Mirror channels — exact copy of relay to an extra channel."""
        await ctx.send_help(ctx.command)

    @wh_mirror.command(name="add")
    @requires_role(Role.ADMIN)
    async def wh_mirror_add(self, ctx: commands.Context, name: str, channel: discord.TextChannel) -> None:
        """Add a mirror channel."""
        async with self.config.networks() as ns:
            mirrors = ns[name].setdefault("mirror_channels", [])
            if channel.id not in mirrors:
                mirrors.append(channel.id)
        await ctx.send(embed=ok_embed(f"{channel.mention} added as mirror for `{name}`."))

    @wh_mirror.command(name="remove", aliases=["rm"])
    @requires_role(Role.ADMIN)
    async def wh_mirror_rm(self, ctx: commands.Context, name: str, channel: discord.TextChannel) -> None:
        """Remove a mirror channel."""
        async with self.config.networks() as ns:
            mirrors = ns[name].get("mirror_channels", [])
            if channel.id in mirrors:
                mirrors.remove(channel.id)
        await ctx.send(embed=ok_embed(f"{channel.mention} removed from mirrors for `{name}`."))

    @wh_mirror.command(name="list")
    async def wh_mirror_list(self, ctx: commands.Context, name: str) -> None:
        """List mirror channels."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        mirrors = nd.get("mirror_channels", [])
        if not mirrors:
            return await ctx.send(embed=info_embed("No mirror channels."))
        lines = []
        for ch_id in mirrors:
            ch = self.bot.get_channel(ch_id)
            lines.append(f"• {ch.mention if ch else ch_id}")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"🪞 Mirrors — {name}"))
