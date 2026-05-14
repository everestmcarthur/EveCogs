"""Social commands — karma, starboard, highlights, bookmarks, profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from redbot.core import commands

from ..models.permissions import Role, has_role, requires_role, get_role, role_name
from ..utils import ok_embed, err_embed, info_embed, star_embed, warn_embed, truncate, COLOUR_INFO, COLOUR_STAR


class SocialCommands:
    """Mixin — social features."""

    # ── Profiles ───────────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-profile")
    async def wh_profile(self, ctx: commands.Context, name: str, user: discord.User = None) -> None:
        """View a user's wormhole profile in a network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        target = user or ctx.author
        p = nd.get("user_profiles", {}).get(str(target.id))
        if not p:
            return await ctx.send(embed=info_embed(f"{target.display_name} hasn't been seen in `{name}`."))

        role = get_role(nd, target.id)
        karma = nd.get("karma_scores", {}).get(str(target.id), 0)

        em = discord.Embed(
            title=f"👤 {target.display_name}",
            colour=COLOUR_INFO,
        )
        em.set_thumbnail(url=target.display_avatar.url)
        em.add_field(name="Role", value=role_name(role), inline=True)
        em.add_field(name="Messages", value=f"{p.get('message_count', 0):,}", inline=True)
        em.add_field(name="Karma", value=str(karma), inline=True)
        em.add_field(name="First Seen", value=p.get("first_seen", "Unknown")[:10], inline=True)
        em.add_field(name="Servers", value=str(len(p.get("servers", []))), inline=True)
        em.set_footer(text=f"Network: {name}")
        await ctx.send(embed=em)

    # ── Karma ──────────────────────────────────────────────────────────────

    @commands.group(name="wh-karma", aliases=["whkarma"], invoke_without_command=True)
    async def wh_karma(self, ctx: commands.Context) -> None:
        """Karma system commands."""
        await ctx.send_help(ctx.command)

    @wh_karma.command(name="enable")
    @requires_role(Role.ADMIN)
    async def wh_karma_enable(self, ctx: commands.Context, name: str, enabled: bool = True) -> None:
        """Enable or disable the karma system."""
        async with self.config.networks() as ns:
            ns[name]["karma_enabled"] = enabled
        await ctx.send(embed=ok_embed(f"Karma {'enabled' if enabled else 'disabled'} for `{name}`."))

    @wh_karma.command(name="emoji")
    @requires_role(Role.ADMIN)
    async def wh_karma_emoji(self, ctx: commands.Context, name: str, emoji: str = "👍") -> None:
        """Set the karma reaction emoji."""
        async with self.config.networks() as ns:
            ns[name]["karma_emoji"] = emoji
        await ctx.send(embed=ok_embed(f"Karma emoji set to {emoji} for `{name}`."))

    @wh_karma.command(name="top")
    async def wh_karma_top(self, ctx: commands.Context, name: str, count: int = 10) -> None:
        """Show karma leaderboard."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        scores = nd.get("karma_scores", {})
        if not scores:
            return await ctx.send(embed=info_embed("No karma data yet."))
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:count]
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid_str, score) in enumerate(sorted_scores):
            user = self.bot.get_user(int(uid_str))
            medal = medals[i] if i < 3 else f"**{i+1}.**"
            lines.append(f"{medal} {user or uid_str} — **{score}** karma")
        em = discord.Embed(title=f"🏆 Karma Leaderboard — {name}", description="\n".join(lines), colour=COLOUR_INFO)
        await ctx.send(embed=em)

    # ── Starboard ──────────────────────────────────────────────────────────

    @commands.group(name="wh-star", aliases=["whstar"], invoke_without_command=True)
    async def wh_star(self, ctx: commands.Context) -> None:
        """Starboard commands."""
        await ctx.send_help(ctx.command)

    @wh_star.command(name="enable")
    @requires_role(Role.ADMIN)
    async def wh_star_enable(self, ctx: commands.Context, name: str, enabled: bool = True) -> None:
        """Enable or disable starboard."""
        async with self.config.networks() as ns:
            ns[name]["starboard_enabled"] = enabled
        await ctx.send(embed=ok_embed(f"Starboard {'enabled' if enabled else 'disabled'} for `{name}`."))

    @wh_star.command(name="channel")
    @requires_role(Role.ADMIN)
    async def wh_star_channel(self, ctx: commands.Context, name: str, channel: discord.TextChannel = None) -> None:
        """Set the starboard channel."""
        async with self.config.networks() as ns:
            ns[name]["starboard_channel"] = channel.id if channel else None
        await ctx.send(embed=ok_embed(f"Starboard channel {'set' if channel else 'cleared'} for `{name}`."))

    @wh_star.command(name="threshold")
    @requires_role(Role.ADMIN)
    async def wh_star_threshold(self, ctx: commands.Context, name: str, threshold: int = 3) -> None:
        """Set minimum stars to reach the starboard."""
        async with self.config.networks() as ns:
            ns[name]["starboard_threshold"] = max(1, threshold)
        await ctx.send(embed=ok_embed(f"Starboard threshold set to {threshold} for `{name}`."))

    # ── Highlights ─────────────────────────────────────────────────────────

    @commands.group(name="wh-hl", aliases=["whhl"], invoke_without_command=True)
    async def wh_hl(self, ctx: commands.Context) -> None:
        """Keyword highlight notifications."""
        await ctx.send_help(ctx.command)

    @wh_hl.command(name="add")
    async def wh_hl_add(self, ctx: commands.Context, name: str, *, keyword: str) -> None:
        """Add a keyword to highlight."""
        async with self.config.networks() as ns:
            hl = ns[name].setdefault("highlights", {})
            uid_str = str(ctx.author.id)
            user_hl = hl.setdefault(uid_str, [])
            if keyword.lower() in [k.lower() for k in user_hl]:
                return await ctx.send(embed=err_embed("Keyword already highlighted."))
            if len(user_hl) >= 25:
                return await ctx.send(embed=err_embed("Max 25 highlights per user."))
            user_hl.append(keyword)
        await ctx.send(embed=ok_embed(f"Highlight `{keyword}` added for `{name}`."))

    @wh_hl.command(name="remove", aliases=["rm"])
    async def wh_hl_remove(self, ctx: commands.Context, name: str, *, keyword: str) -> None:
        """Remove a highlight keyword."""
        async with self.config.networks() as ns:
            hl = ns[name].get("highlights", {})
            user_hl = hl.get(str(ctx.author.id), [])
            ns[name]["highlights"][str(ctx.author.id)] = [k for k in user_hl if k.lower() != keyword.lower()]
        await ctx.send(embed=ok_embed(f"Highlight `{keyword}` removed."))

    @wh_hl.command(name="list")
    async def wh_hl_list(self, ctx: commands.Context, name: str) -> None:
        """List your highlights."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        user_hl = nd.get("highlights", {}).get(str(ctx.author.id), [])
        if not user_hl:
            return await ctx.send(embed=info_embed("No highlights set."))
        await ctx.send(embed=info_embed("\n".join(f"• `{k}`" for k in user_hl), title="🔔 Your Highlights"))

    # ── Bookmarks ──────────────────────────────────────────────────────────

    @commands.group(name="wh-bm", aliases=["whbm"], invoke_without_command=True)
    async def wh_bm(self, ctx: commands.Context) -> None:
        """Message bookmarks."""
        await ctx.send_help(ctx.command)

    @wh_bm.command(name="list")
    async def wh_bm_list(self, ctx: commands.Context) -> None:
        """List your bookmarks."""
        bm = await self.config.bookmarks()
        user_bm = bm.get(str(ctx.author.id), [])
        if not user_bm:
            return await ctx.send(embed=info_embed("No bookmarks yet. Use the context menu to bookmark!"))
        lines = []
        for b in reversed(user_bm[-15:]):
            lines.append(
                f"• [{b.get('timestamp', '?')[:10]}] **{b.get('author', '?')}** in {b.get('server', '?')}\n"
                f"  {truncate(b.get('content', ''), 80)} — [Jump]({b.get('jump_url', '#')})"
            )
        em = discord.Embed(title="📌 Bookmarks", description="\n".join(lines), colour=COLOUR_INFO)
        await ctx.send(embed=em)

    @wh_bm.command(name="clear")
    async def wh_bm_clear(self, ctx: commands.Context) -> None:
        """Clear all your bookmarks."""
        async with self.config.bookmarks() as bm:
            bm.pop(str(ctx.author.id), None)
        await ctx.send(embed=ok_embed("All bookmarks cleared."))
