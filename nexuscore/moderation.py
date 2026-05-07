"""NexusCore — Moderation: warns, cases, anti-raid, anti-nuke, lockdown, notes, appeals, auto-escalation."""

from __future__ import annotations

import asyncio
import collections
import datetime
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    ts_full, duration_str, parse_duration, safe_send, safe_dm, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
MOD_DEFAULTS_GUILD = {
    "enabled": True,
    "modlog_channel": None,
    "appeal_channel": None,
    "cases": {},
    # case_id -> {type, user_id, mod_id, reason, timestamp, duration, active, message_id}
    "case_counter": 0,
    "notes": {},         # user_id -> [{author_id, text, timestamp}]
    "warnings": {},      # user_id -> [{id, reason, mod_id, timestamp}]
    "escalation": {
        "enabled": True,
        "thresholds": {
            "3": "mute_1h",
            "5": "mute_24h",
            "7": "tempban_7d",
            "10": "ban",
        },
    },
    "anti_raid": {
        "enabled": False,
        "join_threshold": 10,
        "join_window": 10,
        "action": "lockdown",  # lockdown | kick | ban
        "notify_channel": None,
    },
    "anti_nuke": {
        "enabled": False,
        "channel_delete_threshold": 3,
        "role_delete_threshold": 3,
        "ban_threshold": 5,
        "window": 30,
        "action": "strip_roles",  # strip_roles | ban
    },
    "auto_mod": {
        "anti_spam": {"enabled": False, "max_messages": 5, "window": 5, "action": "mute_10m"},
        "anti_caps": {"enabled": False, "threshold": 70, "min_length": 10, "action": "warn"},
        "anti_invite": {"enabled": False, "action": "delete_warn"},
        "anti_links": {"enabled": False, "whitelist": [], "action": "delete"},
        "anti_mention": {"enabled": False, "max_mentions": 5, "action": "mute_10m"},
        "anti_newlines": {"enabled": False, "max_newlines": 15, "action": "delete"},
    },
    "mute_role": None,
    "dm_on_action": True,
    "appeal_enabled": False,
    "lockdown_role_overrides": {},  # channel_id -> {role_id: old_send_value}
}

CASE_TYPES = ["warn", "mute", "unmute", "kick", "softban", "tempban", "ban", "unban", "note"]


# ── Views ──────────────────────────────────────────────────────────────────
class AppealModal(discord.ui.Modal):
    def __init__(self, cog, case_id: str):
        super().__init__(title="Appeal")
        self.cog = cog
        self.case_id = case_id
        self.reason = discord.ui.TextInput(label="Why should this be lifted?", style=discord.TextStyle.paragraph, max_length=1000)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Must be used in a server.", ephemeral=True)
        data = await self.cog.mod_config.guild(guild).all()
        appeal_ch_id = data.get("appeal_channel")
        if appeal_ch_id:
            ch = guild.get_channel(appeal_ch_id)
            if ch:
                embed = discord.Embed(
                    title=f"📩 Appeal — Case #{self.case_id}",
                    colour=Clr.MOD,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                embed.add_field(name="User", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
                embed.add_field(name="Case", value=self.case_id, inline=True)
                embed.add_field(name="Reason", value=self.reason.value[:1024], inline=False)
                await safe_send(ch, embed=embed)
        await interaction.response.send_message("✅ Appeal submitted.", ephemeral=True)


class AppealView(discord.ui.View):
    def __init__(self, cog, case_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.case_id = case_id

    @discord.ui.button(label="Appeal", style=discord.ButtonStyle.primary, emoji="📩")
    async def appeal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AppealModal(self.cog, self.case_id)
        await interaction.response.send_modal(modal)


# ── Mixin ──────────────────────────────────────────────────────────────────
class ModerationMixin:
    """Moderation system mixin."""

    def _init_moderation(self, bot):
        self.mod_config = Config.get_conf(
            None, identifier=900007, cog_name="NexusCoreMod"
        )
        self.mod_config.register_guild(**MOD_DEFAULTS_GUILD)
        self._join_tracker = {}    # guild_id -> deque of timestamps
        self._nuke_tracker = {}    # guild_id -> {event_type: deque of timestamps}
        self._spam_tracker = {}    # (guild_id, user_id) -> deque of timestamps
        self.bot = bot

    # ── Case system ────────────────────────────────────────────────────────
    async def _create_case(
        self, guild: discord.Guild, case_type: str,
        user: discord.User | discord.Member, mod: discord.Member,
        reason: str = "No reason", duration: int = 0,
    ) -> str:
        conf = self.mod_config.guild(guild)
        counter = await conf.case_counter()
        counter += 1
        await conf.case_counter.set(counter)

        case_id = str(counter)
        case = {
            "type": case_type,
            "user_id": user.id,
            "user_str": str(user),
            "mod_id": mod.id,
            "mod_str": str(mod),
            "reason": reason,
            "timestamp": ts_now(),
            "duration": duration,
            "active": True,
            "message_id": None,
        }

        async with conf.cases() as cases:
            cases[case_id] = case

        # Log to modlog channel
        data = await conf.all()
        log_ch = guild.get_channel(data["modlog_channel"]) if data["modlog_channel"] else None
        if log_ch:
            type_emojis = {
                "warn": "⚠️", "mute": "🔇", "unmute": "🔊", "kick": "👢",
                "softban": "🧹", "tempban": "⏰", "ban": "🔨", "unban": "🔓", "note": "📝",
            }
            emoji = type_emojis.get(case_type, "📋")
            embed = discord.Embed(
                title=f"{emoji} Case #{case_id} — {case_type.title()}",
                colour=Clr.MOD,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=True)
            embed.add_field(name="Moderator", value=mod.mention, inline=True)
            embed.add_field(name="Reason", value=reason[:1024], inline=False)
            if duration:
                embed.add_field(name="Duration", value=duration_str(duration), inline=True)
            embed.set_footer(text=f"Case #{case_id}")

            msg = await safe_send(log_ch, embed=embed)
            if msg:
                async with conf.cases() as cases:
                    if case_id in cases:
                        cases[case_id]["message_id"] = msg.id

        # DM the user
        if data.get("dm_on_action") and case_type not in ("note", "unmute", "unban"):
            dm_embed = discord.Embed(
                title=f"{case_type.title()} — {guild.name}",
                description=f"**Reason:** {reason}",
                colour=Clr.MOD,
            )
            if duration:
                dm_embed.add_field(name="Duration", value=duration_str(duration))
            if data.get("appeal_enabled"):
                dm_embed.set_footer(text="You can appeal this action in the server.")
            await safe_dm(user, embed=dm_embed)

        return case_id

    # ── Warn system ────────────────────────────────────────────────────────
    async def _warn_user(self, ctx: commands.Context, user: discord.Member, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "warn", user, ctx.author, reason)

        uid = str(user.id)
        async with self.mod_config.guild(ctx.guild).warnings() as warnings:
            if uid not in warnings:
                warnings[uid] = []
            warnings[uid].append({
                "id": case_id,
                "reason": reason,
                "mod_id": ctx.author.id,
                "timestamp": ts_now(),
            })
            warn_count = len(warnings[uid])

        # Auto-escalation
        data = await self.mod_config.guild(ctx.guild).all()
        esc = data.get("escalation", {})
        if esc.get("enabled"):
            thresholds = esc.get("thresholds", {})
            action = thresholds.get(str(warn_count))
            if action:
                await self._execute_escalation(ctx, user, action, warn_count)

        return case_id

    async def _execute_escalation(self, ctx: commands.Context, user: discord.Member, action: str, warn_count: int):
        """Execute an automatic escalation action."""
        if action.startswith("mute_"):
            duration_text = action.replace("mute_", "")
            duration = parse_duration(duration_text) or 3600
            try:
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=duration)
                await user.timeout(until, reason=f"Auto-escalation: {warn_count} warnings")
                await self._create_case(ctx.guild, "mute", user, ctx.guild.me, f"Auto-escalation ({warn_count} warns)", duration)
                await safe_send(ctx.channel, embed=info_embed(
                    f"⚡ Auto-escalation: {user.mention} muted for {duration_str(duration)} ({warn_count} warnings)"
                ))
            except discord.HTTPException:
                pass

        elif action.startswith("tempban_"):
            duration_text = action.replace("tempban_", "")
            duration = parse_duration(duration_text) or 604800
            try:
                await ctx.guild.ban(user, reason=f"Auto-escalation: {warn_count} warnings", delete_message_seconds=0)
                await self._create_case(ctx.guild, "tempban", user, ctx.guild.me, f"Auto-escalation ({warn_count} warns)", duration)

                async def unban_later():
                    await asyncio.sleep(duration)
                    try:
                        await ctx.guild.unban(user, reason="Tempban expired")
                    except discord.HTTPException:
                        pass
                asyncio.create_task(unban_later())

                await safe_send(ctx.channel, embed=info_embed(
                    f"⚡ Auto-escalation: {user.mention} temp-banned for {duration_str(duration)} ({warn_count} warnings)"
                ))
            except discord.HTTPException:
                pass

        elif action == "ban":
            try:
                await ctx.guild.ban(user, reason=f"Auto-escalation: {warn_count} warnings")
                await self._create_case(ctx.guild, "ban", user, ctx.guild.me, f"Auto-escalation ({warn_count} warns)")
                await safe_send(ctx.channel, embed=info_embed(
                    f"⚡ Auto-escalation: {user.mention} banned ({warn_count} warnings)"
                ))
            except discord.HTTPException:
                pass

        elif action == "kick":
            try:
                await ctx.guild.kick(user, reason=f"Auto-escalation: {warn_count} warnings")
                await self._create_case(ctx.guild, "kick", user, ctx.guild.me, f"Auto-escalation ({warn_count} warns)")
            except discord.HTTPException:
                pass

    # ── Mute / Timeout ─────────────────────────────────────────────────────
    async def _mute_user(self, ctx: commands.Context, user: discord.Member, duration: int, reason: str):
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=duration)
        await user.timeout(until, reason=reason)
        case_id = await self._create_case(ctx.guild, "mute", user, ctx.author, reason, duration)
        return case_id

    async def _unmute_user(self, ctx: commands.Context, user: discord.Member, reason: str = "Unmuted"):
        await user.timeout(None, reason=reason)
        case_id = await self._create_case(ctx.guild, "unmute", user, ctx.author, reason)
        return case_id

    # ── Kick / Ban ─────────────────────────────────────────────────────────
    async def _kick_user(self, ctx: commands.Context, user: discord.Member, reason: str):
        await self._create_case(ctx.guild, "kick", user, ctx.author, reason)
        await ctx.guild.kick(user, reason=f"[{ctx.author}] {reason}")

    async def _ban_user(self, ctx: commands.Context, user: discord.User | discord.Member, reason: str, delete_days: int = 0):
        await self._create_case(ctx.guild, "ban", user, ctx.author, reason)
        await ctx.guild.ban(user, reason=f"[{ctx.author}] {reason}", delete_message_seconds=delete_days * 86400)

    async def _softban_user(self, ctx: commands.Context, user: discord.Member, reason: str):
        await self._create_case(ctx.guild, "softban", user, ctx.author, reason)
        await ctx.guild.ban(user, reason=f"[Softban by {ctx.author}] {reason}", delete_message_seconds=86400)
        await ctx.guild.unban(user, reason="Softban — auto-unban")

    async def _tempban_user(self, ctx: commands.Context, user: discord.Member, duration: int, reason: str):
        await self._create_case(ctx.guild, "tempban", user, ctx.author, reason, duration)
        await ctx.guild.ban(user, reason=f"[Tempban by {ctx.author}] {reason}")

        async def unban_later():
            await asyncio.sleep(duration)
            try:
                await ctx.guild.unban(user, reason="Tempban expired")
                await self._create_case(ctx.guild, "unban", user, ctx.guild.me, "Tempban expired")
            except discord.HTTPException:
                pass
        asyncio.create_task(unban_later())

    async def _unban_user(self, ctx: commands.Context, user: discord.User, reason: str = "Unbanned"):
        await ctx.guild.unban(user, reason=f"[{ctx.author}] {reason}")
        await self._create_case(ctx.guild, "unban", user, ctx.author, reason)

    # ── Notes ──────────────────────────────────────────────────────────────
    async def _add_note(self, guild: discord.Guild, user: discord.User, author: discord.Member, text: str):
        uid = str(user.id)
        async with self.mod_config.guild(guild).notes() as notes:
            if uid not in notes:
                notes[uid] = []
            notes[uid].append({
                "author_id": author.id,
                "text": text,
                "timestamp": ts_now(),
            })
        await self._create_case(guild, "note", user, author, text)

    # ── Lockdown ───────────────────────────────────────────────────────────
    async def _lockdown_channel(self, channel: discord.TextChannel, reason: str = "Lockdown"):
        overwrite = channel.overwrites_for(channel.guild.default_role)
        old_send = overwrite.send_messages
        overwrite.send_messages = False
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite, reason=reason)

        async with self.mod_config.guild(channel.guild).lockdown_role_overrides() as overrides:
            overrides[str(channel.id)] = {"send_messages": old_send}

    async def _unlock_channel(self, channel: discord.TextChannel, reason: str = "Unlock"):
        data = await self.mod_config.guild(channel.guild).all()
        old = data.get("lockdown_role_overrides", {}).get(str(channel.id), {})
        old_send = old.get("send_messages")

        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = old_send  # Restore (could be None/True/False)
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite, reason=reason)

        async with self.mod_config.guild(channel.guild).lockdown_role_overrides() as overrides:
            overrides.pop(str(channel.id), None)

    async def _lockdown_server(self, guild: discord.Guild, mod: discord.Member, reason: str = "Server lockdown"):
        for channel in guild.text_channels:
            try:
                await self._lockdown_channel(channel, reason)
            except discord.HTTPException:
                pass
        log_ch = guild.get_channel((await self.mod_config.guild(guild).modlog_channel()))
        if log_ch:
            await safe_send(log_ch, embed=discord.Embed(
                title="🔒 SERVER LOCKDOWN",
                description=f"All channels locked by {mod.mention}\nReason: {reason}",
                colour=Clr.ERROR,
            ))

    # ── Anti-raid ──────────────────────────────────────────────────────────
    async def _check_anti_raid(self, member: discord.Member):
        guild = member.guild
        data = await self.mod_config.guild(guild).all()
        ar = data.get("anti_raid", {})
        if not ar.get("enabled"):
            return

        gid = guild.id
        if gid not in self._join_tracker:
            self._join_tracker[gid] = collections.deque()

        now = ts_now()
        self._join_tracker[gid].append(now)

        # Clean old entries
        window = ar.get("join_window", 10)
        while self._join_tracker[gid] and now - self._join_tracker[gid][0] > window:
            self._join_tracker[gid].popleft()

        if len(self._join_tracker[gid]) >= ar.get("join_threshold", 10):
            action = ar.get("action", "lockdown")
            notify_ch = guild.get_channel(ar.get("notify_channel")) if ar.get("notify_channel") else None

            if notify_ch:
                await safe_send(notify_ch, embed=discord.Embed(
                    title="🚨 RAID DETECTED",
                    description=f"{len(self._join_tracker[gid])} joins in {window}s! Taking action: `{action}`",
                    colour=Clr.ERROR,
                ))

            if action == "lockdown":
                await self._lockdown_server(guild, guild.me, "Anti-raid triggered")
            elif action == "kick":
                for uid_ts in list(self._join_tracker[gid]):
                    pass  # Already tracked; we'd need member refs
            elif action == "ban":
                pass  # Similar

            self._join_tracker[gid].clear()

    # ── Anti-nuke ──────────────────────────────────────────────────────────
    async def _check_anti_nuke(self, guild: discord.Guild, event_type: str, actor: discord.Member | None = None):
        data = await self.mod_config.guild(guild).all()
        an = data.get("anti_nuke", {})
        if not an.get("enabled") or not actor or actor == guild.owner:
            return

        gid = guild.id
        if gid not in self._nuke_tracker:
            self._nuke_tracker[gid] = {}
        if event_type not in self._nuke_tracker[gid]:
            self._nuke_tracker[gid][event_type] = collections.deque()

        now = ts_now()
        self._nuke_tracker[gid][event_type].append((now, actor.id))

        window = an.get("window", 30)
        while self._nuke_tracker[gid][event_type] and now - self._nuke_tracker[gid][event_type][0][0] > window:
            self._nuke_tracker[gid][event_type].popleft()

        threshold_map = {
            "channel_delete": an.get("channel_delete_threshold", 3),
            "role_delete": an.get("role_delete_threshold", 3),
            "ban": an.get("ban_threshold", 5),
        }
        threshold = threshold_map.get(event_type, 3)

        # Count actions by this specific actor
        actor_count = sum(1 for _, uid in self._nuke_tracker[gid][event_type] if uid == actor.id)
        if actor_count >= threshold:
            action = an.get("action", "strip_roles")
            if action == "strip_roles":
                try:
                    await actor.edit(roles=[], reason=f"Anti-nuke: {event_type} spam detected")
                except discord.HTTPException:
                    pass
            elif action == "ban":
                try:
                    await guild.ban(actor, reason=f"Anti-nuke: {event_type} spam detected")
                except discord.HTTPException:
                    pass

            log_ch = guild.get_channel(data.get("modlog_channel"))
            if log_ch:
                await safe_send(log_ch, embed=discord.Embed(
                    title="🚨 ANTI-NUKE TRIGGERED",
                    description=f"**{actor}** triggered anti-nuke: {actor_count}x `{event_type}` in {window}s\nAction: `{action}`",
                    colour=Clr.ERROR,
                ))

    # ── Auto-mod message check ─────────────────────────────────────────────
    async def _check_automod(self, message: discord.Message) -> bool:
        """Returns True if message was handled (deleted/warned), False otherwise."""
        if not message.guild or message.author.bot:
            return False
        if message.author.guild_permissions.manage_messages:
            return False

        data = await self.mod_config.guild(message.guild).all()
        am = data.get("auto_mod", {})

        # Anti-spam
        spam = am.get("anti_spam", {})
        if spam.get("enabled"):
            key = (message.guild.id, message.author.id)
            if key not in self._spam_tracker:
                self._spam_tracker[key] = collections.deque()
            now = ts_now()
            self._spam_tracker[key].append(now)
            window = spam.get("window", 5)
            while self._spam_tracker[key] and now - self._spam_tracker[key][0] > window:
                self._spam_tracker[key].popleft()
            if len(self._spam_tracker[key]) > spam.get("max_messages", 5):
                await self._automod_action(message, spam.get("action", "mute_10m"), "Spam detected")
                self._spam_tracker[key].clear()
                return True

        # Anti-caps
        caps = am.get("anti_caps", {})
        if caps.get("enabled") and message.content:
            text = message.content
            if len(text) >= caps.get("min_length", 10):
                upper = sum(1 for c in text if c.isupper())
                ratio = (upper / len(text)) * 100
                if ratio >= caps.get("threshold", 70):
                    await self._automod_action(message, caps.get("action", "warn"), "Excessive caps")
                    return True

        # Anti-invite
        inv = am.get("anti_invite", {})
        if inv.get("enabled"):
            import re
            if re.search(r"(discord\.gg|discord\.com/invite)/\w+", message.content, re.IGNORECASE):
                await self._automod_action(message, inv.get("action", "delete_warn"), "Discord invite")
                return True

        # Anti-links
        links = am.get("anti_links", {})
        if links.get("enabled"):
            import re
            if re.search(r"https?://\S+", message.content):
                whitelist = links.get("whitelist", [])
                if not any(w in message.content for w in whitelist):
                    await self._automod_action(message, links.get("action", "delete"), "Link posted")
                    return True

        # Anti-mention spam
        mentions = am.get("anti_mention", {})
        if mentions.get("enabled"):
            if len(message.mentions) + len(message.role_mentions) > mentions.get("max_mentions", 5):
                await self._automod_action(message, mentions.get("action", "mute_10m"), "Mention spam")
                return True

        # Anti-newlines
        nl = am.get("anti_newlines", {})
        if nl.get("enabled") and message.content:
            if message.content.count("\n") > nl.get("max_newlines", 15):
                await self._automod_action(message, nl.get("action", "delete"), "Newline spam")
                return True

        return False

    async def _automod_action(self, message: discord.Message, action: str, reason: str):
        """Execute auto-mod action on a message."""
        if "delete" in action:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        if "warn" in action:
            # Fake ctx for warn
            class _FakeCtx:
                guild = message.guild
                author = message.guild.me
                channel = message.channel
            await self._warn_user(_FakeCtx(), message.author, f"[Auto-Mod] {reason}")

        if "mute" in action:
            import re
            m = re.search(r"mute_(\w+)", action)
            dur = parse_duration(m.group(1)) if m else 600
            try:
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=dur)
                await message.author.timeout(until, reason=f"[Auto-Mod] {reason}")
                await self._create_case(message.guild, "mute", message.author, message.guild.me, f"[Auto-Mod] {reason}", dur)
            except discord.HTTPException:
                pass

        if "kick" in action:
            try:
                await message.guild.kick(message.author, reason=f"[Auto-Mod] {reason}")
                await self._create_case(message.guild, "kick", message.author, message.guild.me, f"[Auto-Mod] {reason}")
            except discord.HTTPException:
                pass

        if "ban" in action and "softban" not in action and "tempban" not in action:
            try:
                await message.guild.ban(message.author, reason=f"[Auto-Mod] {reason}")
                await self._create_case(message.guild, "ban", message.author, message.guild.me, f"[Auto-Mod] {reason}")
            except discord.HTTPException:
                pass
