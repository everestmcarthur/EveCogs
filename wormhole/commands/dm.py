"""DM relay commands — subscribe, send, configure DM relay."""

from __future__ import annotations

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role
from ..utils import ok_embed, err_embed, info_embed, dm_embed, truncate
from ._base import WormholeBase


class DMCommands(WormholeBase):
    """Mixin — DM relay management."""

    @WormholeBase.wh_dm.command(name="enable")
    @requires_role(Role.ADMIN)
    async def wh_dm_enable(self, ctx: commands.Context, name: str, enabled: bool = True) -> None:
        """Enable or disable DM relay for a network."""
        async with self.config.networks() as ns:
            ns[name]["dm_enabled"] = enabled
        await ctx.send(embed=ok_embed(f"DM relay {'enabled' if enabled else 'disabled'} for `{name}`."))

    @WormholeBase.wh_dm.command(name="subscribe", aliases=["sub"])
    async def wh_dm_sub(self, ctx: commands.Context, name: str) -> None:
        """Subscribe to receive network messages via DM."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if not nd.get("dm_enabled"):
            return await ctx.send(embed=err_embed(f"DM relay isn't enabled for `{name}`."))
        async with self.config.networks() as ns:
            subs = ns[name].setdefault("dm_subscribers", [])
            if ctx.author.id in subs:
                return await ctx.send(embed=err_embed("You're already subscribed."))
            subs.append(ctx.author.id)
        await ctx.send(embed=ok_embed(f"Subscribed to DM relay for `{name}`."))

    @WormholeBase.wh_dm.command(name="unsubscribe", aliases=["unsub"])
    async def wh_dm_unsub(self, ctx: commands.Context, name: str) -> None:
        """Unsubscribe from DM relay."""
        async with self.config.networks() as ns:
            subs = ns[name].get("dm_subscribers", [])
            if ctx.author.id in subs:
                subs.remove(ctx.author.id)
        await ctx.send(embed=ok_embed(f"Unsubscribed from DM relay for `{name}`."))

    @WormholeBase.wh_dm.command(name="mode")
    @requires_role(Role.ADMIN)
    async def wh_dm_mode(self, ctx: commands.Context, name: str, mode: str) -> None:
        """Set DM relay mode: ``embed``, ``compact``, or ``plain``."""
        if mode not in ("embed", "compact", "plain"):
            return await ctx.send(embed=err_embed("Mode must be `embed`, `compact`, or `plain`."))
        async with self.config.networks() as ns:
            ns[name]["dm_relay_mode"] = mode
        await ctx.send(embed=ok_embed(f"DM relay mode set to **{mode}** for `{name}`."))

    @WormholeBase.wh_dm.command(name="send")
    async def wh_dm_send(self, ctx: commands.Context, name: str, *, message: str) -> None:
        """Send a message to the network from your DMs."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if not nd.get("dm_enabled"):
            return await ctx.send(embed=err_embed("DM relay isn't enabled for this network."))
        if ctx.author.id in nd.get("banned_users", []):
            return await ctx.send(embed=err_embed("You're banned from this network."))
        if ctx.author.id in nd.get("muted_users", []):
            return await ctx.send(embed=err_embed("You're muted in this network."))

        from ..utils import build_dm_relay_embed
        em = build_dm_relay_embed(ctx.author, message, name)
        for ch_id in nd.get("channels", []):
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=em)
                except Exception:
                    pass
        await ctx.send(embed=ok_embed("Message sent to the network."))

    @WormholeBase.wh_dm.command(name="ignore")
    async def wh_dm_ignore(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Ignore a user in DM relay (you won't see their messages)."""
        async with self.config.networks() as ns:
            ignores = ns[name].setdefault("user_ignores", {})
            uid_str = str(ctx.author.id)
            user_ignores = ignores.setdefault(uid_str, [])
            if user.id not in user_ignores:
                user_ignores.append(user.id)
        await ctx.send(embed=ok_embed(f"{user.display_name} ignored in DM relay for `{name}`."))

    @WormholeBase.wh_dm.command(name="unignore")
    async def wh_dm_unignore(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Stop ignoring a user in DM relay."""
        async with self.config.networks() as ns:
            ignores = ns[name].get("user_ignores", {})
            uid_str = str(ctx.author.id)
            user_ignores = ignores.get(uid_str, [])
            if user.id in user_ignores:
                user_ignores.remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.display_name} unignored in DM relay for `{name}`."))
