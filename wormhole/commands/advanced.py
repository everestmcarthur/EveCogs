"""Advanced commands — polls, AFK, auto-responses, scheduled messages,
analytics, ephemeral, quiet hours, user colours, invites, announcements."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role, has_role
from ..utils import (
    ok_embed, err_embed, info_embed, warn_embed, announce_embed,
    truncate, generate_invite_code, human_timedelta, COLOUR_INFO,
)


class AdvancedCommands:
    """Mixin — advanced features."""

    # ── Polls ──────────────────────────────────────────────────────────────

    @commands.group(name="wh-poll", aliases=["whpoll"], invoke_without_command=True)
    async def wh_poll(self, ctx: commands.Context) -> None:
        """Network-wide polls."""
        await ctx.send_help(ctx.command)

    @wh_poll.command(name="create")
    @requires_role(Role.MODERATOR)
    async def wh_poll_create(self, ctx: commands.Context, name: str, duration_minutes: int, question: str, *, options: str) -> None:
        """Create a poll. Options separated by ``|``.

        Example: ``wh poll create mynet 60 Favourite colour? Red | Blue | Green``
        """
        option_list = [o.strip() for o in options.split("|") if o.strip()]
        if len(option_list) < 2:
            return await ctx.send(embed=err_embed("Need at least 2 options separated by `|`."))
        if len(option_list) > 10:
            return await ctx.send(embed=err_embed("Maximum 10 options."))
        expires = (datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)).isoformat()
        poll_id = secrets.token_hex(4)
        poll = {
            "question": question,
            "options": option_list,
            "votes": {},
            "expires": expires,
            "creator": ctx.author.id,
        }
        async with self.config.networks() as ns:
            ns[name].setdefault("active_polls", {})[poll_id] = poll

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        desc = "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(option_list))
        desc += f"\n\nVote with `wh poll vote {name} {poll_id} <number>`\nExpires in {duration_minutes} minutes."
        em = discord.Embed(title=f"📊 {question}", description=desc, colour=COLOUR_INFO)

        nd = await self._net(name)
        for ch_id in nd.get("channels", []):
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=em)
                except Exception:
                    pass
        await ctx.send(embed=ok_embed(f"Poll `{poll_id}` created in `{name}`."))

    @wh_poll.command(name="vote")
    async def wh_poll_vote(self, ctx: commands.Context, name: str, poll_id: str, choice: int) -> None:
        """Vote in a poll (choice = option number, 1-based)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        poll = nd.get("active_polls", {}).get(poll_id)
        if not poll:
            return await ctx.send(embed=err_embed("Poll not found or expired."))
        if choice < 1 or choice > len(poll["options"]):
            return await ctx.send(embed=err_embed(f"Choose 1–{len(poll['options'])}."))
        idx = str(choice - 1)
        uid = ctx.author.id
        async with self.config.networks() as ns:
            p = ns[name]["active_polls"][poll_id]
            # Remove previous vote
            for k, voters in p.get("votes", {}).items():
                if uid in voters:
                    voters.remove(uid)
            p.setdefault("votes", {}).setdefault(idx, []).append(uid)
        await ctx.send(embed=ok_embed(f"Voted for **{poll['options'][choice-1]}**."), delete_after=5)

    @wh_poll.command(name="results")
    async def wh_poll_results(self, ctx: commands.Context, name: str, poll_id: str) -> None:
        """View current poll results."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        poll = nd.get("active_polls", {}).get(poll_id)
        if not poll:
            return await ctx.send(embed=err_embed("Poll not found."))
        results = self._format_poll_results(poll)
        await ctx.send(embed=info_embed(results, title=f"📊 {poll['question']}"))

    @wh_poll.command(name="end")
    @requires_role(Role.MODERATOR)
    async def wh_poll_end(self, ctx: commands.Context, name: str, poll_id: str) -> None:
        """End a poll early."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        poll = nd.get("active_polls", {}).get(poll_id)
        if not poll:
            return await ctx.send(embed=err_embed("Poll not found."))
        results = self._format_poll_results(poll)
        async with self.config.networks() as ns:
            ns[name].get("active_polls", {}).pop(poll_id, None)
        for ch_id in nd.get("channels", []):
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=info_embed(results, title=f"📊 Poll Ended: {poll['question']}"))
                except Exception:
                    pass
        await ctx.send(embed=ok_embed("Poll ended."))

    # ── AFK ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-afk")
    async def wh_afk(self, ctx: commands.Context, name: str, *, reason: str = "AFK") -> None:
        """Set your AFK status in a network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name].setdefault("afk_users", {})[str(ctx.author.id)] = {
                "reason": reason,
                "since_iso": datetime.now(timezone.utc).isoformat(),
            }
        await ctx.send(embed=ok_embed(f"AFK set: **{reason}**"))

    # ── Auto-responses ─────────────────────────────────────────────────────

    @commands.group(name="wh-ar", aliases=["whar"], invoke_without_command=True)
    async def wh_ar(self, ctx: commands.Context) -> None:
        """Auto-response triggers."""
        await ctx.send_help(ctx.command)

    @wh_ar.command(name="add")
    @requires_role(Role.ADMIN)
    async def wh_ar_add(self, ctx: commands.Context, name: str, trigger: str, *, reply: str) -> None:
        """Add an auto-response.  Use ``regex:pattern`` for regex triggers."""
        is_regex = trigger.startswith("regex:")
        if is_regex:
            trigger = trigger[6:]
            import re
            try:
                re.compile(trigger)
            except re.error as e:
                return await ctx.send(embed=err_embed(f"Invalid regex: {e}"))
        async with self.config.networks() as ns:
            ns[name].setdefault("auto_responses", {})[trigger] = {
                "reply": reply,
                "regex": is_regex,
                "cooldown": 30,
                "last_used": 0,
            }
        await ctx.send(embed=ok_embed(f"Auto-response added for `{trigger}`."))

    @wh_ar.command(name="remove", aliases=["rm"])
    @requires_role(Role.ADMIN)
    async def wh_ar_rm(self, ctx: commands.Context, name: str, *, trigger: str) -> None:
        """Remove an auto-response."""
        async with self.config.networks() as ns:
            ns[name].get("auto_responses", {}).pop(trigger, None)
        await ctx.send(embed=ok_embed(f"Auto-response removed for `{trigger}`."))

    @wh_ar.command(name="list")
    @requires_role(Role.HELPER)
    async def wh_ar_list(self, ctx: commands.Context, name: str) -> None:
        """List auto-responses."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        ars = nd.get("auto_responses", {})
        if not ars:
            return await ctx.send(embed=info_embed("No auto-responses configured."))
        lines = []
        for trigger, cfg in ars.items():
            kind = "regex" if cfg.get("regex") else "text"
            lines.append(f"• `{trigger}` ({kind}) → {truncate(cfg.get('reply', ''), 60)}")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"🤖 Auto-Responses — {name}"))

    # ── Scheduled messages ─────────────────────────────────────────────────

    @commands.group(name="wh-schedule", aliases=["whschedule"], invoke_without_command=True)
    async def wh_schedule(self, ctx: commands.Context) -> None:
        """Scheduled messages."""
        await ctx.send_help(ctx.command)

    @wh_schedule.command(name="add")
    @requires_role(Role.ADMIN)
    async def wh_schedule_add(self, ctx: commands.Context, name: str, minutes_from_now: int, *, content: str) -> None:
        """Schedule a message to be sent in N minutes."""
        send_at = (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).isoformat()
        async with self.config.networks() as ns:
            ns[name].setdefault("scheduled_messages", []).append({
                "content": content,
                "send_at_iso": send_at,
                "creator": ctx.author.id,
            })
        await ctx.send(embed=ok_embed(f"Message scheduled for {minutes_from_now} minutes from now."))

    @wh_schedule.command(name="list")
    @requires_role(Role.HELPER)
    async def wh_schedule_list(self, ctx: commands.Context, name: str) -> None:
        """List scheduled messages."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        msgs = nd.get("scheduled_messages", [])
        if not msgs:
            return await ctx.send(embed=info_embed("No scheduled messages."))
        lines = []
        for i, sm in enumerate(msgs, 1):
            lines.append(f"**{i}.** {sm.get('send_at_iso', '?')[:16]} — {truncate(sm.get('content', ''), 60)}")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"📅 Scheduled — {name}"))

    @wh_schedule.command(name="clear")
    @requires_role(Role.ADMIN)
    async def wh_schedule_clear(self, ctx: commands.Context, name: str) -> None:
        """Clear all scheduled messages."""
        async with self.config.networks() as ns:
            ns[name]["scheduled_messages"] = []
        await ctx.send(embed=ok_embed("All scheduled messages cleared."))

    # ── Analytics ──────────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-analytics")
    @requires_role(Role.HELPER)
    async def wh_analytics(self, ctx: commands.Context, name: str) -> None:
        """View network analytics dashboard."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        analytics = nd.get("analytics", {})
        hourly = analytics.get("hourly", {})
        top_users = analytics.get("top_users", {})

        em = discord.Embed(title=f"📈 Analytics — {name}", colour=COLOUR_INFO)
        em.add_field(name="Total Messages", value=f"{nd.get('total_messages', 0):,}", inline=True)
        em.add_field(name="Channels", value=str(len(nd.get("channels", []))), inline=True)

        # Last 24h
        now = datetime.now(timezone.utc)
        last_24h = sum(v for k, v in hourly.items() if k >= (now - timedelta(hours=24)).strftime("%Y-%m-%d-%H"))
        last_7d = sum(hourly.values())
        em.add_field(name="Last 24h", value=f"{last_24h:,}", inline=True)
        em.add_field(name="Last 7d", value=f"{last_7d:,}", inline=True)

        # Top users
        if top_users:
            sorted_users = sorted(top_users.items(), key=lambda x: x[1], reverse=True)[:5]
            top_lines = []
            for uid_str, count in sorted_users:
                user = self.bot.get_user(int(uid_str))
                top_lines.append(f"**{user or uid_str}** — {count:,}")
            em.add_field(name="Top Users (all time)", value="\n".join(top_lines), inline=False)

        await ctx.send(embed=em)

    # ── Quiet hours ────────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-quiet")
    async def wh_quiet(self, ctx: commands.Context, name: str, start_hour: int, end_hour: int, tz_offset: int = 0) -> None:
        """Set quiet hours — DM relay pauses during this window.

        Hours are 0-23.  ``tz_offset`` is hours from UTC.
        """
        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
            return await ctx.send(embed=err_embed("Hours must be 0–23."))
        async with self.config.networks() as ns:
            ns[name].setdefault("quiet_hours", {})[str(ctx.author.id)] = {
                "start_hour": start_hour,
                "end_hour": end_hour,
                "tz_offset": tz_offset,
            }
        await ctx.send(embed=ok_embed(f"Quiet hours set: {start_hour}:00–{end_hour}:00 (UTC{tz_offset:+d})"))

    @commands.hybrid_command(name="wh-unquiet")
    async def wh_unquiet(self, ctx: commands.Context, name: str) -> None:
        """Remove your quiet hours."""
        async with self.config.networks() as ns:
            ns[name].get("quiet_hours", {}).pop(str(ctx.author.id), None)
        await ctx.send(embed=ok_embed("Quiet hours removed."))

    # ── User colours ───────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-colour", aliases=["wh-color"])
    async def wh_colour(self, ctx: commands.Context, name: str, hex_code: str = None) -> None:
        """Set your name colour in embed mode (hex, e.g. ``#ff5733``)."""
        if hex_code:
            try:
                int(hex_code.lstrip("#"), 16)
            except ValueError:
                return await ctx.send(embed=err_embed("Invalid hex colour."))
        async with self.config.networks() as ns:
            if hex_code:
                ns[name].setdefault("user_colours", {})[str(ctx.author.id)] = hex_code.lstrip("#")
            else:
                ns[name].get("user_colours", {}).pop(str(ctx.author.id), None)
        await ctx.send(embed=ok_embed(f"Colour {'set' if hex_code else 'cleared'}."))

    # ── Invites ────────────────────────────────────────────────────────────

    @commands.group(name="wh-invite", aliases=["whinvite"], invoke_without_command=True)
    async def wh_invite(self, ctx: commands.Context) -> None:
        """Network invite codes."""
        await ctx.send_help(ctx.command)

    @wh_invite.command(name="create")
    @requires_role(Role.ADMIN)
    async def wh_invite_create(self, ctx: commands.Context, name: str, max_uses: int = 0) -> None:
        """Create an invite code (``max_uses`` 0 = unlimited)."""
        code = generate_invite_code()
        async with self.config.networks() as ns:
            ns[name].setdefault("invites", {})[code] = {
                "creator": ctx.author.id,
                "max_uses": max_uses,
                "uses": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        await ctx.send(embed=ok_embed(f"Invite code: `{code}`\nMax uses: {'unlimited' if max_uses == 0 else max_uses}"))

    @wh_invite.command(name="vanity")
    @requires_role(Role.OWNER)
    async def wh_invite_vanity(self, ctx: commands.Context, name: str, code: str) -> None:
        """Set a vanity invite code."""
        if len(code) < 3 or len(code) > 20:
            return await ctx.send(embed=err_embed("Code must be 3–20 characters."))
        async with self.config.networks() as ns:
            ns[name]["vanity_invite"] = code
        await ctx.send(embed=ok_embed(f"Vanity invite set: `{code}`"))

    @wh_invite.command(name="list")
    @requires_role(Role.ADMIN)
    async def wh_invite_list(self, ctx: commands.Context, name: str) -> None:
        """List all invite codes."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        invites = nd.get("invites", {})
        if not invites:
            return await ctx.send(embed=info_embed("No invites."))
        lines = []
        for code, data in invites.items():
            uses = data.get("uses", 0)
            mx = data.get("max_uses", 0)
            lines.append(f"`{code}` — {uses}/{mx if mx else '∞'} uses")
        vanity = nd.get("vanity_invite")
        if vanity:
            lines.append(f"\n✨ Vanity: `{vanity}`")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"🔗 Invites — {name}"))

    @wh_invite.command(name="revoke")
    @requires_role(Role.ADMIN)
    async def wh_invite_revoke(self, ctx: commands.Context, name: str, code: str) -> None:
        """Revoke an invite code."""
        async with self.config.networks() as ns:
            ns[name].get("invites", {}).pop(code, None)
        await ctx.send(embed=ok_embed(f"Invite `{code}` revoked."))

    # ── Announcements ──────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-announce")
    @requires_role(Role.ADMIN)
    async def wh_announce(self, ctx: commands.Context, name: str, *, message: str) -> None:
        """Broadcast an announcement to all channels in the network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        em = announce_embed(message, title=f"📢 {name} — Announcement")
        sent = 0
        for ch_id in nd.get("channels", []):
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=em)
                    sent += 1
                except Exception:
                    pass
        await ctx.send(embed=ok_embed(f"Announcement sent to {sent} channels."))
        await self._audit(name, "announce", str(ctx.author), details=truncate(message, 100))

    # ── Blackout schedules ─────────────────────────────────────────────────

    @commands.group(name="wh-blackout", aliases=["whblackout"], invoke_without_command=True)
    async def wh_blackout(self, ctx: commands.Context) -> None:
        """Scheduled freeze windows."""
        await ctx.send_help(ctx.command)

    @wh_blackout.command(name="add")
    @requires_role(Role.ADMIN)
    async def wh_blackout_add(self, ctx: commands.Context, name: str, start_hour: int, end_hour: int, *, days: str = "0,1,2,3,4,5,6") -> None:
        """Add a blackout schedule. Days: 0=Mon … 6=Sun."""
        day_list = [int(d.strip()) for d in days.split(",") if d.strip().isdigit()]
        async with self.config.networks() as ns:
            ns[name].setdefault("blackout_schedules", []).append({
                "start_hour": start_hour,
                "end_hour": end_hour,
                "days": day_list,
            })
        await ctx.send(embed=ok_embed(f"Blackout added: {start_hour}:00–{end_hour}:00 UTC on days {day_list}"))

    @wh_blackout.command(name="clear")
    @requires_role(Role.ADMIN)
    async def wh_blackout_clear(self, ctx: commands.Context, name: str) -> None:
        """Clear all blackout schedules."""
        async with self.config.networks() as ns:
            ns[name]["blackout_schedules"] = []
        await ctx.send(embed=ok_embed("All blackout schedules cleared."))

    # ── Portal embed ───────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-portal")
    @requires_role(Role.ADMIN)
    async def wh_portal(self, ctx: commands.Context, name: str) -> None:
        """Post a self-updating portal embed in this channel."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        from ..utils import build_portal_embed
        em = build_portal_embed(name, nd, len(nd.get("channels", [])), nd.get("total_messages", 0))
        msg = await ctx.send(embed=em)
        async with self.config.networks() as ns:
            ns[name].setdefault("portal_messages", {})[str(ctx.channel.id)] = msg.id
        await ctx.send(embed=ok_embed("Portal embed posted. It will auto-update every 5 minutes."), delete_after=10)
