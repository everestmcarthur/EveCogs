"""
Wormhole v4.0.0 — Core cog class, config, and internal helpers.
================================================================

This is the main cog class that Red loads.  Commands are added via
mixin classes in the ``commands/`` package; event listeners live in
``listeners/``.  This file contains:

- Cog initialisation and config registration
- Internal helper methods (_net, _save, _wh, _log, _audit, …)
- Background task management
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Set

import discord
from discord import app_commands
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

from .models.config import DEFAULT_GLOBAL, DEFAULT_NETWORK
from .models.message_map import MessageMap
from .models.permissions import Role, has_role, get_role, role_name
from .ui.modals import ReportModal
from .ui.views import reply_jump_view
from .services.emoji import resolve_foreign_emojis, build_emoji_embeds_and_files
from .utils import (
    BLOCKED_EXTENSIONS,
    COLOUR_ANNOUNCE,
    COLOUR_DM,
    COLOUR_INFO,
    COLOUR_NEUTRAL,
    COLOUR_OK,
    COLOUR_STAR,
    CooldownBucket,
    DuplicateDetector,
    RaidDetector,
    announce_embed,
    apply_mention_policy,
    build_dm_incoming_embed,
    build_dm_relay_embed,
    build_portal_embed,
    build_relay_embed,
    build_star_embed,
    check_attachment_filters,
    check_automod,
    check_filters,
    compact_format,
    dm_embed,
    err_embed,
    format_audit_entry,
    generate_invite_code,
    human_timedelta,
    info_embed,
    ok_embed,
    sanitise_mentions,
    star_embed,
    truncate,
    warn_embed,
)

# Command mixins
from .commands.network import NetworkCommands
from .commands.settings import SettingsCommands
from .commands.moderation import ModerationCommands
from .commands.staff import StaffCommands
from .commands.filters import FilterCommands
from .commands.social import SocialCommands
from .commands.dm import DMCommands
from .commands.advanced import AdvancedCommands
from .commands.mentions import MentionCommands
from .commands.tos import ToSCommands
from .commands.reports import ReportCommands
from .commands.bridge import BridgeCommands
from .commands.debug import DebugCommands

# Listener mixins
from .listeners.relay import RelayListener
from .listeners.sync import SyncListener
from .listeners.misc import MiscListener

log = logging.getLogger("red.evecogs.wormhole")

_AUDIT_LIMIT = 500


class Wormhole(
    # Listeners
    RelayListener,
    SyncListener,
    MiscListener,
    # Commands
    NetworkCommands,
    SettingsCommands,
    ModerationCommands,
    StaffCommands,
    FilterCommands,
    SocialCommands,
    DMCommands,
    AdvancedCommands,
    MentionCommands,
    ToSCommands,
    ReportCommands,
    BridgeCommands,
    DebugCommands,
    commands.Cog,
):
    """The ultimate cross-server relay cog for Red-DiscordBot."""

    __version__ = "4.0.0"

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=928374650, force_registration=True)
        self.config.register_global(**DEFAULT_GLOBAL)

        # In-memory state
        self.msg_map = MessageMap()
        self.cooldowns: Dict[str, CooldownBucket] = {}
        self.dup_detectors: Dict[str, DuplicateDetector] = {}
        self.raid_detectors: Dict[str, RaidDetector] = {}
        self.slowmode_tracker: Dict[str, Dict[int, float]] = {}
        self._wh_cache: Dict[int, discord.Webhook] = {}
        self._ready = asyncio.Event()
        self._bg_tasks: List[asyncio.Task] = []
        self._trace_channels: Set[int] = set()

    async def _init(self) -> None:
        """Deferred initialisation — called from setup() after cog is added."""
        await self.bot.wait_until_ready()
        nets = await self.config.networks()
        for name, nd in nets.items():
            r = nd.get("rate_limit_rate", 5)
            p = nd.get("rate_limit_per", 10.0)
            self.cooldowns[name] = CooldownBucket(r, p)
            am = nd.get("automod", {})
            if am.get("anti_spam"):
                self.dup_detectors[name] = DuplicateDetector(
                    am.get("spam_window", 30.0), am.get("spam_threshold", 3)
                )
            if am.get("anti_raid"):
                self.raid_detectors[name] = RaidDetector(
                    am.get("raid_window", 60.0), am.get("raid_threshold", 10)
                )
        self._bg_tasks.append(asyncio.create_task(self._blackout_loop()))
        self._bg_tasks.append(asyncio.create_task(self._portal_update_loop()))
        self._bg_tasks.append(asyncio.create_task(self._scheduled_msg_loop()))
        self._bg_tasks.append(asyncio.create_task(self._health_check_loop()))
        self._bg_tasks.append(asyncio.create_task(self._poll_expiry_loop()))
        self._register_context_menus()
        self._ready.set()
        log.info("Wormhole v%s ready — %d networks loaded", self.__version__, len(nets))

    # ── Context menu registration ──────────────────────────────────────────

    def _register_context_menus(self) -> None:
        """Register slash commands and context menus."""

        # ── Context menus ──
        ctx_report = app_commands.ContextMenu(name="Report to Wormhole", callback=self._ctx_report_message)
        ctx_bookmark = app_commands.ContextMenu(name="Bookmark (Wormhole)", callback=self._ctx_bookmark_message)
        ctx_delete = app_commands.ContextMenu(name="Delete from Network", callback=self._ctx_delete_message)
        ctx_profile = app_commands.ContextMenu(name="Wormhole Profile", callback=self._ctx_view_profile)
        self.bot.tree.add_command(ctx_report)
        self.bot.tree.add_command(ctx_bookmark)
        self.bot.tree.add_command(ctx_delete)
        self.bot.tree.add_command(ctx_profile)

        # ── Slash commands ──
        @app_commands.command(name="wh-list", description="List wormhole networks")
        async def slash_list(interaction: discord.Interaction):
            ctx = await commands.Context.from_interaction(interaction)
            await self.wh_list(ctx)

        @app_commands.command(name="wh-info", description="Info about a network")
        @app_commands.describe(name="Network name")
        async def slash_info(interaction: discord.Interaction, name: str):
            ctx = await commands.Context.from_interaction(interaction)
            await self.wh_info(ctx, name)

        @app_commands.command(name="wh-accept", description="Accept network rules")
        @app_commands.describe(name="Network name")
        async def slash_accept(interaction: discord.Interaction, name: str):
            ctx = await commands.Context.from_interaction(interaction)
            await self.wh_accept(ctx, name)

        @app_commands.command(name="wh-agree", description="Agree to network ToS")
        @app_commands.describe(name="Network name")
        async def slash_agree(interaction: discord.Interaction, name: str):
            ctx = await commands.Context.from_interaction(interaction)
            await self.wh_agree(ctx, name)

        @app_commands.command(name="wh-report", description="Report a message")
        @app_commands.describe(message_id="Message ID to report", reason="Reason")
        async def slash_report(interaction: discord.Interaction, message_id: str, reason: str = "No reason provided"):
            ctx = await commands.Context.from_interaction(interaction)
            await self.wh_report_msg(ctx, int(message_id), reason=reason)

        @app_commands.command(name="wh-profile", description="View a user's wormhole profile")
        @app_commands.describe(name="Network name", user="User to look up")
        async def slash_profile(interaction: discord.Interaction, name: str, user: discord.User = None):
            ctx = await commands.Context.from_interaction(interaction)
            await self.wh_profile(ctx, name, user)

        @app_commands.command(name="wh-discover", description="Discover public networks")
        async def slash_discover(interaction: discord.Interaction):
            ctx = await commands.Context.from_interaction(interaction)
            await self.wh_discover(ctx)

        for cmd in (slash_list, slash_info, slash_accept, slash_agree,
                    slash_report, slash_profile, slash_discover):
            self.bot.tree.add_command(cmd)

    async def cog_unload(self) -> None:
        for task in self._bg_tasks:
            task.cancel()
        for cmd_name in ("Report to Wormhole", "Bookmark (Wormhole)",
                         "Delete from Network", "Wormhole Profile",
                         "wh-list", "wh-info", "wh-accept", "wh-agree",
                         "wh-report", "wh-profile", "wh-discover"):
            self.bot.tree.remove_command(cmd_name)

    # ── Background task loops ──────────────────────────────────────────────

    async def _blackout_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                now = datetime.now(timezone.utc)
                async with self.config.networks() as nets:
                    for name, nd in nets.items():
                        for sched in nd.get("blackout_schedules", []):
                            day = now.weekday()
                            if day not in sched.get("days", []):
                                continue
                            h = now.hour
                            start, end = sched["start_hour"], sched["end_hour"]
                            in_window = (
                                (start <= h < end) if start < end else (h >= start or h < end)
                            )
                            if in_window and not nd.get("frozen"):
                                nd["frozen"] = True
                                log.info("Blackout freeze: %s", name)
                            elif not in_window and nd.get("frozen") and nd.get("_blackout_froze"):
                                nd["frozen"] = False
                                nd.pop("_blackout_froze", None)
                            if in_window:
                                nd["_blackout_froze"] = True
            except Exception as exc:
                log.error("Blackout loop error: %s", exc)
            await asyncio.sleep(60)

    async def _portal_update_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                nets = await self.config.networks()
                for name, nd in nets.items():
                    for ch_id_s, msg_id in list(nd.get("portal_messages", {}).items()):
                        ch = self.bot.get_channel(int(ch_id_s))
                        if not ch:
                            continue
                        try:
                            msg = await ch.fetch_message(msg_id)
                            em = build_portal_embed(
                                name, nd, len(nd.get("channels", [])),
                                nd.get("total_messages", 0),
                            )
                            await msg.edit(embed=em)
                        except Exception:
                            pass
            except Exception as exc:
                log.error("Portal loop error: %s", exc)
            await asyncio.sleep(300)

    async def _scheduled_msg_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                now = datetime.now(timezone.utc)
                async with self.config.networks() as nets:
                    for name, nd in nets.items():
                        remaining = []
                        for sm in nd.get("scheduled_messages", []):
                            send_at = datetime.fromisoformat(sm["send_at_iso"])
                            if now >= send_at:
                                for ch_id in nd.get("channels", []):
                                    ch = self.bot.get_channel(ch_id)
                                    if ch:
                                        try:
                                            await ch.send(
                                                embed=announce_embed(
                                                    sm["content"],
                                                    title=f"📅 Scheduled — {name}",
                                                )
                                            )
                                        except Exception:
                                            pass
                            else:
                                remaining.append(sm)
                        nd["scheduled_messages"] = remaining
            except Exception as exc:
                log.error("Scheduled msg loop error: %s", exc)
            await asyncio.sleep(30)

    async def _health_check_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                async with self.config.networks() as nets:
                    for name, nd in nets.items():
                        unhealthy = []
                        for ch_id in nd.get("channels", []):
                            ch = self.bot.get_channel(ch_id)
                            if not ch:
                                unhealthy.append(ch_id)
                                continue
                            perms = ch.permissions_for(ch.guild.me)
                            if not perms.send_messages or not perms.manage_webhooks:
                                unhealthy.append(ch_id)
                        nd["unhealthy_channels"] = unhealthy
                        nd["last_health_check"] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                log.error("Health check error: %s", exc)
            await asyncio.sleep(600)

    async def _poll_expiry_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                now = datetime.now(timezone.utc)
                async with self.config.networks() as nets:
                    for name, nd in nets.items():
                        expired = []
                        for pid, poll in list(nd.get("active_polls", {}).items()):
                            exp = datetime.fromisoformat(poll["expires"])
                            if now >= exp:
                                expired.append(pid)
                                results = self._format_poll_results(poll)
                                for ch_id in nd.get("channels", []):
                                    ch = self.bot.get_channel(ch_id)
                                    if ch:
                                        try:
                                            await ch.send(
                                                embed=info_embed(results, title=f"📊 Poll Ended: {poll['question']}")
                                            )
                                        except Exception:
                                            pass
                        for pid in expired:
                            nd.get("active_polls", {}).pop(pid, None)
            except Exception as exc:
                log.error("Poll expiry error: %s", exc)
            await asyncio.sleep(30)

    @staticmethod
    def _format_poll_results(poll: dict) -> str:
        options = poll.get("options", [])
        votes = poll.get("votes", {})
        lines = []
        total = sum(len(v) for v in votes.values())
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, opt in enumerate(options):
            count = len(votes.get(str(i), []))
            pct = (count / total * 100) if total else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            emoji = emojis[i] if i < len(emojis) else f"{i+1}."
            lines.append(f"{emoji} **{opt}** — {count} votes ({pct:.0f}%)\n`{bar}`")
        lines.append(f"\n**Total votes:** {total}")
        return "\n".join(lines)

    # ── Config helpers ─────────────────────────────────────────────────────

    async def _net(self, name: str) -> Optional[dict]:
        nets = await self.config.networks()
        return nets.get(name)

    async def _save(self, name: str, data: dict) -> None:
        async with self.config.networks() as nets:
            nets[name] = data

    async def _net_for_ch(self, ch_id: int) -> Optional[str]:
        nets = await self.config.networks()
        for n, d in nets.items():
            if ch_id in d.get("channels", []):
                return n
        return None

    # ── Webhook helper ─────────────────────────────────────────────────────

    async def _wh(self, ch: discord.TextChannel, *, force_refresh: bool = False) -> discord.Webhook:
        if not force_refresh and ch.id in self._wh_cache:
            return self._wh_cache[ch.id]
        hooks = await ch.webhooks()
        wh = discord.utils.get(hooks, name="Wormhole")
        if not wh:
            wh = await ch.create_webhook(name="Wormhole")
        self._wh_cache[ch.id] = wh
        return wh

    # ── Identity helpers ───────────────────────────────────────────────────

    def _avatar(self, msg: discord.Message, mode: str, icon: Optional[str]) -> str:
        if mode == "server" and msg.guild and msg.guild.icon:
            return msg.guild.icon.url
        if mode == "custom" and icon:
            return icon
        return msg.author.display_avatar.url

    def _name(self, msg: discord.Message, mode: str, custom: Optional[str], nick: Optional[str] = None) -> str:
        server = nick or msg.guild.name
        user = msg.author.display_name
        if mode == "server":
            return server
        if mode == "custom" and custom:
            return custom
        if mode == "user":
            return user
        return f"{user} @ {server}"

    # ── Anonymous mode ─────────────────────────────────────────────────────

    def _anon_name(self, net_data: dict, user_id: int) -> str:
        salt = net_data.get("anon_salt", "")
        h = hashlib.md5(f"{salt}{user_id}".encode()).hexdigest()[:6]
        return f"Anon-{h}"

    def _anon_avatar(self, user_id: int) -> str:
        idx = user_id % 5
        return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"

    # ── Logging / audit ────────────────────────────────────────────────────

    async def _log(self, d: dict, embed: discord.Embed) -> None:
        ch_id = d.get("log_channel")
        if ch_id:
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    async def _audit(self, name: str, action: str, user: str, target: str = "", details: str = "") -> None:
        entry = format_audit_entry(action, user, target, details)
        async with self.config.networks() as nets:
            if name in nets:
                log_list = nets[name].setdefault("audit_log", [])
                log_list.append(entry)
                if len(log_list) > _AUDIT_LIMIT:
                    nets[name]["audit_log"] = log_list[-_AUDIT_LIMIT:]

    async def _status(self, net_name: str, net_data: dict, src_ch: Optional[int], text: str) -> None:
        for ch_id in net_data.get("channels", []):
            if ch_id == src_ch:
                continue
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=info_embed(text, title=f"🌀 {net_name}"))
                except Exception:
                    pass

    # ── Profile tracking ───────────────────────────────────────────────────

    async def _update_profile(self, name: str, user: discord.User, guild_id: int) -> None:
        async with self.config.networks() as nets:
            if name not in nets:
                return
            profiles = nets[name].setdefault("user_profiles", {})
            uid = str(user.id)
            if uid not in profiles:
                profiles[uid] = {
                    "display_name": user.display_name,
                    "avatar_url": str(user.display_avatar.url),
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "message_count": 0,
                    "servers": [],
                }
            profiles[uid]["message_count"] = profiles[uid].get("message_count", 0) + 1
            profiles[uid]["display_name"] = user.display_name
            profiles[uid]["avatar_url"] = str(user.display_avatar.url)
            if guild_id not in profiles[uid].get("servers", []):
                profiles[uid].setdefault("servers", []).append(guild_id)

    # ── Highlight notifications ────────────────────────────────────────────

    async def _check_highlights(self, net_name: str, net_data: dict, content: str, author_id: int) -> None:
        if not content:
            return
        lowered = content.lower()
        for uid_str, keywords in net_data.get("highlights", {}).items():
            uid = int(uid_str)
            if uid == author_id:
                continue
            for kw in keywords:
                if kw.lower() in lowered:
                    user = self.bot.get_user(uid)
                    if user:
                        try:
                            await user.send(
                                embed=info_embed(
                                    f"Keyword **{kw}** mentioned in `{net_name}`:\n>>> {truncate(content, 200)}",
                                    title="🔔 Highlight",
                                )
                            )
                        except discord.Forbidden:
                            pass
                    break

    # ── AFK system ─────────────────────────────────────────────────────────

    async def _check_afk(self, net_name: str, net_data: dict, message: discord.Message) -> None:
        afk = net_data.get("afk_users", {})
        uid_str = str(message.author.id)

        # Return from AFK
        if uid_str in afk:
            since = afk[uid_str].get("since_iso", "")
            async with self.config.networks() as nets:
                if net_name in nets:
                    nets[net_name].get("afk_users", {}).pop(uid_str, None)
            try:
                await message.channel.send(
                    embed=info_embed(f"Welcome back, {message.author.mention}! AFK removed."),
                    delete_after=10,
                )
            except Exception:
                pass

        # Notify about mentioned AFK users
        if message.mentions:
            for mentioned in message.mentions:
                muid = str(mentioned.id)
                if muid in afk:
                    reason = afk[muid].get("reason", "AFK")
                    try:
                        await message.channel.send(
                            embed=info_embed(
                                f"{mentioned.display_name} is AFK: **{reason}**"
                            ),
                            delete_after=10,
                        )
                    except Exception:
                        pass

    # ── Auto-responses ─────────────────────────────────────────────────────

    async def _check_auto_responses(self, net_name: str, net_data: dict, message: discord.Message) -> None:
        if not message.content:
            return
        ars = net_data.get("auto_responses", {})
        now = time.time()
        for trigger, cfg in ars.items():
            is_regex = cfg.get("regex", False)
            cooldown = cfg.get("cooldown", 0)
            last_used = cfg.get("last_used", 0)
            if cooldown and (now - last_used) < cooldown:
                continue
            matched = False
            if is_regex:
                try:
                    if __import__("re").search(trigger, message.content, __import__("re").IGNORECASE):
                        matched = True
                except Exception:
                    pass
            else:
                if trigger.lower() in message.content.lower():
                    matched = True
            if matched:
                reply = cfg.get("reply", "")
                if reply:
                    try:
                        await message.channel.send(reply)
                    except Exception:
                        pass
                    async with self.config.networks() as nets:
                        if net_name in nets:
                            ar = nets[net_name].get("auto_responses", {}).get(trigger)
                            if ar:
                                ar["last_used"] = now

    # ── Ephemeral delete ───────────────────────────────────────────────────

    async def _schedule_ephemeral_delete(self, msg: discord.Message, delay: int) -> None:
        async def _delete_after():
            await asyncio.sleep(delay)
            try:
                await msg.delete()
            except Exception:
                pass

        asyncio.create_task(_delete_after())

    # ── Quiet hours check ──────────────────────────────────────────────────

    def _is_quiet_hour(self, net_data: dict, user_id: int) -> bool:
        qh = net_data.get("quiet_hours", {}).get(str(user_id))
        if not qh:
            return False
        now = datetime.now(timezone.utc) + timedelta(hours=qh.get("tz_offset", 0))
        h = now.hour
        start, end = qh["start_hour"], qh["end_hour"]
        if start < end:
            return start <= h < end
        return h >= start or h < end

    # ── DM relay ───────────────────────────────────────────────────────────

    async def _relay_to_dm_subs(self, net_name: str, net_data: dict, message: discord.Message) -> None:
        if not net_data.get("dm_enabled"):
            return
        subs = net_data.get("dm_subscribers", [])
        if not subs:
            return
        for uid in subs:
            if uid == message.author.id:
                continue
            if self._is_quiet_hour(net_data, uid):
                continue
            # Check personal ignore list
            ignores = net_data.get("user_ignores", {}).get(str(uid), [])
            if message.author.id in ignores:
                continue
            user = self.bot.get_user(uid)
            if not user:
                continue
            dm_mode = net_data.get("dm_relay_mode", "embed")
            try:
                if dm_mode == "embed":
                    em = build_dm_incoming_embed(
                        message.author.display_name,
                        str(message.author.display_avatar.url),
                        message.guild.name,
                        message.channel.name,
                        message.content,
                        net_name,
                        net_data.get("colour"),
                    )
                    await user.send(embed=em)
                elif dm_mode == "compact":
                    await user.send(
                        content=f"**[{net_name}] {message.author.display_name}:** {truncate(message.content, 1800)}"
                    )
                else:
                    await user.send(content=truncate(message.content, 1900))
            except discord.Forbidden:
                pass

    # ── Analytics ──────────────────────────────────────────────────────────

    async def _record_analytics(self, net_name: str, user_id: int) -> None:
        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y-%m-%d-%H")
        uid_str = str(user_id)
        async with self.config.networks() as nets:
            if net_name not in nets:
                return
            analytics = nets[net_name].setdefault("analytics", {"hourly": {}, "top_users": {}})
            analytics["hourly"][hour_key] = analytics["hourly"].get(hour_key, 0) + 1
            analytics["top_users"][uid_str] = analytics["top_users"].get(uid_str, 0) + 1
            # Prune old hourly data (keep 7 days)
            cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d-%H")
            analytics["hourly"] = {
                k: v for k, v in analytics["hourly"].items() if k >= cutoff
            }

    # ── Per-channel override helper ────────────────────────────────────────

    def _get_override(self, net_data: dict, ch_id: int, key: str):
        overrides = net_data.get("channel_overrides", {}).get(str(ch_id), {})
        return overrides.get(key)

    # ── Context menu callbacks ─────────────────────────────────────────────

    async def _ctx_report_message(self, interaction: discord.Interaction, message: discord.Message) -> None:
        net_name = await self._net_for_ch(message.channel.id)
        if not net_name:
            await interaction.response.send_message("This channel isn't in a wormhole network.", ephemeral=True)
            return
        nd = await self._net(net_name)
        modal = ReportModal(self, net_name, message)
        await interaction.response.send_modal(modal)

    async def _ctx_bookmark_message(self, interaction: discord.Interaction, message: discord.Message) -> None:
        uid_str = str(interaction.user.id)
        bookmark = {
            "content": truncate(message.content or "*[no text]*", 500),
            "author": str(message.author),
            "server": message.guild.name if message.guild else "DM",
            "channel": message.channel.name if hasattr(message.channel, "name") else "DM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "jump_url": message.jump_url,
        }
        async with self.config.bookmarks() as bm:
            bm.setdefault(uid_str, []).append(bookmark)
            if len(bm[uid_str]) > 50:
                bm[uid_str] = bm[uid_str][-50:]
        await interaction.response.send_message(
            embed=ok_embed("Message bookmarked! Use `wh bm list` to view."),
            ephemeral=True,
        )

    async def _ctx_delete_message(self, interaction: discord.Interaction, message: discord.Message) -> None:
        net_name = await self._net_for_ch(message.channel.id)
        if not net_name:
            await interaction.response.send_message("Not in a network.", ephemeral=True)
            return
        nd = await self._net(net_name)
        if not has_role(nd, interaction.user.id, Role.MODERATOR) and not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("You need Moderator role or higher.", ephemeral=True)
            return
        # Find and delete all relayed copies
        orig_id = self.msg_map.get_original(net_name, message.id) or message.id
        relayed = self.msg_map.get_relayed(net_name, orig_id)
        deleted = 0
        for ch_id, msg_id in relayed.items():
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    m = await ch.fetch_message(msg_id)
                    await m.delete()
                    deleted += 1
                except Exception:
                    pass
        try:
            await message.delete()
            deleted += 1
        except Exception:
            pass
        await interaction.response.send_message(
            embed=ok_embed(f"Deleted {deleted} message(s) across the network."),
            ephemeral=True,
        )
        await self._audit(net_name, "ctx_delete", str(interaction.user), str(orig_id))

    async def _ctx_view_profile(self, interaction: discord.Interaction, user: discord.User) -> None:
        nets = await self.config.networks()
        profiles_found = []
        for name, nd in nets.items():
            p = nd.get("user_profiles", {}).get(str(user.id))
            if p:
                role = get_role(nd, user.id)
                profiles_found.append((name, p, role))
        if not profiles_found:
            await interaction.response.send_message("No wormhole profile found for this user.", ephemeral=True)
            return
        em = discord.Embed(
            title=f"🌀 Wormhole Profile — {user.display_name}",
            colour=COLOUR_INFO,
        )
        em.set_thumbnail(url=user.display_avatar.url)
        for name, p, role in profiles_found[:10]:
            em.add_field(
                name=f"Network: {name}",
                value=(
                    f"Role: **{role_name(role)}**\n"
                    f"Messages: {p.get('message_count', 0):,}\n"
                    f"First seen: {p.get('first_seen', 'Unknown')[:10]}"
                ),
                inline=True,
            )
        await interaction.response.send_message(embed=em, ephemeral=True)

    # ── Root command group ─────────────────────────────────────────────────

    @commands.hybrid_group(name="wh", aliases=["wormhole"], invoke_without_command=True)
    async def wh(self, ctx: commands.Context) -> None:
        """🌀 Wormhole — the ultimate cross-server relay."""
        await ctx.send_help(ctx.command)
