"""
Root ``wh`` command group and subgroup stubs.

Every command mixin inherits from :class:`WormholeBase` so that
all subcommands end up registered under the same ``wh`` parent.
"""

from __future__ import annotations

from redbot.core import commands


class WormholeBase:
    """Defines the ``wh`` group and every subgroup stub.

    Subgroups are defined here (with ``invoke_without_command=True``) so
    each mixin can reference them as ``@WormholeBase.wh_xxx.command(…)``.
    """

    # ── Root ───────────────────────────────────────────────────────────────

    @commands.group(name="wh", aliases=["wormhole"], invoke_without_command=True)
    async def wh(self, ctx: commands.Context) -> None:
        """Wormhole — the ultimate cross-server relay."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    # ── Subgroups (alphabetical) ───────────────────────────────────────────

    @wh.group(name="ar", aliases=["autoreply"], invoke_without_command=True)
    async def wh_ar(self, ctx: commands.Context) -> None:
        """Auto-response triggers."""
        await ctx.send_help(ctx.command)

    @wh.group(name="blackout", invoke_without_command=True)
    async def wh_blackout(self, ctx: commands.Context) -> None:
        """Scheduled freeze windows."""
        await ctx.send_help(ctx.command)

    @wh.group(name="bm", aliases=["bookmark"], invoke_without_command=True)
    async def wh_bm(self, ctx: commands.Context) -> None:
        """Message bookmarks."""
        await ctx.send_help(ctx.command)

    @wh.group(name="bridge", invoke_without_command=True)
    async def wh_bridge(self, ctx: commands.Context) -> None:
        """Cross-network bridging."""
        await ctx.send_help(ctx.command)

    @wh.group(name="debug", invoke_without_command=True)
    async def wh_debug(self, ctx: commands.Context) -> None:
        """Debug and diagnostic tools."""
        await ctx.send_help(ctx.command)

    @wh.group(name="dm", invoke_without_command=True)
    async def wh_dm(self, ctx: commands.Context) -> None:
        """DM relay — receive network messages in your DMs."""
        await ctx.send_help(ctx.command)

    @wh.group(name="filter", invoke_without_command=True)
    async def wh_filter(self, ctx: commands.Context) -> None:
        """Manage content filters and automod."""
        await ctx.send_help(ctx.command)

    @wh.group(name="hl", aliases=["highlight"], invoke_without_command=True)
    async def wh_hl(self, ctx: commands.Context) -> None:
        """Keyword highlight notifications."""
        await ctx.send_help(ctx.command)

    @wh.group(name="invite", invoke_without_command=True)
    async def wh_invite(self, ctx: commands.Context) -> None:
        """Network invite codes."""
        await ctx.send_help(ctx.command)

    @wh.group(name="karma", invoke_without_command=True)
    async def wh_karma(self, ctx: commands.Context) -> None:
        """Karma system commands."""
        await ctx.send_help(ctx.command)

    @wh.group(name="mention", aliases=["mentions"], invoke_without_command=True)
    async def wh_mention(self, ctx: commands.Context) -> None:
        """Configure mention behaviour."""
        await ctx.send_help(ctx.command)

    @wh.group(name="mirror", invoke_without_command=True)
    async def wh_mirror(self, ctx: commands.Context) -> None:
        """Mirror channels — exact copy of relay to an extra channel."""
        await ctx.send_help(ctx.command)

    @wh.group(name="mod", invoke_without_command=True)
    async def wh_mod(self, ctx: commands.Context) -> None:
        """Network moderation tools."""
        await ctx.send_help(ctx.command)

    @wh.group(name="poll", invoke_without_command=True)
    async def wh_poll(self, ctx: commands.Context) -> None:
        """Network-wide polls."""
        await ctx.send_help(ctx.command)

    @wh.group(name="report", invoke_without_command=True)
    async def wh_report(self, ctx: commands.Context) -> None:
        """Network report system."""
        await ctx.send_help(ctx.command)

    @wh.group(name="rules", aliases=["tos", "terms"], invoke_without_command=True)
    async def wh_rules(self, ctx: commands.Context) -> None:
        """Network rules / Terms of Service."""
        await ctx.send_help(ctx.command)

    @wh.group(name="schedule", invoke_without_command=True)
    async def wh_schedule(self, ctx: commands.Context) -> None:
        """Scheduled messages."""
        await ctx.send_help(ctx.command)

    @wh.group(name="set", invoke_without_command=True)
    async def wh_set(self, ctx: commands.Context) -> None:
        """Configure network settings."""
        await ctx.send_help(ctx.command)

    @wh.group(name="staff", invoke_without_command=True)
    async def wh_staff(self, ctx: commands.Context) -> None:
        """Manage network staff — add, remove, list, promote, demote."""
        await ctx.send_help(ctx.command)

    @wh.group(name="star", aliases=["starboard"], invoke_without_command=True)
    async def wh_star(self, ctx: commands.Context) -> None:
        """Starboard commands."""
        await ctx.send_help(ctx.command)
