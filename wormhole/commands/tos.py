"""ToS / Rules acceptance gate commands."""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role
from ..utils import ok_embed, err_embed, info_embed, COLOUR_INFO


class ToSCommands:
    """Mixin — Terms of Service / rules acceptance gate."""

    @commands.group(name="wh-rules", aliases=["whrules"], invoke_without_command=True)
    async def wh_rules(self, ctx: commands.Context) -> None:
        """Network rules / Terms of Service."""
        await ctx.send_help(ctx.command)

    @wh_rules.command(name="set")
    @requires_role(Role.ADMIN)
    async def wh_rules_set(self, ctx: commands.Context, name: str, *, text: str) -> None:
        """Set the rules / ToS text."""
        async with self.config.networks() as ns:
            ns[name]["rules_text"] = text
        await ctx.send(embed=ok_embed(f"Rules updated for `{name}`."))

    @wh_rules.command(name="require")
    @requires_role(Role.ADMIN)
    async def wh_rules_require(self, ctx: commands.Context, name: str, enabled: bool = True) -> None:
        """Toggle mandatory rules acceptance before using the network."""
        async with self.config.networks() as ns:
            ns[name]["rules_required"] = enabled
        await ctx.send(embed=ok_embed(
            f"Rules acceptance {'required' if enabled else 'not required'} for `{name}`."
        ))

    @wh_rules.command(name="view")
    async def wh_rules_view(self, ctx: commands.Context, name: str) -> None:
        """View the network rules."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        text = nd.get("rules_text") or nd.get("rules") or "No rules set."
        em = discord.Embed(
            title=f"📜 Rules — {name}",
            description=text[:4000],
            colour=COLOUR_INFO,
        )
        accepted = nd.get("rules_accepted", {}).get(str(ctx.author.id))
        if accepted:
            em.set_footer(text=f"You accepted on {accepted[:10]}")
        else:
            em.set_footer(text="⚠️ You haven't accepted these rules yet. Use `wh accept` or `wh agree`.")
        await ctx.send(embed=em)

    @commands.hybrid_command(name="wh-accept")
    async def wh_accept(self, ctx: commands.Context, name: str) -> None:
        """Accept the network rules / ToS."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if not nd.get("rules_required"):
            return await ctx.send(embed=info_embed("This network doesn't require rules acceptance."))
        async with self.config.networks() as ns:
            ns[name].setdefault("rules_accepted", {})[str(ctx.author.id)] = datetime.now(timezone.utc).isoformat()
        await ctx.send(embed=ok_embed(f"You've accepted the rules for `{name}`. You can now use the relay."))

    @commands.hybrid_command(name="wh-agree")
    async def wh_agree(self, ctx: commands.Context, name: str) -> None:
        """Alias for ``wh accept``."""
        await self.wh_accept(ctx, name)

    @wh_rules.command(name="reset")
    @requires_role(Role.ADMIN)
    async def wh_rules_reset(self, ctx: commands.Context, name: str) -> None:
        """Reset all acceptances (force everyone to re-accept)."""
        async with self.config.networks() as ns:
            ns[name]["rules_accepted"] = {}
        await ctx.send(embed=ok_embed(f"All acceptances reset for `{name}`. Users must re-accept."))
        await self._audit(name, "rules_reset", str(ctx.author))
