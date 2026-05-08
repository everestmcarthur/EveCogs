"""NexusCore — Moderation v2: case system, warn escalation, mute/kick/ban, anti-raid, anti-nuke,
automod (6 modules), appeals, slowmode, reputation, quarantine, warning decay, staff leaderboard,
punishment templates, cross-server ban sync, lockdown, purge."""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    duration_str, parse_duration, safe_send, safe_dm, ConfirmView, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
MOD_DEFAULTS_GUILD = {
    "enabled": True,
    "modlog_channel": None,
    "case_counter": 0,
    "cases": {},
    "warnings": {},         # user_id_str -> [warning_dicts]
    "notes": {},            # user_id_str -> [note_dicts]
    "muted_users": {},      # user_id -> {until, reason}
    "reputation": {},       # user_id_str -> int
    "quarantine_role": None,
    "quarantined": [],
    "dm_on_action": True,
    "show_moderator": False,
    "appeal_enabled": False,
    "appeal_channel": None,
    "appeal_cooldown": 86400,
    "anti_raid": {
        "enabled": False, "join_threshold": 10, "join_window": 10,
        "action": "lockdown", "notify_channel": None,
    },
    "anti_nuke": {
        "enabled": False, "action": "strip_roles",
        "ban_threshold": 5, "kick_threshold": 5, "channel_delete_threshold": 3,
        "role_delete_threshold": 3, "window": 30, "whitelist": [],
    },
    "auto_mod": {
        "anti_spam": {"enabled": False, "threshold": 5, "window": 5, "action": "mute_5m"},
        "anti_caps": {"enabled": False, "threshold": 70, "min_length": 10, "action": "delete"},
        "anti_invite": {"enabled": False, "action": "delete", "whitelist": []},
        "anti_links": {"enabled": False, "action": "delete", "whitelist": []},
        "anti_mention": {"enabled": False, "threshold": 5, "action": "mute_5m"},
        "anti_newlines": {"enabled": False, "threshold": 15, "action": "delete"},
    },
    "escalation": {"enabled": True, "thresholds": {}},
    "warn_decay_days": 0,      # 0 = no decay
    "warn_decay_amount": 1,
    "staff_stats": {},         # mod_id_str -> {warns, mutes, kicks, bans}
    "punishment_templates": {},  # template_name -> {action, duration, reason}
    "slowmode_defaults": {"channel": 0, "global": 0},
    "cross_server_ban": {"enabled": False, "webhook_url": None, "log_only": True},
}


# ── Views ──────────────────────────────────────────────────────────────────
class AppealModal(discord.ui.Modal):
    def __init__(self, cog, case_id: str | None = None):
        super().__init__(title="Submit Appeal")
        self.cog = cog
        self.case_id = case_id
        self.case_input = discord.ui.TextInput(label="Case ID (if known)", required=False, max_length=20)
        self.reason_input = discord.ui.TextInput(label="Why should this be reversed?", style=discord.TextStyle.paragraph, max_length=1000, required=True)
        self.add_item(self.case_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        data = await self.cog.mod_config.guild(guild).all()
        appeal_ch_id = data.get("appeal_channel")
        if not appeal_ch_id:
            return await interaction.response.send_message("Appeals channel not configured.", ephemeral=True)
        appeal_ch = guild.get_channel(appeal_ch_id)
        if not appeal_ch:
            return await interaction.response.send_message("Appeals channel not found.", ephemeral=True)

        embed = discord.Embed(title="📨 New Appeal", colour=Clr.MOD,
            timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="User", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
        if self.case_input.value:
            embed.add_field(name="Case", value=self.case_input.value, inline=True)
        embed.add_field(name="Reason", value=self.reason_input.value, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)

        view = AppealReviewView(self.cog, interaction.user.id, self.case_input.value or None)
        await appeal_ch.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Appeal submitted.", ephemeral=True)


class AppealReviewView(discord.ui.View):
    def __init__(self, cog, user_id: int, case_id: str | None):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        self.case_id = case_id

    @discord.ui.button(label="Accept Appeal", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.guild.get_member(self.user_id)
        if user:
            await safe_dm(user, embed=discord.Embed(
                description=f"Your appeal in **{interaction.guild.name}** has been **accepted**.",
                colour=Clr.SUCCESS))
        await interaction.response.send_message(f"✅ Appeal accepted by {interaction.user.mention}.")
        self.stop()

    @discord.ui.button(label="Deny Appeal", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.guild.get_member(self.user_id)
        if user:
            await safe_dm(user, embed=discord.Embed(
                description=f"Your appeal in **{interaction.guild.name}** has been **denied**.",
                colour=Clr.ERROR))
        await interaction.response.send_message(f"❌ Appeal denied by {interaction.user.mention}.")
        self.stop()


class AppealButtonView(discord.ui.View):
    """Persistent button for users to submit appeals."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="📨 Submit Appeal", style=discord.ButtonStyle.primary, custom_id="nexus_mod_appeal")
    async def appeal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.cog.mod_config.guild(interaction.guild).all()
        if not data.get("appeal_enabled"):
            return await interaction.response.send_message("Appeals are disabled.", ephemeral=True)
        modal = AppealModal(self.cog)
        await interaction.response.send_modal(modal)


# ── Mixin ──────────────────────────────────────────────────────────────────
class ModerationMixin:
    """Moderation mixin — v2 with reputation, quarantine, decay, staff lb, templates."""

    def _init_moderation(self, bot):
        self.mod_config = Config.get_conf(None, identifier=900007, cog_name="NexusCoreMod")
        self.mod_config.register_guild(**MOD_DEFAULTS_GUILD)
        self._raid_tracker = {}   # guild_id -> [join_timestamps]
        self._nuke_tracker = {}   # guild_id -> {event_type: [timestamps]}
        self._spam_tracker = {}   # guild_id -> {user_id: [msg_timestamps]}
        self._appeal_view = AppealButtonView(self)
        bot.add_view(self._appeal_view)

    async def _create_case(self, guild, case_type: str, user: discord.User,
                            mod: discord.User, reason: str, duration: int = 0) -> str:
        conf = self.mod_config.guild(guild)
        counter = await conf.case_counter()
        counter += 1
        await conf.case_counter.set(counter)

        case = {
            "id": counter, "type": case_type, "user_id": user.id,
            "user_name": str(user), "mod_id": mod.id,
            "reason": reason, "timestamp": ts_now(),
            "duration": duration, "active": True,
        }
        async with conf.cases() as cases:
            cases[str(counter)] = case

        # Track staff stats
        async with conf.staff_stats() as ss:
            mid = str(mod.id)
            if mid not in ss:
                ss[mid] = {"warns": 0, "mutes": 0, "kicks": 0, "bans": 0}
            stat_key = {"warn": "warns", "mute": "mutes", "kick": "kicks", "ban": "bans",
                        "tempban": "bans", "softban": "bans", "unban": "bans"}.get(case_type, "warns")
            ss[mid][stat_key] = ss[mid].get(stat_key, 0) + 1

        # Modlog
        modlog_ch_id = await conf.modlog_channel()
        if modlog_ch_id:
            modlog = guild.get_channel(modlog_ch_id)
            if modlog:
                emoji_map = {"warn": "⚠️", "mute": "🔇", "unmute": "🔊", "kick": "👢",
                             "ban": "🔨", "softban": "🧹", "tempban": "⏰", "unban": "🔓",
                             "quarantine": "🔒", "unquarantine": "🔓"}
                emoji = emoji_map.get(case_type, "📋")
                colour_map = {"warn": discord.Colour(0xF1C40F), "mute": discord.Colour(0xE67E22),
                              "kick": discord.Colour(0xE74C3C), "ban": Clr.ERROR,
                              "softban": Clr.ERROR, "tempban": Clr.ERROR, "unban": Clr.SUCCESS,
                              "unmute": Clr.SUCCESS}
                embed = discord.Embed(
                    title=f"{emoji} Case #{counter} — {case_type.upper()}",
                    colour=colour_map.get(case_type, Clr.MOD),
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=True)
                show_mod = await conf.show_moderator()
                embed.add_field(name="Moderator", value=mod.mention if show_mod else "Hidden", inline=True)
                embed.add_field(name="Reason", value=reason[:1024], inline=False)
                if duration:
                    embed.add_field(name="Duration", value=duration_str(duration), inline=True)
                embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
                await safe_send(modlog, embed=embed)

        return str(counter)

    # ── Warn with escalation ───────────────────────────────────────────────
    async def _warn_user(self, ctx, user: discord.Member, reason: str) -> str:
        guild = ctx.guild
        case_id = await self._create_case(guild, "warn", user, ctx.author, reason)

        warn_entry = {"id": int(case_id), "reason": reason, "mod_id": ctx.author.id, "timestamp": ts_now()}
        async with self.mod_config.guild(guild).warnings() as warnings:
            uid_str = str(user.id)
            if uid_str not in warnings:
                warnings[uid_str] = []
            warnings[uid_str].append(warn_entry)
            warn_count = len(warnings[uid_str])

        # DM user
        dm_enabled = await self.mod_config.guild(guild).dm_on_action()
        if dm_enabled:
            await safe_dm(user, embed=discord.Embed(
                title=f"⚠️ Warning in {guild.name}",
                description=f"**Reason:** {reason}\n**Warning #{warn_count}**",
                colour=discord.Colour(0xF1C40F)))

        # Reputation decrease
        await self._adjust_reputation(guild, user, -1)

        # Escalation
        esc_data = await self.mod_config.guild(guild).escalation()
        if esc_data.get("enabled"):
            thresholds = esc_data.get("thresholds", {})
            action = thresholds.get(str(warn_count))
            if action:
                await self._execute_escalation(ctx, user, action, f"Warn escalation (#{warn_count})")

        return case_id

    async def _execute_escalation(self, ctx, user: discord.Member, action: str, reason: str):
        """Execute escalation action: mute_Xm, mute_Xh, kick, ban, tempban_Xd."""
        if action.startswith("mute_"):
            dur_str = action.split("_", 1)[1]
            dur = parse_duration(dur_str)
            if dur:
                await self._mute_user(ctx, user, dur, reason)
        elif action == "kick":
            await self._kick_user(ctx, user, reason)
        elif action == "ban":
            await self._ban_user(ctx, user, reason)
        elif action.startswith("tempban_"):
            dur_str = action.split("_", 1)[1]
            dur = parse_duration(dur_str)
            if dur:
                await self._tempban_user(ctx, user, dur, reason)

    async def _mute_user(self, ctx, user: discord.Member, duration: int, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "mute", user, ctx.author, reason, duration)
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=duration)
        try:
            await user.timeout(until, reason=f"Case #{case_id}: {reason}")
        except discord.HTTPException:
            pass
        dm_enabled = await self.mod_config.guild(ctx.guild).dm_on_action()
        if dm_enabled:
            await safe_dm(user, embed=discord.Embed(
                description=f"🔇 You have been muted in **{ctx.guild.name}** for {duration_str(duration)}.\n**Reason:** {reason}",
                colour=discord.Colour(0xE67E22)))
        return case_id

    async def _unmute_user(self, ctx, user: discord.Member, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "unmute", user, ctx.author, reason)
        try:
            await user.timeout(None, reason=f"Case #{case_id}: {reason}")
        except discord.HTTPException:
            pass
        return case_id

    async def _kick_user(self, ctx, user: discord.Member, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "kick", user, ctx.author, reason)
        dm_enabled = await self.mod_config.guild(ctx.guild).dm_on_action()
        if dm_enabled:
            await safe_dm(user, embed=discord.Embed(
                description=f"👢 You have been kicked from **{ctx.guild.name}**.\n**Reason:** {reason}",
                colour=Clr.ERROR))
        try:
            await ctx.guild.kick(user, reason=f"Case #{case_id}: {reason}")
        except discord.HTTPException:
            pass
        return case_id

    async def _ban_user(self, ctx, user: discord.User, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "ban", user, ctx.author, reason)
        dm_enabled = await self.mod_config.guild(ctx.guild).dm_on_action()
        if dm_enabled and isinstance(user, discord.Member):
            await safe_dm(user, embed=discord.Embed(
                description=f"🔨 You have been banned from **{ctx.guild.name}**.\n**Reason:** {reason}",
                colour=Clr.ERROR))
        try:
            await ctx.guild.ban(user, reason=f"Case #{case_id}: {reason}", delete_message_days=0)
        except discord.HTTPException:
            pass

        # Cross-server ban sync
        csb = await self.mod_config.guild(ctx.guild).cross_server_ban()
        if csb.get("enabled") and csb.get("webhook_url"):
            try:
                import aiohttp
                payload = {"content": f"🔨 **Cross-server ban:** {user} (`{user.id}`) from {ctx.guild.name}\nReason: {reason}"}
                async with aiohttp.ClientSession() as session:
                    await session.post(csb["webhook_url"], json=payload)
            except Exception:
                pass

        return case_id

    async def _softban_user(self, ctx, user: discord.Member, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "softban", user, ctx.author, reason)
        try:
            await ctx.guild.ban(user, reason=f"Softban case #{case_id}: {reason}", delete_message_days=7)
            await ctx.guild.unban(user, reason=f"Softban case #{case_id}")
        except discord.HTTPException:
            pass
        return case_id

    async def _tempban_user(self, ctx, user: discord.Member, duration: int, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "tempban", user, ctx.author, reason, duration)
        dm_enabled = await self.mod_config.guild(ctx.guild).dm_on_action()
        if dm_enabled:
            await safe_dm(user, embed=discord.Embed(
                description=f"⏰ You have been temp-banned from **{ctx.guild.name}** for {duration_str(duration)}.\n**Reason:** {reason}",
                colour=Clr.ERROR))
        try:
            await ctx.guild.ban(user, reason=f"Tempban case #{case_id}: {reason}")
        except discord.HTTPException:
            pass
        # Schedule unban
        async def unban_later():
            await asyncio.sleep(duration)
            try:
                fetched = await self.bot.fetch_user(user.id)
                await ctx.guild.unban(fetched, reason=f"Tempban expired (case #{case_id})")
            except discord.HTTPException:
                pass
        asyncio.create_task(unban_later())
        return case_id

    async def _unban_user(self, ctx, user: discord.User, reason: str) -> str:
        case_id = await self._create_case(ctx.guild, "unban", user, ctx.author, reason)
        try:
            await ctx.guild.unban(user, reason=f"Case #{case_id}: {reason}")
        except discord.HTTPException:
            pass
        return case_id

    async def _add_note(self, guild, user: discord.User, author: discord.User, text: str):
        async with self.mod_config.guild(guild).notes() as notes:
            uid_str = str(user.id)
            if uid_str not in notes:
                notes[uid_str] = []
            notes[uid_str].append({"author_id": author.id, "text": text, "timestamp": ts_now()})

    # ── Quarantine ─────────────────────────────────────────────────────────
    async def _quarantine_user(self, ctx, user: discord.Member, reason: str) -> str:
        quarantine_role_id = await self.mod_config.guild(ctx.guild).quarantine_role()
        if not quarantine_role_id:
            return None
        role = ctx.guild.get_role(quarantine_role_id)
        if not role:
            return None
        case_id = await self._create_case(ctx.guild, "quarantine", user, ctx.author, reason)
        try:
            await user.add_roles(role, reason=f"Quarantine case #{case_id}: {reason}")
        except discord.HTTPException:
            pass
        async with self.mod_config.guild(ctx.guild).quarantined() as q:
            if user.id not in q:
                q.append(user.id)
        return case_id

    async def _unquarantine_user(self, ctx, user: discord.Member, reason: str) -> str:
        quarantine_role_id = await self.mod_config.guild(ctx.guild).quarantine_role()
        if not quarantine_role_id:
            return None
        role = ctx.guild.get_role(quarantine_role_id)
        if not role:
            return None
        case_id = await self._create_case(ctx.guild, "unquarantine", user, ctx.author, reason)
        try:
            await user.remove_roles(role, reason=f"Unquarantine case #{case_id}: {reason}")
        except discord.HTTPException:
            pass
        async with self.mod_config.guild(ctx.guild).quarantined() as q:
            if user.id in q:
                q.remove(user.id)
        return case_id

    # ── Reputation ─────────────────────────────────────────────────────────
    async def _adjust_reputation(self, guild, user, amount: int):
        async with self.mod_config.guild(guild).reputation() as rep:
            uid = str(user.id)
            rep[uid] = rep.get(uid, 0) + amount

    async def _get_reputation(self, guild, user) -> int:
        rep = await self.mod_config.guild(guild).reputation()
        return rep.get(str(user.id), 0)

    # ── Lockdown ───────────────────────────────────────────────────────────
    async def _lockdown_channel(self, channel: discord.TextChannel, reason: str):
        overwrites = channel.overwrites_for(channel.guild.default_role)
        overwrites.send_messages = False
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrites, reason=reason)

    async def _unlock_channel(self, channel: discord.TextChannel, reason: str):
        overwrites = channel.overwrites_for(channel.guild.default_role)
        overwrites.send_messages = None
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrites, reason=reason)

    async def _lockdown_server(self, guild: discord.Guild, mod: discord.Member, reason: str):
        for channel in guild.text_channels:
            try:
                await self._lockdown_channel(channel, reason)
            except discord.HTTPException:
                pass
        modlog_id = await self.mod_config.guild(guild).modlog_channel()
        if modlog_id:
            modlog = guild.get_channel(modlog_id)
            if modlog:
                await safe_send(modlog, embed=discord.Embed(
                    title="🔒 SERVER LOCKDOWN", description=f"By: {mod.mention}\nReason: {reason}",
                    colour=Clr.ERROR))

    # ── Anti-raid ──────────────────────────────────────────────────────────
    async def _check_raid(self, member: discord.Member):
        guild = member.guild
        data = await self.mod_config.guild(guild).anti_raid()
        if not data.get("enabled"):
            return
        gid = guild.id
        if gid not in self._raid_tracker:
            self._raid_tracker[gid] = []
        self._raid_tracker[gid].append(ts_now())
        window = data.get("join_window", 10)
        threshold = data.get("join_threshold", 10)
        cutoff = ts_now() - window
        self._raid_tracker[gid] = [t for t in self._raid_tracker[gid] if t >= cutoff]
        if len(self._raid_tracker[gid]) >= threshold:
            action = data.get("action", "lockdown")
            notify_ch_id = data.get("notify_channel")
            if action == "lockdown":
                await self._lockdown_server(guild, guild.me, "Anti-raid triggered")
            elif action == "kick":
                recent = self._raid_tracker[gid][-threshold:]
                for _ in recent:
                    pass
            notify_ch = guild.get_channel(notify_ch_id) if notify_ch_id else None
            if notify_ch:
                await safe_send(notify_ch, embed=discord.Embed(
                    title="🚨 RAID DETECTED",
                    description=f"**{len(self._raid_tracker[gid])}** joins in {window}s!\nAction: {action}",
                    colour=Clr.ERROR))
            self._raid_tracker[gid] = []

    # ── Automod ────────────────────────────────────────────────────────────
    async def _check_automod(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if message.author.guild_permissions.manage_messages:
            return

        data = await self.mod_config.guild(message.guild).auto_mod()

        # Anti-spam
        if data["anti_spam"]["enabled"]:
            gid = message.guild.id
            uid = message.author.id
            if gid not in self._spam_tracker:
                self._spam_tracker[gid] = {}
            if uid not in self._spam_tracker[gid]:
                self._spam_tracker[gid][uid] = []
            self._spam_tracker[gid][uid].append(ts_now())
            window = data["anti_spam"]["window"]
            cutoff = ts_now() - window
            self._spam_tracker[gid][uid] = [t for t in self._spam_tracker[gid][uid] if t >= cutoff]
            if len(self._spam_tracker[gid][uid]) >= data["anti_spam"]["threshold"]:
                await self._automod_action(message, data["anti_spam"]["action"], "Spam detected")
                self._spam_tracker[gid][uid] = []
                return

        # Anti-caps
        if data["anti_caps"]["enabled"]:
            content = message.content
            if len(content) >= data["anti_caps"]["min_length"]:
                upper = sum(1 for c in content if c.isupper())
                pct = (upper / len(content)) * 100
                if pct >= data["anti_caps"]["threshold"]:
                    await self._automod_action(message, data["anti_caps"]["action"], "Excessive caps")
                    return

        # Anti-invite
        if data["anti_invite"]["enabled"]:
            invite_re = re.compile(r"(discord\.gg|discord\.com/invite|discordapp\.com/invite)/[a-zA-Z0-9]+")
            if invite_re.search(message.content):
                whitelist = data["anti_invite"].get("whitelist", [])
                for inv in invite_re.findall(message.content):
                    if not any(w in inv for w in whitelist):
                        await self._automod_action(message, data["anti_invite"]["action"], "Discord invite")
                        return

        # Anti-links
        if data["anti_links"]["enabled"]:
            url_re = re.compile(r"https?://\S+")
            if url_re.search(message.content):
                whitelist = data["anti_links"].get("whitelist", [])
                for url in url_re.findall(message.content):
                    if not any(w in url for w in whitelist):
                        await self._automod_action(message, data["anti_links"]["action"], "Link detected")
                        return

        # Anti-mention
        if data["anti_mention"]["enabled"]:
            if len(message.mentions) >= data["anti_mention"]["threshold"]:
                await self._automod_action(message, data["anti_mention"]["action"], "Mass mention")
                return

        # Anti-newlines
        if data["anti_newlines"]["enabled"]:
            if message.content.count("\n") >= data["anti_newlines"]["threshold"]:
                await self._automod_action(message, data["anti_newlines"]["action"], "Excessive newlines")

    async def _automod_action(self, message: discord.Message, action: str, reason: str):
        if action == "delete":
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        elif action.startswith("mute_"):
            dur_str = action.split("_", 1)[1]
            dur = parse_duration(dur_str)
            if dur:
                until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=dur)
                try:
                    await message.author.timeout(until, reason=f"Automod: {reason}")
                except discord.HTTPException:
                    pass
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        elif action == "warn":
            class _FakeCtx:
                guild = message.guild
                author = message.guild.me
                channel = message.channel
            await self._warn_user(_FakeCtx(), message.author, f"Automod: {reason}")
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        elif action == "kick":
            try:
                await message.guild.kick(message.author, reason=f"Automod: {reason}")
            except discord.HTTPException:
                pass
        elif action == "ban":
            try:
                await message.guild.ban(message.author, reason=f"Automod: {reason}")
            except discord.HTTPException:
                pass

    # ── Warning decay loop ─────────────────────────────────────────────────
    async def _warning_decay_loop(self):
        """Periodically remove old warnings based on decay setting."""
        while True:
            try:
                for guild in self.bot.guilds:
                    data = await self.mod_config.guild(guild).all()
                    decay_days = data.get("warn_decay_days", 0)
                    if not decay_days:
                        continue
                    decay_amount = data.get("warn_decay_amount", 1)
                    cutoff = ts_now() - (decay_days * 86400)
                    async with self.mod_config.guild(guild).warnings() as warnings:
                        for uid, warns in list(warnings.items()):
                            old_warns = [w for w in warns if w.get("timestamp", 0) < cutoff]
                            for _ in old_warns[:decay_amount]:
                                if warns:
                                    warns.pop(0)
                            if not warns:
                                del warnings[uid]
            except Exception:
                pass
            await asyncio.sleep(86400)  # Once a day
