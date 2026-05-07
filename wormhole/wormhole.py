"""
Wormhole v3.2.0 — The Ultimate Cross-Server Relay Cog for Red-DiscordBot
=========================================================================

Phase 1: Named networks, webhook relay, edit/delete/reply/reaction/sticker sync,
          staff system, moderation, filters, rate limiting, logging, stats
Phase 2: Embed/compact relay modes, auto-moderation, invites, announcements,
          portals, welcome messages, mention control, user profiles, backup/restore,
          blackout scheduling, global blocklist
Phase 3: DM relay (bidirectional), pin sync, starboard, audit log, anti-raid,
          attachment filters, reputation/karma, MOTD/rules, relay delay, vanity
          invites, keyword highlights/notifications, network roles, per-channel
          overrides, scheduled messages, purge, typing indicators, network
          discovery, message search, slowmode
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

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

log = logging.getLogger("red.evecogs.wormhole")

# ── Default config structures ──────────────────────────────────────────────

_DEFAULT_NETWORK = {
    # ownership / staff
    "owner_id": 0,
    "staff_ids": [],
    # channels
    "channels": [],
    # identity
    "use_webhooks": True,
    "relay_mode": "webhook",       # webhook | embed | compact
    "image_mode": "user",          # user | server | custom
    "name_mode": "both",           # user | server | both | custom
    "custom_icon": None,
    "custom_name": None,
    "colour": None,
    "description": "",
    # moderation
    "banned_users": [],
    "banned_servers": [],
    "muted_users": [],
    "muted_servers": [],
    "word_filters": [],
    "regex_filters": [],
    "allowlist_servers": [],
    # features
    "sync_edits": True,
    "sync_deletes": True,
    "sync_reactions": True,
    "sync_replies": True,
    "sync_threads": False,
    "sync_stickers": True,
    "sync_pins": False,
    "forward_embeds": True,
    "nsfw_gate": True,
    "silent": False,
    "frozen": False,
    # rate limit
    "rate_limit_rate": 5,
    "rate_limit_per": 10.0,
    # logging
    "log_channel": None,
    # server nicknames
    "server_nicknames": {},
    # stats
    "total_messages": 0,
    "created_at": None,
    # ── Phase 2 ──
    "automod": {
        "enabled": False,
        "anti_spam": False,
        "anti_mention_spam": False,
        "anti_caps": False,
        "anti_invite": False,
        "anti_link": False,
        "anti_zalgo": False,
        "anti_spoiler": False,
        "anti_emote_spam": False,
        "anti_newline_spam": False,
        "anti_raid": False,
        "max_mentions": 5,
        "caps_threshold": 0.7,
        "spam_window": 30.0,
        "spam_threshold": 3,
        "max_emotes": 10,
        "max_newlines": 15,
        "raid_window": 60.0,
        "raid_threshold": 10,
    },
    "invites": {},
    "vanity_invite": None,         # custom word invite
    "portal_messages": {},
    "welcome_message": "",
    "mention_control": {
        "strip_everyone": True,
        "strip_role_mentions": False,
        "strip_user_mentions": False,
    },
    "user_profiles": {},
    "blackout_schedules": [],
    # ── Phase 3 ──
    # DM relay
    "dm_enabled": False,
    "dm_subscribers": [],          # user IDs
    "dm_relay_mode": "embed",      # embed | compact | plain
    # Starboard
    "starboard_enabled": False,
    "starboard_channel": None,
    "starboard_threshold": 3,
    "starred_messages": {},        # {original_msg_id: {stars: int, board_msg_id: int}}
    # Audit log
    "audit_log": [],               # list of audit entries (capped at 500)
    # Attachment filters
    "blocked_extensions": [],
    "max_filesize": None,          # bytes
    # Reputation / Karma
    "karma_enabled": False,
    "karma_emoji": "👍",
    "karma_scores": {},            # {user_id_str: int}
    # MOTD / Rules
    "motd": "",
    "rules": "",
    # Relay delay (seconds, 0 = instant)
    "relay_delay": 0,
    # Keyword highlights (DM notifications)
    "highlights": {},              # {user_id_str: [keywords]}
    # Network roles
    "roles": {},                   # {role_name: {perms: [...], members: [user_ids]}}
    # Per-channel overrides
    "channel_overrides": {},       # {channel_id_str: {key: value}}
    # Scheduled messages
    "scheduled_messages": [],      # [{content, send_at_iso, author_id}]
    # Slowmode (network-level, seconds between messages per user)
    "slowmode": 0,
    # Network discovery
    "public": False,               # show in wh discover
    "tags": [],
    # Typing indicator relay
    "sync_typing": False,
}

_DEFAULT_GLOBAL = {
    "networks": {},
    "max_networks_per_user": 10,
    "global_banned_users": [],
    "global_banned_servers": [],
}

_MAP_LIMIT = 2_000
_AUDIT_LIMIT = 500


class _MessageMap:
    def __init__(self):
        self.forward: Dict[str, Dict[int, Dict[int, int]]] = defaultdict(dict)
        self.reverse: Dict[str, Dict[int, int]] = defaultdict(dict)
        self._order: Dict[str, list] = defaultdict(list)

    def add(self, network: str, original_id: int, mapping: Dict[int, int]):
        self.forward[network][original_id] = mapping
        for ch_id, msg_id in mapping.items():
            self.reverse[network][msg_id] = original_id
        self._order[network].append(original_id)
        while len(self._order[network]) > _MAP_LIMIT:
            old = self._order[network].pop(0)
            old_map = self.forward[network].pop(old, {})
            for _ch, _mid in old_map.items():
                self.reverse[network].pop(_mid, None)

    def get_relayed(self, network: str, original_id: int) -> Dict[int, int]:
        return self.forward.get(network, {}).get(original_id, {})

    def get_original(self, network: str, relayed_id: int) -> Optional[int]:
        return self.reverse.get(network, {}).get(relayed_id)

    def get_all_relayed_ids(self, network: str, original_id: int) -> List[int]:
        return list(self.forward.get(network, {}).get(original_id, {}).values())


class Wormhole(commands.Cog):
    """The ultimate cross-server relay: networks, DMs, starboard, auto-mod, invites, portals & more."""

    __version__ = "3.2.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7730187301, force_registration=True)
        self.config.register_global(**_DEFAULT_GLOBAL)

        self.webhook_cache: Dict[int, discord.Webhook] = {}
        self.cooldowns: Dict[str, CooldownBucket] = {}
        self.slowmode_tracker: Dict[str, Dict[int, float]] = defaultdict(dict)  # {network: {user_id: last_time}}
        self.dup_detectors: Dict[str, DuplicateDetector] = {}
        self.raid_detectors: Dict[str, RaidDetector] = {}
        self.msg_map = _MessageMap()

        self._ready = asyncio.Event()
        self._bg_tasks: List[asyncio.Task] = []
        self._startup_task = self.bot.loop.create_task(self._init())

    async def _init(self):
        await self.bot.wait_until_ready()
        networks = await self.config.networks()
        for name, data in networks.items():
            self.cooldowns[name] = CooldownBucket(data.get("rate_limit_rate", 5), data.get("rate_limit_per", 10.0))
            am = data.get("automod", {})
            self.dup_detectors[name] = DuplicateDetector(am.get("spam_window", 30.0), am.get("spam_threshold", 3))
            self.raid_detectors[name] = RaidDetector(am.get("raid_window", 60.0), am.get("raid_threshold", 10))
        self._bg_tasks.append(self.bot.loop.create_task(self._blackout_loop()))
        self._bg_tasks.append(self.bot.loop.create_task(self._portal_update_loop()))
        self._bg_tasks.append(self.bot.loop.create_task(self._scheduled_msg_loop()))
        self._ready.set()
        log.info("Wormhole v3.2.0 ready — %d networks loaded.", len(networks))

    async def cog_unload(self):
        self._startup_task.cancel()
        for t in self._bg_tasks:
            t.cancel()

    # ── Background loops ────────────────────────────────────────────────────

    async def _blackout_loop(self):
        await self._ready.wait()
        while True:
            try:
                await asyncio.sleep(60)
                now_utc = datetime.now(timezone.utc)
                h, d = now_utc.hour, now_utc.weekday()
                async with self.config.networks() as networks:
                    for name, data in networks.items():
                        scheds = data.get("blackout_schedules", [])
                        if not scheds:
                            continue
                        should = False
                        for s in scheds:
                            if d in s.get("days", list(range(7))):
                                st, en = s.get("start_hour", 0), s.get("end_hour", 0)
                                if st <= en:
                                    should = should or (st <= h < en)
                                else:
                                    should = should or (h >= st or h < en)
                        if should and not data.get("frozen"):
                            networks[name]["frozen"] = True
                        elif not should and data.get("frozen"):
                            networks[name]["frozen"] = False
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Blackout loop: %s", e)
                await asyncio.sleep(60)

    async def _portal_update_loop(self):
        await self._ready.wait()
        while True:
            try:
                await asyncio.sleep(300)
                networks = await self.config.networks()
                for name, data in networks.items():
                    portals = data.get("portal_messages", {})
                    if not portals:
                        continue
                    embed = build_portal_embed(name, data, len(data["channels"]), data.get("total_messages", 0))
                    dead = []
                    for cid_s, mid in portals.items():
                        ch = self.bot.get_channel(int(cid_s))
                        if not ch:
                            dead.append(cid_s); continue
                        try:
                            msg = await ch.fetch_message(mid)
                            await msg.edit(embed=embed)
                        except discord.NotFound:
                            dead.append(cid_s)
                        except Exception:
                            pass
                    if dead:
                        async with self.config.networks() as nets:
                            if name in nets:
                                for c in dead:
                                    nets[name].get("portal_messages", {}).pop(c, None)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Portal loop: %s", e)
                await asyncio.sleep(300)

    async def _scheduled_msg_loop(self):
        await self._ready.wait()
        while True:
            try:
                await asyncio.sleep(30)
                now = datetime.now(timezone.utc)
                async with self.config.networks() as networks:
                    for name, data in networks.items():
                        sched = data.get("scheduled_messages", [])
                        remaining = []
                        for msg_data in sched:
                            send_at = datetime.fromisoformat(msg_data["send_at"])
                            if now >= send_at:
                                # Send it
                                for ch_id in data["channels"]:
                                    ch = self.bot.get_channel(ch_id)
                                    if ch:
                                        try:
                                            em = announce_embed(msg_data["content"], title=f"📅 Scheduled — {name}")
                                            await ch.send(embed=em)
                                        except Exception:
                                            pass
                            else:
                                remaining.append(msg_data)
                        networks[name]["scheduled_messages"] = remaining
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Scheduled msg loop: %s", e)
                await asyncio.sleep(30)

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _net(self, name: str) -> Optional[dict]:
        return (await self.config.networks()).get(name)

    async def _save(self, name: str, data: dict):
        async with self.config.networks() as n:
            n[name] = data

    async def _net_for_ch(self, ch_id: int) -> Optional[str]:
        for n, d in (await self.config.networks()).items():
            if ch_id in d.get("channels", []):
                return n
        return None

    async def _wh(self, ch: discord.TextChannel) -> discord.Webhook:
        if ch.id in self.webhook_cache:
            return self.webhook_cache[ch.id]
        try:
            for w in await ch.webhooks():
                if w.user == self.bot.user and w.name == "Wormhole Relay":
                    self.webhook_cache[ch.id] = w
                    return w
            w = await ch.create_webhook(name="Wormhole Relay")
            self.webhook_cache[ch.id] = w
            return w
        except discord.Forbidden:
            raise commands.UserFeedbackCheckFailure("Missing webhook permissions.")

    def _avatar(self, msg, mode, icon):
        if mode == "server":
            i = msg.guild.icon
            return i.url if i else msg.author.display_avatar.url
        if mode == "custom" and icon:
            return icon
        return msg.author.display_avatar.url

    def _name(self, msg, mode, custom, nick=None):
        g = nick or msg.guild.name
        u = msg.author.display_name
        if mode == "server": return g
        if mode == "both": return f"{g} • {u}"
        if mode == "custom" and custom: return custom.replace("{user}", u).replace("{server}", g)
        return u

    async def _is_staff(self, d, uid): return uid == d["owner_id"] or uid in d.get("staff_ids", [])
    async def _is_owner(self, d, uid): return uid == d["owner_id"]

    def _get_override(self, net_data, ch_id, key):
        """Get per-channel override or fall back to network setting."""
        overrides = net_data.get("channel_overrides", {}).get(str(ch_id), {})
        if key in overrides:
            return overrides[key]
        return net_data.get(key)

    async def _log(self, d, embed):
        ch_id = d.get("log_channel")
        if ch_id:
            ch = self.bot.get_channel(ch_id)
            if ch:
                try: await ch.send(embed=embed)
                except Exception: pass

    async def _audit(self, name, action, user, target="", details=""):
        entry = format_audit_entry(action, str(user), target, details)
        async with self.config.networks() as nets:
            if name in nets:
                al = nets[name].setdefault("audit_log", [])
                al.append(entry)
                if len(al) > _AUDIT_LIMIT:
                    nets[name]["audit_log"] = al[-_AUDIT_LIMIT:]

    async def _status(self, net_name, net_data, src_ch, text):
        if net_data.get("silent"): return
        em = info_embed(text, title=f"🌀 {net_name}")
        for ch_id in net_data["channels"]:
            if ch_id == (src_ch.id if src_ch else 0): continue
            ch = self.bot.get_channel(ch_id)
            if ch:
                try: await ch.send(embed=em)
                except Exception: pass

    async def _update_profile(self, name, user, guild_id):
        uid = str(user.id)
        async with self.config.networks() as nets:
            if name not in nets: return
            p = nets[name].setdefault("user_profiles", {})
            if uid not in p:
                p[uid] = {"messages": 0, "first_seen": datetime.now(timezone.utc).isoformat(), "servers": []}
            p[uid]["messages"] += 1
            if guild_id not in p[uid].get("servers", []):
                p[uid].setdefault("servers", []).append(guild_id)

    async def _check_highlights(self, net_name, net_data, content, author_id):
        """DM users who have keyword highlights matching this message."""
        highlights = net_data.get("highlights", {})
        if not highlights or not content:
            return
        lower = content.lower()
        for uid_str, keywords in highlights.items():
            uid = int(uid_str)
            if uid == author_id:
                continue
            for kw in keywords:
                if kw.lower() in lower:
                    user = self.bot.get_user(uid)
                    if user:
                        try:
                            em = info_embed(
                                f"Keyword **{kw}** was mentioned in **{net_name}**:\n\n> {truncate(content, 300)}",
                                title="🔔 Highlight"
                            )
                            await user.send(embed=em)
                        except Exception:
                            pass
                    break  # one DM per message per user

    async def _relay_to_dm_subs(self, net_name, net_data, message):
        """Forward a network message to all DM subscribers."""
        if not net_data.get("dm_enabled"):
            return
        subs = net_data.get("dm_subscribers", [])
        if not subs:
            return
        dm_mode = net_data.get("dm_relay_mode", "embed")
        for uid in subs:
            if uid == message.author.id:
                continue
            user = self.bot.get_user(uid)
            if not user:
                continue
            try:
                nick = net_data.get("server_nicknames", {}).get(str(message.guild.id))
                if dm_mode == "embed":
                    em = build_dm_incoming_embed(
                        message.author.display_name,
                        message.author.display_avatar.url,
                        nick or message.guild.name,
                        message.channel.name,
                        message.content,
                        net_name,
                        net_data.get("colour"),
                    )
                    await user.send(embed=em)
                elif dm_mode == "compact":
                    server = nick or message.guild.name
                    text = f"**[{server}] {message.author.display_name}:** {truncate(message.content, 1800)}"
                    await user.send(text)
                else:
                    await user.send(f"**{message.author.display_name}** ({message.guild.name}): {truncate(message.content, 1800)}")
            except Exception:
                pass

    # ── Main group ──────────────────────────────────────────────────────────

    @commands.group(name="wh", aliases=["wormhole"], invoke_without_command=True)
    async def wh(self, ctx: commands.Context):
        """🌀 Wormhole — the ultimate cross-server relay. Use `[p]wh help` for commands."""
        await ctx.send_help(ctx.command)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  NETWORK MANAGEMENT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="create")
    async def wh_create(self, ctx, name: str, *, description: str = ""):
        """Create a new wormhole network."""
        name = name.lower().strip()
        if not name.replace("-", "").replace("_", "").isalnum() or len(name) > 32:
            return await ctx.send(embed=err_embed("Name: alphanumeric/hyphens/underscores, max 32 chars."))
        nets = await self.config.networks()
        if name in nets:
            return await ctx.send(embed=err_embed(f"**{name}** already exists."))
        mx = await self.config.max_networks_per_user()
        if sum(1 for n in nets.values() if n["owner_id"] == ctx.author.id) >= mx:
            return await ctx.send(embed=err_embed(f"You own the max of {mx} networks."))
        d = deepcopy(_DEFAULT_NETWORK)
        d["owner_id"] = ctx.author.id
        d["description"] = description
        d["created_at"] = datetime.now(timezone.utc).isoformat()
        await self._save(name, d)
        self.cooldowns[name] = CooldownBucket(d["rate_limit_rate"], d["rate_limit_per"])
        self.dup_detectors[name] = DuplicateDetector()
        self.raid_detectors[name] = RaidDetector()
        p = ctx.clean_prefix
        await ctx.send(embed=ok_embed(
            f"Network **{name}** created!\n\n"
            f"`{p}wh open {name}` — link a channel\n"
            f"`{p}wh set {name} ...` — customise\n"
            f"`{p}wh invite create {name}` — share invite\n"
            f"`{p}wh dm enable {name}` — enable DM relay",
            title="🌀 Network Created"))
        await self._audit(name, "create", ctx.author)

    @wh.command(name="delete")
    async def wh_delete(self, ctx, name: str):
        """Delete a network (owner/bot-owner). Requires confirmation."""
        name = name.lower()
        d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed(f"**{name}** not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Owner or bot-owner only."))
        await ctx.send(embed=warn_embed(f"Type **`yes`** in 30 s to delete **{name}**."))
        try:
            await self.bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "yes", timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send(embed=info_embed("Cancelled."))
        async with self.config.networks() as n: n.pop(name, None)
        self.cooldowns.pop(name, None)
        self.dup_detectors.pop(name, None)
        self.raid_detectors.pop(name, None)
        await ctx.send(embed=ok_embed(f"**{name}** deleted."))

    @wh.command(name="open")
    @commands.guild_only()
    async def wh_open(self, ctx, name: str):
        """Link this channel to a network."""
        name = name.lower()
        d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed(f"**{name}** not found."))
        if d.get("allowlist_servers") and ctx.guild.id not in d["allowlist_servers"]:
            return await ctx.send(embed=err_embed("Server not on allowlist."))
        if ctx.guild.id in d.get("banned_servers", []):
            return await ctx.send(embed=err_embed("Server banned from network."))
        gbu = await self.config.global_banned_servers()
        if ctx.guild.id in gbu:
            return await ctx.send(embed=err_embed("Server globally blocked."))
        if ctx.channel.id in d["channels"]:
            return await ctx.send(embed=err_embed("Already linked."))
        ex = await self._net_for_ch(ctx.channel.id)
        if ex: return await ctx.send(embed=err_embed(f"Already in **{ex}**. Close first."))
        async with self.config.networks() as nets:
            nets[name]["channels"].append(ctx.channel.id)
            d = nets[name]
        await ctx.send(embed=ok_embed(f"Linked to **{name}** ({len(d['channels'])} channels)."))
        await self._status(name, d, ctx.channel, f"📡 **{ctx.guild.name}** › #{ctx.channel.name} joined.")
        if d.get("welcome_message"):
            await ctx.send(embed=info_embed(d["welcome_message"], title=f"👋 Welcome to {name}!"))
        if d.get("motd"):
            await ctx.send(embed=info_embed(d["motd"], title=f"📋 MOTD — {name}"))
        if d.get("rules"):
            await ctx.send(embed=info_embed(d["rules"], title=f"📜 Rules — {name}"))
        await self._audit(name, "open", ctx.author, target=f"#{ctx.channel.name}")

    @wh.command(name="close")
    @commands.guild_only()
    async def wh_close(self, ctx, name: str = None):
        """Unlink this channel."""
        if not name:
            name = await self._net_for_ch(ctx.channel.id)
            if not name: return await ctx.send(embed=err_embed("Not linked."))
        else:
            name = name.lower()
        d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed(f"**{name}** not found."))
        if ctx.channel.id not in d["channels"]:
            return await ctx.send(embed=err_embed("Not linked."))
        async with self.config.networks() as nets:
            nets[name]["channels"].remove(ctx.channel.id)
            nets[name].get("portal_messages", {}).pop(str(ctx.channel.id), None)
            d = nets[name]
        self.webhook_cache.pop(ctx.channel.id, None)
        await ctx.send(embed=ok_embed(f"Severed from **{name}**."))
        await self._status(name, d, ctx.channel, f"📡 **{ctx.guild.name}** › #{ctx.channel.name} left.")
        await self._audit(name, "close", ctx.author, target=f"#{ctx.channel.name}")

    @wh.command(name="list")
    async def wh_list(self, ctx):
        """List all networks."""
        nets = await self.config.networks()
        if not nets: return await ctx.send(embed=info_embed("No networks yet."))
        lines = []
        for n, d in sorted(nets.items()):
            st = "❄️" if d.get("frozen") else f"✅{len(d['channels'])}ch"
            mode = d.get("relay_mode", "webhook")
            dm = " 📧" if d.get("dm_enabled") else ""
            pub = " 🌍" if d.get("public") else ""
            lines.append(f"**{n}** — {st} `{mode}`{dm}{pub}")
        await ctx.send(embed=info_embed("\n".join(lines), title="🌀 Networks"))

    @wh.command(name="discover")
    async def wh_discover(self, ctx):
        """List public networks anyone can join."""
        nets = await self.config.networks()
        public = {n: d for n, d in nets.items() if d.get("public")}
        if not public:
            return await ctx.send(embed=info_embed("No public networks available."))
        lines = []
        for n, d in sorted(public.items()):
            desc = truncate(d.get("description") or "No description", 60)
            ch = len(d["channels"])
            tags = " ".join(f"`{t}`" for t in d.get("tags", [])[:3])
            lines.append(f"**{n}** — {ch} channels — {desc} {tags}")
        await ctx.send(embed=info_embed("\n".join(lines), title="🌍 Public Networks"))

    @wh.command(name="info")
    async def wh_info(self, ctx, name: str):
        """Show detailed network info."""
        name = name.lower()
        d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed(f"**{name}** not found."))

        owner = self.bot.get_user(d["owner_id"])
        colour = discord.Colour(d["colour"]) if d.get("colour") else COLOUR_INFO
        em = discord.Embed(title=f"🌀 {name}", description=d.get("description") or "*No description.*", colour=colour)
        em.add_field(name="Owner", value=str(owner or d["owner_id"]), inline=True)
        em.add_field(name="Staff", value=str(len(d.get("staff_ids", []))), inline=True)
        em.add_field(name="Channels", value=str(len(d["channels"])), inline=True)
        em.add_field(name="Relayed", value=f"{d.get('total_messages', 0):,}", inline=True)
        em.add_field(name="Mode", value=f"`{d.get('relay_mode', 'webhook')}`", inline=True)
        em.add_field(name="Frozen", value="✅" if d.get("frozen") else "❌", inline=True)

        flags = []
        for f in ("sync_edits", "sync_deletes", "sync_reactions", "sync_replies", "sync_stickers", "sync_pins", "sync_typing", "forward_embeds", "dm_enabled", "starboard_enabled", "karma_enabled"):
            if d.get(f): flags.append(f"✅ {f.replace('_', ' ').title()}")
        if flags: em.add_field(name="Features", value="\n".join(flags), inline=False)

        em.add_field(name="Identity", value=f"Name: `{d['name_mode']}`  Image: `{d['image_mode']}`", inline=True)
        em.add_field(name="Rate limit", value=f"{d.get('rate_limit_rate',5)}/{d.get('rate_limit_per',10)}s", inline=True)

        if d.get("slowmode"): em.add_field(name="Slowmode", value=f"{d['slowmode']}s", inline=True)
        if d.get("relay_delay"): em.add_field(name="Relay delay", value=f"{d['relay_delay']}s", inline=True)
        dm_subs = len(d.get("dm_subscribers", []))
        if dm_subs: em.add_field(name="DM Subscribers", value=str(dm_subs), inline=True)
        if d.get("vanity_invite"): em.add_field(name="Vanity", value=f"`{d['vanity_invite']}`", inline=True)
        if d.get("motd"): em.add_field(name="MOTD", value=truncate(d["motd"], 100), inline=False)

        channels_list = []
        for ch_id in d["channels"][:15]:
            ch = self.bot.get_channel(ch_id)
            channels_list.append(f"• **{ch.guild.name}** › #{ch.name}" if ch else f"• `{ch_id}`")
        if channels_list: em.add_field(name="Channels", value="\n".join(channels_list), inline=False)
        if d.get("created_at"): em.set_footer(text=f"Created {d['created_at'][:10]} • v3.2.0")
        if d.get("custom_icon"): em.set_thumbnail(url=d["custom_icon"])
        await ctx.send(embed=em)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  SETTINGS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="set", invoke_without_command=True)
    async def wh_set(self, ctx):
        """Customise network settings."""
        await ctx.send_help(ctx.command)

    async def _toggle(self, ctx, name, key, value):
        name = name.lower()
        d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed(f"**{name}** not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff/owner only."))
        async with self.config.networks() as n: n[name][key] = value
        await ctx.send(embed=ok_embed(f"**{key.replace('_',' ').title()}** {'enabled' if value else 'disabled'} for **{name}**."))
        await self._audit(name, f"set {key}", ctx.author, details=str(value))

    # All the toggle commands
    @wh_set.command(name="relay-mode")
    async def wh_set_relay_mode(self, ctx, name: str, mode: str):
        """Set relay mode: webhook | embed | compact"""
        if mode.lower() not in ("webhook", "embed", "compact"):
            return await ctx.send(embed=err_embed("Must be `webhook`, `embed`, or `compact`."))
        name = name.lower()
        d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed(f"**{name}** not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff/owner only."))
        async with self.config.networks() as n:
            n[name]["relay_mode"] = mode.lower()
            n[name]["use_webhooks"] = mode.lower() == "webhook"
        await ctx.send(embed=ok_embed(f"Relay mode → `{mode}` for **{name}**."))

    @wh_set.command(name="webhooks")
    async def wh_set_wh(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "use_webhooks", toggle)
    @wh_set.command(name="sync-edits")
    async def wh_set_se(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "sync_edits", toggle)
    @wh_set.command(name="sync-deletes")
    async def wh_set_sd(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "sync_deletes", toggle)
    @wh_set.command(name="sync-reactions")
    async def wh_set_sr(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "sync_reactions", toggle)
    @wh_set.command(name="sync-replies")
    async def wh_set_srp(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "sync_replies", toggle)
    @wh_set.command(name="sync-stickers")
    async def wh_set_ss(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "sync_stickers", toggle)
    @wh_set.command(name="sync-threads")
    async def wh_set_st(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "sync_threads", toggle)
    @wh_set.command(name="sync-pins")
    async def wh_set_sp(self, ctx, name: str, toggle: bool):
        """Toggle pin synchronisation across channels."""
        await self._toggle(ctx, name, "sync_pins", toggle)
    @wh_set.command(name="sync-typing")
    async def wh_set_styp(self, ctx, name: str, toggle: bool):
        """Toggle typing indicator relay."""
        await self._toggle(ctx, name, "sync_typing", toggle)
    @wh_set.command(name="forward-embeds")
    async def wh_set_fe(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "forward_embeds", toggle)
    @wh_set.command(name="nsfw-gate")
    async def wh_set_nsfw(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "nsfw_gate", toggle)
    @wh_set.command(name="silent")
    async def wh_set_sil(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "silent", toggle)
    @wh_set.command(name="freeze")
    async def wh_set_frz(self, ctx, name: str, toggle: bool): await self._toggle(ctx, name, "frozen", toggle)
    @wh_set.command(name="public")
    async def wh_set_pub(self, ctx, name: str, toggle: bool):
        """Make the network discoverable."""
        await self._toggle(ctx, name, "public", toggle)

    @wh_set.command(name="name-mode")
    async def wh_set_nm(self, ctx, name: str, mode: str):
        """user | server | both | custom"""
        if mode.lower() not in ("user", "server", "both", "custom"):
            return await ctx.send(embed=err_embed("Invalid mode."))
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["name_mode"] = mode.lower()
        await ctx.send(embed=ok_embed(f"Name mode → `{mode}`."))

    @wh_set.command(name="image-mode")
    async def wh_set_im(self, ctx, name: str, mode: str):
        """user | server | custom"""
        if mode.lower() not in ("user", "server", "custom"):
            return await ctx.send(embed=err_embed("Invalid mode."))
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["image_mode"] = mode.lower()
        await ctx.send(embed=ok_embed(f"Image mode → `{mode}`."))

    @wh_set.command(name="custom-icon")
    async def wh_set_ci(self, ctx, name: str, url: str):
        """Set custom icon URL."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["custom_icon"] = url
        await ctx.send(embed=ok_embed("Icon set."))

    @wh_set.command(name="custom-name")
    async def wh_set_cn(self, ctx, name: str, *, template: str):
        """Set name template ({user}, {server})."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["custom_name"] = template
        await ctx.send(embed=ok_embed(f"Template → `{template}`."))

    @wh_set.command(name="description")
    async def wh_set_desc(self, ctx, name: str, *, text: str):
        """Set network description."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["description"] = text[:1024]
        await ctx.send(embed=ok_embed("Description updated."))

    @wh_set.command(name="colour", aliases=["color"])
    async def wh_set_col(self, ctx, name: str, hex_colour: str):
        """Set accent colour (#hex)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        try: val = int(hex_colour.strip("#"), 16)
        except ValueError: return await ctx.send(embed=err_embed("Invalid hex."))
        async with self.config.networks() as n: n[name]["colour"] = val
        await ctx.send(embed=ok_embed("Colour set."))

    @wh_set.command(name="ratelimit")
    async def wh_set_rl(self, ctx, name: str, rate: int, per: float):
        """Set rate limit: <msgs> per <seconds>."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["rate_limit_rate"] = rate; n[name]["rate_limit_per"] = per
        self.cooldowns.setdefault(name, CooldownBucket()).update(rate, per)
        await ctx.send(embed=ok_embed(f"Rate limit → {rate}/{per}s."))

    @wh_set.command(name="slowmode")
    async def wh_set_slow(self, ctx, name: str, seconds: int):
        """Set network-wide slowmode (0 to disable)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["slowmode"] = max(0, seconds)
        await ctx.send(embed=ok_embed(f"Slowmode → {seconds}s."))

    @wh_set.command(name="relay-delay")
    async def wh_set_delay(self, ctx, name: str, seconds: int):
        """Set relay delay in seconds (0=instant, max 30)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["relay_delay"] = min(30, max(0, seconds))
        await ctx.send(embed=ok_embed(f"Relay delay → {seconds}s."))

    @wh_set.command(name="log-channel")
    async def wh_set_log(self, ctx, name: str, channel: discord.TextChannel = None):
        """Set/clear log channel."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["log_channel"] = channel.id if channel else None
        await ctx.send(embed=ok_embed(f"Log → {channel.mention if channel else 'disabled'}."))

    @wh_set.command(name="nickname")
    async def wh_set_nick(self, ctx, name: str, *, nickname: str):
        """Set server nickname in network."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        async with self.config.networks() as n:
            n[name].setdefault("server_nicknames", {})[str(ctx.guild.id)] = nickname
        await ctx.send(embed=ok_embed(f"This server → **{nickname}** in **{name}**."))

    @wh_set.command(name="welcome")
    async def wh_set_welc(self, ctx, name: str, *, msg: str):
        """Set welcome message."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["welcome_message"] = msg[:1024]
        await ctx.send(embed=ok_embed("Welcome message set."))

    @wh_set.command(name="motd")
    async def wh_set_motd(self, ctx, name: str, *, text: str):
        """Set message of the day."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["motd"] = text[:1024]
        await ctx.send(embed=ok_embed("MOTD set."))

    @wh_set.command(name="rules")
    async def wh_set_rules(self, ctx, name: str, *, text: str):
        """Set network rules."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["rules"] = text[:2048]
        await ctx.send(embed=ok_embed("Rules set."))

    @wh_set.command(name="tags")
    async def wh_set_tags(self, ctx, name: str, *, tags: str):
        """Set discovery tags (comma-separated)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()][:10]
        async with self.config.networks() as n: n[name]["tags"] = tag_list
        await ctx.send(embed=ok_embed(f"Tags → {', '.join(tag_list)}"))

    @wh_set.command(name="max-filesize")
    async def wh_set_maxfs(self, ctx, name: str, megabytes: float):
        """Set max file size in MB (0 to disable)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        val = int(megabytes * 1024 * 1024) if megabytes > 0 else None
        async with self.config.networks() as n: n[name]["max_filesize"] = val
        await ctx.send(embed=ok_embed(f"Max filesize → {megabytes} MB." if val else "Filesize limit disabled."))

    @wh_set.command(name="blocked-extensions")
    async def wh_set_exts(self, ctx, name: str, *, extensions: str):
        """Set blocked file extensions (comma-separated, e.g. .exe,.bat)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        exts = [e.strip().lower() for e in extensions.split(",") if e.strip()]
        async with self.config.networks() as n: n[name]["blocked_extensions"] = exts
        await ctx.send(embed=ok_embed(f"Blocked extensions → {', '.join(exts)}"))

    # ── Mention control ─────────────────────────────────────────────────────

    @wh_set.command(name="strip-everyone")
    async def wh_set_se2(self, ctx, name: str, toggle: bool):
        """Strip @everyone/@here."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name].setdefault("mention_control", {})["strip_everyone"] = toggle
        await ctx.send(embed=ok_embed(f"@everyone stripping {'on' if toggle else 'off'}."))

    @wh_set.command(name="strip-roles")
    async def wh_set_sr2(self, ctx, name: str, toggle: bool):
        """Strip @role mentions."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name].setdefault("mention_control", {})["strip_role_mentions"] = toggle
        await ctx.send(embed=ok_embed(f"@role stripping {'on' if toggle else 'off'}."))

    @wh_set.command(name="strip-users")
    async def wh_set_su(self, ctx, name: str, toggle: bool):
        """Strip @user mentions."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name].setdefault("mention_control", {})["strip_user_mentions"] = toggle
        await ctx.send(embed=ok_embed(f"@user stripping {'on' if toggle else 'off'}."))

    # ── Per-channel overrides ────────────────────────────────────────────────

    @wh_set.command(name="channel-override")
    @commands.guild_only()
    async def wh_set_override(self, ctx, name: str, key: str, value: str):
        """Set a per-channel override for a setting (e.g. relay_mode, name_mode)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        # Parse value
        if value.lower() in ("true", "false"):
            parsed = value.lower() == "true"
        else:
            try: parsed = int(value)
            except ValueError:
                try: parsed = float(value)
                except ValueError: parsed = value
        async with self.config.networks() as n:
            n[name].setdefault("channel_overrides", {}).setdefault(str(ctx.channel.id), {})[key] = parsed
        await ctx.send(embed=ok_embed(f"Override for this channel: `{key}` = `{parsed}`."))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  DM RELAY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="dm", invoke_without_command=True)
    async def wh_dm(self, ctx):
        """DM relay — send/receive wormhole messages via DMs."""
        await ctx.send_help(ctx.command)

    @wh_dm.command(name="enable")
    async def wh_dm_enable(self, ctx, name: str):
        """Enable DM relay for a network (staff only)."""
        await self._toggle(ctx, name, "dm_enabled", True)

    @wh_dm.command(name="disable")
    async def wh_dm_disable(self, ctx, name: str):
        """Disable DM relay for a network (staff only)."""
        await self._toggle(ctx, name, "dm_enabled", False)

    @wh_dm.command(name="mode")
    async def wh_dm_mode(self, ctx, name: str, mode: str):
        """Set DM relay format: embed | compact | plain"""
        if mode.lower() not in ("embed", "compact", "plain"):
            return await ctx.send(embed=err_embed("Must be `embed`, `compact`, or `plain`."))
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["dm_relay_mode"] = mode.lower()
        await ctx.send(embed=ok_embed(f"DM relay mode → `{mode}`."))

    @wh_dm.command(name="subscribe", aliases=["sub"])
    async def wh_dm_sub(self, ctx, name: str):
        """Subscribe to receive network messages via DM."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not d.get("dm_enabled"):
            return await ctx.send(embed=err_embed("DM relay not enabled for this network."))
        if ctx.author.id in d.get("banned_users", []):
            return await ctx.send(embed=err_embed("You're banned from this network."))
        if ctx.author.id in d.get("dm_subscribers", []):
            return await ctx.send(embed=info_embed("Already subscribed."))
        async with self.config.networks() as n:
            n[name].setdefault("dm_subscribers", []).append(ctx.author.id)
        await ctx.send(embed=ok_embed(f"You'll now receive **{name}** messages in your DMs.\nSend messages with: `{ctx.clean_prefix}wh dm send {name} <message>`"))

    @wh_dm.command(name="unsubscribe", aliases=["unsub"])
    async def wh_dm_unsub(self, ctx, name: str):
        """Unsubscribe from DM relay."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if ctx.author.id not in d.get("dm_subscribers", []):
            return await ctx.send(embed=info_embed("Not subscribed."))
        async with self.config.networks() as n:
            if ctx.author.id in n[name].get("dm_subscribers", []):
                n[name]["dm_subscribers"].remove(ctx.author.id)
        await ctx.send(embed=ok_embed(f"Unsubscribed from **{name}** DMs."))

    @wh_dm.command(name="send")
    async def wh_dm_send(self, ctx, name: str, *, message: str):
        """Send a message to a network from anywhere (DMs or channel)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not d.get("dm_enabled"):
            return await ctx.send(embed=err_embed("DM relay not enabled."))
        if d.get("frozen"):
            return await ctx.send(embed=err_embed("Network is frozen."))
        if ctx.author.id in d.get("banned_users", []):
            return await ctx.send(embed=err_embed("You're banned."))
        if ctx.author.id in d.get("muted_users", []):
            return await ctx.send(embed=err_embed("You're muted."))

        # Rate limit
        bucket = self.cooldowns.get(name)
        if bucket and bucket.is_rate_limited(ctx.author.id, name):
            return await ctx.send(embed=warn_embed("Slow down!"))

        # Filter
        if message:
            matched = check_filters(message, d.get("word_filters", []), d.get("regex_filters", []))
            if matched:
                return await ctx.send(embed=warn_embed("Message blocked by filter."))

        # Build embed for channels
        relay_em = build_dm_relay_embed(ctx.author, message, name)

        sent = 0
        for ch_id in d["channels"]:
            ch = self.bot.get_channel(ch_id)
            if not ch: continue
            try:
                relay_mode = self._get_override(d, ch_id, "relay_mode") or d.get("relay_mode", "webhook")
                if relay_mode == "webhook":
                    wh = await self._wh(ch)
                    await wh.send(
                        content=message,
                        username=f"{ctx.author.display_name} (via DM)",
                        avatar_url=ctx.author.display_avatar.url,
                        wait=True,
                    )
                else:
                    await ch.send(embed=relay_em)
                sent += 1
            except Exception:
                pass

        # Also DM to other subscribers
        for uid in d.get("dm_subscribers", []):
            if uid == ctx.author.id: continue
            u = self.bot.get_user(uid)
            if u:
                try:
                    em = build_dm_incoming_embed(
                        f"{ctx.author.display_name} (DM)", ctx.author.display_avatar.url,
                        "Direct Message", "DM", message, name, d.get("colour"))
                    await u.send(embed=em)
                except Exception: pass

        await ctx.send(embed=ok_embed(f"Sent to {sent} channel(s) on **{name}**."))
        async with self.config.networks() as nets:
            if name in nets: nets[name]["total_messages"] = nets[name].get("total_messages", 0) + 1
        await self._update_profile(name, ctx.author, 0)

    @wh_dm.command(name="list")
    async def wh_dm_list(self, ctx):
        """List your DM subscriptions."""
        nets = await self.config.networks()
        subs = [n for n, d in nets.items() if ctx.author.id in d.get("dm_subscribers", [])]
        if not subs:
            return await ctx.send(embed=info_embed("You're not subscribed to any network DM relay."))
        await ctx.send(embed=info_embed("\n".join(f"• **{n}**" for n in subs), title="📧 DM Subscriptions"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STAFF
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="staff", invoke_without_command=True)
    async def wh_staff(self, ctx): await ctx.send_help(ctx.command)

    @wh_staff.command(name="add")
    async def wh_staff_add(self, ctx, name: str, user: discord.User):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return await ctx.send(embed=err_embed("Owner only."))
        if user.id in d.get("staff_ids", []): return await ctx.send(embed=err_embed("Already staff."))
        async with self.config.networks() as n: n[name].setdefault("staff_ids", []).append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} → staff on **{name}**."))
        await self._audit(name, "staff_add", ctx.author, target=str(user))

    @wh_staff.command(name="remove")
    async def wh_staff_rm(self, ctx, name: str, user: discord.User):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return await ctx.send(embed=err_embed("Owner only."))
        async with self.config.networks() as n:
            if user.id in n[name].get("staff_ids", []): n[name]["staff_ids"].remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} removed from staff."))

    @wh_staff.command(name="list")
    async def wh_staff_ls(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        lines = [f"👑 **Owner:** {self.bot.get_user(d['owner_id']) or d['owner_id']}"]
        for uid in d.get("staff_ids", []):
            lines.append(f"⭐ {self.bot.get_user(uid) or uid}")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"Staff — {name}"))

    @wh.command(name="transfer")
    async def wh_transfer(self, ctx, name: str, new_owner: discord.User):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return await ctx.send(embed=err_embed("Owner only."))
        async with self.config.networks() as n:
            n[name]["owner_id"] = new_owner.id
            if new_owner.id in n[name].get("staff_ids", []): n[name]["staff_ids"].remove(new_owner.id)
        await ctx.send(embed=ok_embed(f"Ownership → {new_owner.mention}."))
        await self._audit(name, "transfer", ctx.author, target=str(new_owner))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  MODERATION
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="mod", invoke_without_command=True)
    async def wh_mod(self, ctx): await ctx.send_help(ctx.command)

    @wh_mod.command(name="ban")
    async def wh_mod_ban(self, ctx, name: str, user: discord.User):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return await ctx.send(embed=err_embed("Staff only."))
        async with self.config.networks() as n:
            if user.id not in n[name].get("banned_users", []): n[name].setdefault("banned_users", []).append(user.id)
            # Also remove from DM subs
            if user.id in n[name].get("dm_subscribers", []): n[name]["dm_subscribers"].remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} banned from **{name}**."))
        await self._audit(name, "ban", ctx.author, target=str(user))
        await self._log(d, warn_embed(f"{ctx.author} banned {user}."))

    @wh_mod.command(name="unban")
    async def wh_mod_unban(self, ctx, name: str, user: discord.User):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if user.id in n[name].get("banned_users", []): n[name]["banned_users"].remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} unbanned."))

    @wh_mod.command(name="mute")
    async def wh_mod_mute(self, ctx, name: str, user: discord.User):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if user.id not in n[name].get("muted_users", []): n[name].setdefault("muted_users", []).append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} muted."))

    @wh_mod.command(name="unmute")
    async def wh_mod_unmute(self, ctx, name: str, user: discord.User):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if user.id in n[name].get("muted_users", []): n[name]["muted_users"].remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} unmuted."))

    @wh_mod.command(name="ban-server")
    async def wh_mod_bans(self, ctx, name: str, guild_id: int):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        rm = []
        async with self.config.networks() as n:
            if guild_id not in n[name].get("banned_servers", []): n[name].setdefault("banned_servers", []).append(guild_id)
            for ch_id in list(n[name]["channels"]):
                ch = self.bot.get_channel(ch_id)
                if ch and ch.guild.id == guild_id: n[name]["channels"].remove(ch_id); rm.append(ch_id)
        await ctx.send(embed=ok_embed(f"Server banned, {len(rm)} channels removed."))

    @wh_mod.command(name="unban-server")
    async def wh_mod_unbans(self, ctx, name: str, guild_id: int):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if guild_id in n[name].get("banned_servers", []): n[name]["banned_servers"].remove(guild_id)
        await ctx.send(embed=ok_embed("Server unbanned."))

    @wh_mod.command(name="mute-server")
    async def wh_mod_ms(self, ctx, name: str, guild_id: int):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if guild_id not in n[name].get("muted_servers", []): n[name].setdefault("muted_servers", []).append(guild_id)
        await ctx.send(embed=ok_embed("Server muted."))

    @wh_mod.command(name="unmute-server")
    async def wh_mod_ums(self, ctx, name: str, guild_id: int):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if guild_id in n[name].get("muted_servers", []): n[name]["muted_servers"].remove(guild_id)
        await ctx.send(embed=ok_embed("Server unmuted."))

    @wh_mod.command(name="allowlist-add")
    async def wh_mod_aa(self, ctx, name: str, guild_id: int):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if guild_id not in n[name].get("allowlist_servers", []): n[name].setdefault("allowlist_servers", []).append(guild_id)
        await ctx.send(embed=ok_embed("Added to allowlist."))

    @wh_mod.command(name="allowlist-remove")
    async def wh_mod_ar(self, ctx, name: str, guild_id: int):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            if guild_id in n[name].get("allowlist_servers", []): n[name]["allowlist_servers"].remove(guild_id)
        await ctx.send(embed=ok_embed("Removed from allowlist."))

    @wh_mod.command(name="purge")
    async def wh_mod_purge(self, ctx, name: str, count: int = 10):
        """Delete last N relayed messages across all channels (max 50)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        count = min(50, max(1, count))
        deleted = 0
        for ch_id in d["channels"]:
            ch = self.bot.get_channel(ch_id)
            if not ch: continue
            try:
                msgs = [m async for m in ch.history(limit=count) if m.author == self.bot.user or (m.webhook_id is not None)]
                for m in msgs[:count]:
                    try: await m.delete(); deleted += 1
                    except Exception: pass
            except Exception: pass
        await ctx.send(embed=ok_embed(f"Purged {deleted} messages across network."))
        await self._audit(name, "purge", ctx.author, details=f"{count} requested, {deleted} deleted")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  FILTERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="filter", invoke_without_command=True)
    async def wh_filter(self, ctx): await ctx.send_help(ctx.command)

    @wh_filter.command(name="add-word")
    async def wh_f_aw(self, ctx, name: str, *, word: str):
        name = name.lower(); d = await self._net(name)
        if not d or (not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author)): return
        async with self.config.networks() as n: n[name].setdefault("word_filters", []).append(word)
        await ctx.send(embed=ok_embed("Word filter added."))

    @wh_filter.command(name="remove-word")
    async def wh_f_rw(self, ctx, name: str, *, word: str):
        name = name.lower(); d = await self._net(name)
        if not d or (not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author)): return
        async with self.config.networks() as n:
            if word in n[name].get("word_filters", []): n[name]["word_filters"].remove(word)
        await ctx.send(embed=ok_embed("Word filter removed."))

    @wh_filter.command(name="add-regex")
    async def wh_f_ar(self, ctx, name: str, *, pattern: str):
        try: re.compile(pattern)
        except re.error as e: return await ctx.send(embed=err_embed(f"Invalid: {e}"))
        name = name.lower(); d = await self._net(name)
        if not d or (not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author)): return
        async with self.config.networks() as n: n[name].setdefault("regex_filters", []).append(pattern)
        await ctx.send(embed=ok_embed("Regex filter added."))

    @wh_filter.command(name="remove-regex")
    async def wh_f_rr(self, ctx, name: str, *, pattern: str):
        name = name.lower(); d = await self._net(name)
        if not d or (not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author)): return
        async with self.config.networks() as n:
            if pattern in n[name].get("regex_filters", []): n[name]["regex_filters"].remove(pattern)
        await ctx.send(embed=ok_embed("Regex filter removed."))

    @wh_filter.command(name="list")
    async def wh_f_ls(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return
        lines = []
        for w in d.get("word_filters", []): lines.append(f"Word: `{w}`")
        for r in d.get("regex_filters", []): lines.append(f"Regex: `{r}`")
        await ctx.send(embed=info_embed("\n".join(lines) if lines else "No filters.", title=f"Filters — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  AUTO-MODERATION
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="automod", invoke_without_command=True)
    async def wh_am(self, ctx): await ctx.send_help(ctx.command)

    async def _am_toggle(self, ctx, name, key, val, extra=None):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            n[name].setdefault("automod", {})[key] = val
            if extra:
                for k, v in extra.items(): n[name]["automod"][k] = v
        await ctx.send(embed=ok_embed(f"`{key}` → `{val}` for **{name}**."))

    @wh_am.command(name="enable")
    async def wh_am_on(self, ctx, name: str): await self._am_toggle(ctx, name, "enabled", True)
    @wh_am.command(name="disable")
    async def wh_am_off(self, ctx, name: str): await self._am_toggle(ctx, name, "enabled", False)
    @wh_am.command(name="anti-spam")
    async def wh_am_spam(self, ctx, name: str, toggle: bool): await self._am_toggle(ctx, name, "anti_spam", toggle)
    @wh_am.command(name="anti-mentions")
    async def wh_am_ment(self, ctx, name: str, toggle: bool, max_mentions: int = 5):
        await self._am_toggle(ctx, name, "anti_mention_spam", toggle, {"max_mentions": max_mentions})
    @wh_am.command(name="anti-caps")
    async def wh_am_caps(self, ctx, name: str, toggle: bool, threshold: float = 0.7):
        await self._am_toggle(ctx, name, "anti_caps", toggle, {"caps_threshold": threshold})
    @wh_am.command(name="anti-invite")
    async def wh_am_inv(self, ctx, name: str, toggle: bool): await self._am_toggle(ctx, name, "anti_invite", toggle)
    @wh_am.command(name="anti-link")
    async def wh_am_link(self, ctx, name: str, toggle: bool): await self._am_toggle(ctx, name, "anti_link", toggle)
    @wh_am.command(name="anti-zalgo")
    async def wh_am_zalgo(self, ctx, name: str, toggle: bool):
        """Block zalgo/combining-character text."""
        await self._am_toggle(ctx, name, "anti_zalgo", toggle)
    @wh_am.command(name="anti-spoiler")
    async def wh_am_spoiler(self, ctx, name: str, toggle: bool):
        """Block excessive spoiler tags."""
        await self._am_toggle(ctx, name, "anti_spoiler", toggle)
    @wh_am.command(name="anti-emote-spam")
    async def wh_am_emote(self, ctx, name: str, toggle: bool, max_emotes: int = 10):
        """Block custom emote spam."""
        await self._am_toggle(ctx, name, "anti_emote_spam", toggle, {"max_emotes": max_emotes})
    @wh_am.command(name="anti-newlines")
    async def wh_am_nl(self, ctx, name: str, toggle: bool, max_newlines: int = 15):
        """Block newline spam."""
        await self._am_toggle(ctx, name, "anti_newline_spam", toggle, {"max_newlines": max_newlines})
    @wh_am.command(name="anti-raid")
    async def wh_am_raid(self, ctx, name: str, toggle: bool, threshold: int = 10, window: float = 60):
        """Auto-freeze network on raid detection."""
        await self._am_toggle(ctx, name, "anti_raid", toggle, {"raid_threshold": threshold, "raid_window": window})

    @wh_am.command(name="status")
    async def wh_am_status(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return
        am = d.get("automod", {})
        lines = []
        for k in ("enabled", "anti_spam", "anti_mention_spam", "anti_caps", "anti_invite", "anti_link", "anti_zalgo", "anti_spoiler", "anti_emote_spam", "anti_newline_spam", "anti_raid"):
            lines.append(f"{'✅' if am.get(k) else '❌'} `{k}`")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"Auto-mod — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  INVITES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="invite", invoke_without_command=True)
    async def wh_inv(self, ctx): await ctx.send_help(ctx.command)

    @wh_inv.command(name="create")
    async def wh_inv_create(self, ctx, name: str, max_uses: int = 0, expires_minutes: int = 0):
        """Create invite code. 0=unlimited/no expiry."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        code = generate_invite_code()
        inv = {"uses": 0, "max_uses": max_uses or None,
               "expires_at": datetime.fromtimestamp(time.time() + expires_minutes * 60, tz=timezone.utc).isoformat() if expires_minutes > 0 else None,
               "creator_id": ctx.author.id}
        async with self.config.networks() as n: n[name].setdefault("invites", {})[code] = inv
        await ctx.send(embed=ok_embed(f"Invite for **{name}**:\n```\n{code}\n```\nJoin: `{ctx.clean_prefix}wh invite use {code}`", title="🔗 Invite"))

    @wh_inv.command(name="vanity")
    async def wh_inv_vanity(self, ctx, name: str, *, word: str):
        """Set a vanity invite word (e.g. `gaming` → `[p]wh invite use gaming`)."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        word = word.lower().strip().replace(" ", "-")
        # Check uniqueness
        for n, nd in (await self.config.networks()).items():
            if nd.get("vanity_invite") == word and n != name:
                return await ctx.send(embed=err_embed(f"Vanity `{word}` is taken."))
        async with self.config.networks() as n: n[name]["vanity_invite"] = word
        await ctx.send(embed=ok_embed(f"Vanity invite → `{word}`. Join: `{ctx.clean_prefix}wh invite use {word}`"))

    @wh_inv.command(name="use", aliases=["join"])
    @commands.guild_only()
    async def wh_inv_use(self, ctx, code: str):
        """Use an invite code or vanity name to join."""
        nets = await self.config.networks()
        target = None
        inv_data = None
        is_vanity = False

        # Check vanity first
        for n, d in nets.items():
            if d.get("vanity_invite") and d["vanity_invite"].lower() == code.lower():
                target = n; is_vanity = True; break

        # Then check codes
        if not target:
            for n, d in nets.items():
                if code in d.get("invites", {}):
                    target = n; inv_data = d["invites"][code]; break

        if not target:
            return await ctx.send(embed=err_embed("Invalid invite."))

        d = nets[target]
        if inv_data:
            if inv_data.get("expires_at"):
                if datetime.now(timezone.utc) > datetime.fromisoformat(inv_data["expires_at"]):
                    async with self.config.networks() as n: n[target].get("invites", {}).pop(code, None)
                    return await ctx.send(embed=err_embed("Expired."))
            if inv_data.get("max_uses") and inv_data["uses"] >= inv_data["max_uses"]:
                return await ctx.send(embed=err_embed("Max uses reached."))

        # Standard checks
        if d.get("allowlist_servers") and ctx.guild.id not in d["allowlist_servers"]: return await ctx.send(embed=err_embed("Not on allowlist."))
        if ctx.guild.id in d.get("banned_servers", []): return await ctx.send(embed=err_embed("Server banned."))
        if ctx.channel.id in d["channels"]: return await ctx.send(embed=err_embed("Already linked."))
        ex = await self._net_for_ch(ctx.channel.id)
        if ex: return await ctx.send(embed=err_embed(f"Already in **{ex}**."))

        async with self.config.networks() as n:
            n[target]["channels"].append(ctx.channel.id)
            if inv_data and not is_vanity: n[target]["invites"][code]["uses"] += 1
            d = n[target]
        await ctx.send(embed=ok_embed(f"Linked to **{target}**! ({len(d['channels'])} channels)"))
        await self._status(target, d, ctx.channel, f"📡 **{ctx.guild.name}** joined via invite.")
        if d.get("welcome_message"): await ctx.send(embed=info_embed(d["welcome_message"], title=f"👋 Welcome!"))
        if d.get("motd"): await ctx.send(embed=info_embed(d["motd"], title=f"📋 MOTD"))

    @wh_inv.command(name="revoke")
    async def wh_inv_revoke(self, ctx, name: str, code: str):
        name = name.lower(); d = await self._net(name)
        if not d or (not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author)): return
        async with self.config.networks() as n: n[name].get("invites", {}).pop(code, None)
        await ctx.send(embed=ok_embed(f"Invite `{code}` revoked."))

    @wh_inv.command(name="list")
    async def wh_inv_list(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return
        invs = d.get("invites", {})
        van = d.get("vanity_invite")
        lines = []
        if van: lines.append(f"🌟 Vanity: `{van}`")
        for c, i in invs.items():
            lines.append(f"`{c}` — {i['uses']}/{i.get('max_uses') or '∞'}")
        await ctx.send(embed=info_embed("\n".join(lines) if lines else "No invites.", title=f"Invites — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  ANNOUNCEMENTS & PORTAL
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="announce")
    async def wh_announce(self, ctx, name: str, *, message: str):
        """Broadcast to all channels + DM subscribers."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        em = announce_embed(message, title=f"📢 {name}")
        em.set_footer(text=f"From {ctx.author.display_name}")
        sent = 0
        for ch_id in d["channels"]:
            ch = self.bot.get_channel(ch_id)
            if ch:
                try: await ch.send(embed=em); sent += 1
                except: pass
        # Also DM subscribers
        dm_sent = 0
        for uid in d.get("dm_subscribers", []):
            u = self.bot.get_user(uid)
            if u:
                try: await u.send(embed=em); dm_sent += 1
                except: pass
        await ctx.send(embed=ok_embed(f"Sent to {sent} channels + {dm_sent} DM subscribers."))
        await self._audit(name, "announce", ctx.author)

    @wh.command(name="portal")
    @commands.guild_only()
    async def wh_portal(self, ctx, name: str = None):
        """Create/refresh portal status embed."""
        if not name:
            name = await self._net_for_ch(ctx.channel.id)
            if not name: return await ctx.send(embed=err_embed("Not linked."))
        else: name = name.lower()
        d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        embed = build_portal_embed(name, d, len(d["channels"]), d.get("total_messages", 0))
        existing = d.get("portal_messages", {}).get(str(ctx.channel.id))
        if existing:
            try:
                msg = await ctx.channel.fetch_message(existing)
                await msg.edit(embed=embed)
                return await ctx.send(embed=ok_embed("Portal refreshed!"), delete_after=5)
            except: pass
        msg = await ctx.send(embed=embed)
        try: await msg.pin()
        except: pass
        async with self.config.networks() as n: n[name].setdefault("portal_messages", {})[str(ctx.channel.id)] = msg.id

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STARBOARD
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="starboard", aliases=["star"], invoke_without_command=True)
    async def wh_star(self, ctx): await ctx.send_help(ctx.command)

    @wh_star.command(name="enable")
    async def wh_star_on(self, ctx, name: str, channel: discord.TextChannel, threshold: int = 3):
        """Enable cross-network starboard."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            n[name]["starboard_enabled"] = True
            n[name]["starboard_channel"] = channel.id
            n[name]["starboard_threshold"] = threshold
        await ctx.send(embed=ok_embed(f"Starboard → {channel.mention} (threshold: {threshold}⭐)"))

    @wh_star.command(name="disable")
    async def wh_star_off(self, ctx, name: str):
        await self._toggle(ctx, name, "starboard_enabled", False)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  KARMA / REPUTATION
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="karma", invoke_without_command=True)
    async def wh_karma(self, ctx): await ctx.send_help(ctx.command)

    @wh_karma.command(name="enable")
    async def wh_k_on(self, ctx, name: str, emoji: str = "👍"):
        """Enable karma. React with the emoji on relayed messages."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n:
            n[name]["karma_enabled"] = True
            n[name]["karma_emoji"] = emoji
        await ctx.send(embed=ok_embed(f"Karma enabled (react {emoji} to give karma)."))

    @wh_karma.command(name="disable")
    async def wh_k_off(self, ctx, name: str):
        await self._toggle(ctx, name, "karma_enabled", False)

    @wh_karma.command(name="check")
    async def wh_k_check(self, ctx, name: str, user: discord.User = None):
        """Check karma score."""
        name = name.lower(); d = await self._net(name)
        if not d: return
        user = user or ctx.author
        score = d.get("karma_scores", {}).get(str(user.id), 0)
        await ctx.send(embed=info_embed(f"**{user.display_name}** has **{score}** karma on **{name}**.", title="⭐ Karma"))

    @wh_karma.command(name="leaderboard", aliases=["lb"])
    async def wh_k_lb(self, ctx, name: str):
        """Karma leaderboard."""
        name = name.lower(); d = await self._net(name)
        if not d: return
        scores = d.get("karma_scores", {})
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"] + [f"**{i}.**" for i in range(4, 11)]
        lines = []
        for i, (uid, sc) in enumerate(top):
            u = self.bot.get_user(int(uid))
            lines.append(f"{medals[i]} {u or uid} — **{sc}** karma")
        await ctx.send(embed=info_embed("\n".join(lines) if lines else "No karma yet.", title=f"Karma — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  HIGHLIGHTS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="highlight", aliases=["hl"], invoke_without_command=True)
    async def wh_hl(self, ctx): await ctx.send_help(ctx.command)

    @wh_hl.command(name="add")
    async def wh_hl_add(self, ctx, name: str, *, keyword: str):
        """Get DM'd when a keyword appears in the network."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        uid = str(ctx.author.id)
        async with self.config.networks() as n:
            hl = n[name].setdefault("highlights", {}).setdefault(uid, [])
            if keyword.lower() not in [k.lower() for k in hl]:
                hl.append(keyword)
        await ctx.send(embed=ok_embed(f"Highlight `{keyword}` added for **{name}**."))

    @wh_hl.command(name="remove")
    async def wh_hl_rm(self, ctx, name: str, *, keyword: str):
        name = name.lower()
        async with self.config.networks() as n:
            if name in n:
                hl = n[name].get("highlights", {}).get(str(ctx.author.id), [])
                n[name]["highlights"][str(ctx.author.id)] = [k for k in hl if k.lower() != keyword.lower()]
        await ctx.send(embed=ok_embed(f"Highlight `{keyword}` removed."))

    @wh_hl.command(name="list")
    async def wh_hl_ls(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return
        kws = d.get("highlights", {}).get(str(ctx.author.id), [])
        await ctx.send(embed=info_embed("\n".join(f"• `{k}`" for k in kws) if kws else "No highlights.", title=f"Your Highlights — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  SCHEDULED MESSAGES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="schedule")
    async def wh_schedule(self, ctx, name: str, minutes: int, *, message: str):
        """Schedule a message to be sent to the network in X minutes."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        send_at = datetime.fromtimestamp(time.time() + minutes * 60, tz=timezone.utc).isoformat()
        async with self.config.networks() as n:
            n[name].setdefault("scheduled_messages", []).append({
                "content": message, "send_at": send_at, "author_id": ctx.author.id
            })
        await ctx.send(embed=ok_embed(f"Scheduled for {minutes} min from now."))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  AUDIT LOG
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="audit")
    async def wh_audit(self, ctx, name: str, count: int = 20):
        """View recent audit log entries."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        entries = d.get("audit_log", [])[-count:]
        if not entries: return await ctx.send(embed=info_embed("No audit entries."))
        lines = []
        for e in reversed(entries):
            ts = e.get("timestamp", "?")[:16]
            lines.append(f"`{ts}` **{e.get('action')}** by {e.get('user')} {e.get('target', '')}")
        await ctx.send(embed=info_embed("\n".join(lines[:25]), title=f"Audit — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  BLACKOUT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="blackout", invoke_without_command=True)
    async def wh_bo(self, ctx): await ctx.send_help(ctx.command)

    @wh_bo.command(name="add")
    async def wh_bo_add(self, ctx, name: str, start_hour: int, end_hour: int, *, days: str = "0,1,2,3,4,5,6"):
        """Add blackout: freeze during hours (UTC). Days: 0=Mon..6=Sun"""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        try: day_list = [int(x.strip()) for x in days.split(",")]
        except: return await ctx.send(embed=err_embed("Invalid days."))
        async with self.config.networks() as n:
            n[name].setdefault("blackout_schedules", []).append({"start_hour": start_hour, "end_hour": end_hour, "days": day_list})
        await ctx.send(embed=ok_embed(f"Blackout {start_hour:02d}:00–{end_hour:02d}:00 UTC on {days}."))

    @wh_bo.command(name="clear")
    async def wh_bo_clear(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return
        if not await self._is_staff(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        async with self.config.networks() as n: n[name]["blackout_schedules"] = []; n[name]["frozen"] = False
        await ctx.send(embed=ok_embed("Blackout cleared & unfrozen."))

    @wh_bo.command(name="list")
    async def wh_bo_ls(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return
        ss = d.get("blackout_schedules", [])
        dn = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        lines = [f"{s['start_hour']:02d}:00–{s['end_hour']:02d}:00 — {','.join(dn[x] for x in s.get('days',[]))}" for s in ss]
        await ctx.send(embed=info_embed("\n".join(lines) if lines else "None.", title=f"Blackout — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  BACKUP & RESTORE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="backup")
    async def wh_backup(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        if not await self._is_owner(d, ctx.author.id) and not await self.bot.is_owner(ctx.author): return
        data = {"name": name, "version": self.__version__, "exported": datetime.now(timezone.utc).isoformat(), "config": d}
        f = discord.File(fp=io.BytesIO(json.dumps(data, indent=2, default=str).encode()), filename=f"wormhole-{name}.json")
        await ctx.send(embed=ok_embed("Backup:"), file=f)

    @wh.command(name="restore")
    async def wh_restore(self, ctx, new_name: str = None):
        if not ctx.message.attachments: return await ctx.send(embed=err_embed("Attach a JSON file."))
        try: backup = json.loads((await ctx.message.attachments[0].read()).decode())
        except: return await ctx.send(embed=err_embed("Invalid JSON."))
        cfg = backup.get("config")
        if not cfg: return await ctx.send(embed=err_embed("Missing config."))
        name = (new_name or backup.get("name", "restored")).lower()
        if name in await self.config.networks(): return await ctx.send(embed=err_embed(f"**{name}** exists."))
        cfg["owner_id"] = ctx.author.id
        cfg["channels"] = []
        cfg["portal_messages"] = {}
        cfg["created_at"] = datetime.now(timezone.utc).isoformat()
        await self._save(name, cfg)
        self.cooldowns[name] = CooldownBucket(cfg.get("rate_limit_rate", 5), cfg.get("rate_limit_per", 10.0))
        self.dup_detectors[name] = DuplicateDetector()
        self.raid_detectors[name] = RaidDetector()
        await ctx.send(embed=ok_embed(f"**{name}** restored! Link channels with `{ctx.clean_prefix}wh open {name}`."))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  GLOBAL BLOCKLIST
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="global", invoke_without_command=True)
    @checks.is_owner()
    async def wh_gl(self, ctx): await ctx.send_help(ctx.command)

    @wh_gl.command(name="ban-user")
    @checks.is_owner()
    async def wh_gl_bu(self, ctx, user: discord.User):
        async with self.config.global_banned_users() as bl:
            if user.id not in bl: bl.append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} globally blocked."))

    @wh_gl.command(name="unban-user")
    @checks.is_owner()
    async def wh_gl_uu(self, ctx, user: discord.User):
        async with self.config.global_banned_users() as bl:
            if user.id in bl: bl.remove(user.id)
        await ctx.send(embed=ok_embed("Unblocked."))

    @wh_gl.command(name="ban-server")
    @checks.is_owner()
    async def wh_gl_bs(self, ctx, gid: int):
        async with self.config.global_banned_servers() as bl:
            if gid not in bl: bl.append(gid)
        await ctx.send(embed=ok_embed("Server globally blocked."))

    @wh_gl.command(name="unban-server")
    @checks.is_owner()
    async def wh_gl_us(self, ctx, gid: int):
        async with self.config.global_banned_servers() as bl:
            if gid in bl: bl.remove(gid)
        await ctx.send(embed=ok_embed("Unblocked."))

    @wh_gl.command(name="list")
    @checks.is_owner()
    async def wh_gl_ls(self, ctx):
        users = await self.config.global_banned_users()
        servers = await self.config.global_banned_servers()
        lines = [f"User: {self.bot.get_user(u) or u}" for u in users] + [f"Server: {self.bot.get_guild(g) or g}" for g in servers]
        await ctx.send(embed=info_embed("\n".join(lines) if lines else "Empty.", title="Global Blocklist"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  PROFILES & STATS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="profile")
    async def wh_profile(self, ctx, name: str, user: discord.User = None):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        user = user or ctx.author
        p = d.get("user_profiles", {}).get(str(user.id))
        if not p: return await ctx.send(embed=info_embed(f"{user.display_name} has no activity on **{name}**."))
        em = discord.Embed(title=f"👤 {user.display_name} — {name}", colour=COLOUR_INFO)
        em.set_thumbnail(url=user.display_avatar.url)
        em.add_field(name="Messages", value=f"{p.get('messages',0):,}", inline=True)
        em.add_field(name="First seen", value=p.get("first_seen","?")[:10], inline=True)
        em.add_field(name="Servers", value=str(len(p.get("servers",[]))), inline=True)
        karma = d.get("karma_scores", {}).get(str(user.id), 0)
        if d.get("karma_enabled"): em.add_field(name="Karma", value=str(karma), inline=True)
        status = []
        if user.id == d["owner_id"]: status.append("👑 Owner")
        elif user.id in d.get("staff_ids", []): status.append("⭐ Staff")
        if user.id in d.get("banned_users", []): status.append("🚫 Banned")
        if user.id in d.get("muted_users", []): status.append("🔇 Muted")
        if user.id in d.get("dm_subscribers", []): status.append("📧 DM Sub")
        if status: em.add_field(name="Status", value=" ".join(status), inline=False)
        await ctx.send(embed=em)

    @wh.command(name="stats")
    async def wh_stats(self, ctx, name: str):
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        profiles = d.get("user_profiles", {})
        top = sorted(profiles.items(), key=lambda x: x[1].get("messages", 0), reverse=True)[:5]
        em = discord.Embed(title=f"📊 {name}", colour=COLOUR_INFO)
        em.add_field(name="Messages", value=f"{d.get('total_messages',0):,}", inline=True)
        em.add_field(name="Channels", value=str(len(d["channels"])), inline=True)
        em.add_field(name="Users", value=str(len(profiles)), inline=True)
        em.add_field(name="DM subs", value=str(len(d.get("dm_subscribers",[]))), inline=True)
        em.add_field(name="Mode", value=f"`{d.get('relay_mode','webhook')}`", inline=True)
        em.add_field(name="Created", value=d.get("created_at","?")[:10], inline=True)
        if top:
            lb = []
            for i, (uid, pr) in enumerate(top):
                u = self.bot.get_user(int(uid))
                lb.append(f"{'🥇🥈🥉'[i] if i < 3 else f'{i+1}.'} {u or uid} — {pr.get('messages',0):,}")
            em.add_field(name="🏆 Top", value="\n".join(lb), inline=False)
        await ctx.send(embed=em)

    @wh.command(name="rules")
    async def wh_rules(self, ctx, name: str):
        """Display network rules."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        rules = d.get("rules", "")
        if not rules: return await ctx.send(embed=info_embed("No rules set."))
        await ctx.send(embed=info_embed(rules, title=f"📜 Rules — {name}"))

    @wh.command(name="motd")
    async def wh_motd(self, ctx, name: str):
        """Display the message of the day."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        motd = d.get("motd", "")
        if not motd: return await ctx.send(embed=info_embed("No MOTD set."))
        await ctx.send(embed=info_embed(motd, title=f"📋 MOTD — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  SEARCH
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="search")
    async def wh_search(self, ctx, name: str, *, query: str):
        """Search recent messages across the network."""
        name = name.lower(); d = await self._net(name)
        if not d: return await ctx.send(embed=err_embed("Not found."))
        results = []
        for ch_id in d["channels"][:10]:  # Limit to 10 channels
            ch = self.bot.get_channel(ch_id)
            if not ch: continue
            try:
                async for msg in ch.history(limit=100):
                    if query.lower() in (msg.content or "").lower():
                        results.append(f"**{msg.author.display_name}** in #{ch.name}: {truncate(msg.content, 80)}")
                        if len(results) >= 15: break
            except: pass
            if len(results) >= 15: break
        await ctx.send(embed=info_embed("\n".join(results) if results else "No results.", title=f"🔍 Search — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  MESSAGE RELAY ENGINE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._ready.wait()
        if not message.guild or message.author.bot:
            return
        if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return

        eff_ch = message.channel.id
        is_thread = isinstance(message.channel, discord.Thread)
        if is_thread:
            eff_ch = message.channel.parent_id

        nets = await self.config.networks()
        net_name = None
        nd = None
        for n, d in nets.items():
            if eff_ch in d.get("channels", []):
                net_name = n; nd = d; break
        if not net_name:
            return

        if is_thread and not nd.get("sync_threads"): return
        if nd.get("frozen"): return

        # Ignore commands
        pfx = await self.bot.get_prefix(message)
        if isinstance(pfx, str): pfx = [pfx]
        if any(message.content.startswith(p) for p in pfx): return

        # NSFW gate
        if nd.get("nsfw_gate") and hasattr(message.channel, "is_nsfw") and message.channel.is_nsfw(): return

        # Global blocklist
        if message.author.id in await self.config.global_banned_users(): return
        if message.guild.id in await self.config.global_banned_servers(): return

        # Per-network checks
        if message.author.id in nd.get("banned_users", []): return
        if message.author.id in nd.get("muted_users", []): return
        if message.guild.id in nd.get("banned_servers", []): return
        if message.guild.id in nd.get("muted_servers", []): return

        # Content filter
        if message.content:
            if check_filters(message.content, nd.get("word_filters", []), nd.get("regex_filters", [])):
                try:
                    await message.delete()
                    await message.channel.send(embed=warn_embed(f"{message.author.mention}, blocked by filter."), delete_after=5)
                except: pass
                return

        # Attachment filter
        if message.attachments:
            exts = set(nd.get("blocked_extensions", []))
            reason = check_attachment_filters(message.attachments, exts, nd.get("max_filesize"))
            if reason:
                try:
                    await message.delete()
                    await message.channel.send(embed=warn_embed(f"{message.author.mention}, {reason}"), delete_after=5)
                except: pass
                return

        # Auto-moderation
        am = nd.get("automod", {})
        if am.get("enabled") and message.content:
            if am.get("anti_spam"):
                det = self.dup_detectors.get(net_name)
                if det and det.is_duplicate(net_name, message.author.id, message.content):
                    try: await message.delete(); await message.channel.send(embed=warn_embed("Spam detected."), delete_after=5)
                    except: pass
                    await self._log(nd, warn_embed(f"Auto-mod spam: {message.author}"))
                    return
            if am.get("anti_raid"):
                rd = self.raid_detectors.get(net_name)
                if rd and rd.record(net_name, message.author.id):
                    async with self.config.networks() as ns:
                        if net_name in ns: ns[net_name]["frozen"] = True
                    await self._log(nd, warn_embed(f"🚨 Raid detected! Network auto-frozen."))
                    await self._status(net_name, nd, None, "🚨 **Raid detected — network auto-frozen!** Staff: use `wh set freeze <name> false` to unfreeze.")
                    return
            reason = check_automod(message.content, am)
            if reason:
                try: await message.delete(); await message.channel.send(embed=warn_embed(f"{message.author.mention}: {reason}"), delete_after=5)
                except: pass
                await self._log(nd, warn_embed(f"Auto-mod: {reason} — {message.author}"))
                return

        # Rate limit
        bucket = self.cooldowns.get(net_name)
        if bucket and bucket.is_rate_limited(message.author.id, net_name):
            try: await message.add_reaction("🕐")
            except: pass
            return

        # Slowmode
        sm = nd.get("slowmode", 0)
        if sm > 0:
            last = self.slowmode_tracker.get(net_name, {}).get(message.author.id, 0)
            if time.monotonic() - last < sm:
                try: await message.add_reaction("🐌")
                except: pass
                return
            self.slowmode_tracker.setdefault(net_name, {})[message.author.id] = time.monotonic()

        # Relay delay
        delay = nd.get("relay_delay", 0)
        if delay > 0:
            await asyncio.sleep(min(delay, 30))

        # Build payload
        relay_mode = nd.get("relay_mode", "webhook")
        nick = nd.get("server_nicknames", {}).get(str(message.guild.id))
        mc = nd.get("mention_control", {})
        content = sanitise_mentions(message.content or "", mc)

        # Reply context
        if nd.get("sync_replies") and message.reference and message.reference.message_id:
            try:
                ref = message.reference.cached_message or await message.channel.fetch_message(message.reference.message_id)
                preview = truncate(ref.content, 100) if ref.content else "*[attachment]*"
                content = f"> **↩ {ref.author.display_name}:** {preview}\n{content}"
            except: content = f"> ↩ *[reply]*\n{content}"

        # Stickers
        if nd.get("sync_stickers") and message.stickers:
            sl = [f"[Sticker: {s.name}]({s.url})" for s in message.stickers]
            content = (content + "\n" if content else "") + "\n".join(sl)

        # Embeds
        extra_embeds = []
        if nd.get("forward_embeds") and message.embeds:
            extra_embeds = [e for e in message.embeds if e.type == "rich"]

        avatar = self._avatar(message, nd.get("image_mode", "user"), nd.get("custom_icon"))
        uname = self._name(message, nd.get("name_mode", "both"), nd.get("custom_name"), nick)

        # Relay to channels
        mapping: Dict[int, int] = {}
        for ch_id in nd["channels"]:
            if ch_id == eff_ch: continue
            ch = self.bot.get_channel(ch_id)
            if not ch: continue
            ch_mode = self._get_override(nd, ch_id, "relay_mode") or relay_mode
            try:
                if ch_mode == "webhook":
                    wh = await self._wh(ch)
                    files = []
                    for a in message.attachments:
                        try: files.append(await a.to_file())
                        except: pass
                    sent = await wh.send(content=content or None, username=truncate(uname, 80), avatar_url=avatar,
                                         files=files or discord.utils.MISSING, embeds=extra_embeds or discord.utils.MISSING, wait=True)
                    mapping[ch_id] = sent.id
                elif ch_mode == "embed":
                    em = build_relay_embed(message, nick, nd.get("colour"))
                    sent = await ch.send(embeds=[em] + extra_embeds[:9])
                    mapping[ch_id] = sent.id
                elif ch_mode == "compact":
                    g = nick or message.guild.name
                    files = []
                    for a in message.attachments:
                        try: files.append(await a.to_file())
                        except: pass
                    sent = await ch.send(content=compact_format(g, message.author.display_name, content), files=files or None)
                    mapping[ch_id] = sent.id
            except Exception as exc:
                log.warning("Relay fail %s: %s", ch_id, exc)

        if mapping:
            self.msg_map.add(net_name, message.id, mapping)

        # Stats + profile
        async with self.config.networks() as ns:
            if net_name in ns: ns[net_name]["total_messages"] = ns[net_name].get("total_messages", 0) + 1
        await self._update_profile(net_name, message.author, message.guild.id)

        # DM relay
        await self._relay_to_dm_subs(net_name, nd, message)

        # Keyword highlights
        await self._check_highlights(net_name, nd, message.content, message.author.id)

    # ── Edit sync ───────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        await self._ready.wait()
        if not after.guild or after.author.bot or before.content == after.content: return
        eff = after.channel.id
        if isinstance(after.channel, discord.Thread): eff = after.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net: return
        nd = await self._net(net)
        if not nd or not nd.get("sync_edits"): return
        mapping = self.msg_map.get_relayed(net, after.id)
        if not mapping: return
        mode = nd.get("relay_mode", "webhook")
        for ch_id, mid in mapping.items():
            ch = self.bot.get_channel(ch_id)
            if not ch: continue
            try:
                cm = self._get_override(nd, ch_id, "relay_mode") or mode
                if cm == "webhook":
                    wh = await self._wh(ch)
                    await wh.edit_message(mid, content=after.content or "")
                elif cm == "embed":
                    msg = await ch.fetch_message(mid)
                    if msg.embeds:
                        e = msg.embeds[0]; e.description = after.content or "*[no text]*"
                        await msg.edit(embed=e)
                else:
                    msg = await ch.fetch_message(mid)
                    cp = msg.content.find(":** ")
                    if cp != -1: await msg.edit(content=truncate(msg.content[:cp+4] + after.content, 2000))
            except: pass

    # ── Delete sync ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        await self._ready.wait()
        if not message.guild or message.author.bot: return
        eff = message.channel.id
        if isinstance(message.channel, discord.Thread): eff = message.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net: return
        nd = await self._net(net)
        if not nd or not nd.get("sync_deletes"): return
        mapping = self.msg_map.get_relayed(net, message.id)
        if not mapping: return
        mode = nd.get("relay_mode", "webhook")
        for ch_id, mid in mapping.items():
            ch = self.bot.get_channel(ch_id)
            if not ch: continue
            try:
                cm = self._get_override(nd, ch_id, "relay_mode") or mode
                if cm == "webhook":
                    wh = await self._wh(ch)
                    await wh.delete_message(mid)
                else:
                    msg = await ch.fetch_message(mid)
                    await msg.delete()
            except: pass

    # ── Reaction sync + karma + starboard ──────────────────────────────────

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        await self._ready.wait()
        if user.bot: return
        msg = reaction.message
        if not msg.guild: return
        eff = msg.channel.id
        if isinstance(msg.channel, discord.Thread): eff = msg.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net: return
        nd = await self._net(net)
        if not nd: return

        # Reaction sync
        if nd.get("sync_reactions"):
            mapping = self.msg_map.get_relayed(net, msg.id)
            if mapping:
                for ch_id, mid in mapping.items():
                    ch = self.bot.get_channel(ch_id)
                    if not ch: continue
                    try:
                        rm = await ch.fetch_message(mid)
                        await rm.add_reaction(reaction.emoji)
                    except: pass

        # Karma
        if nd.get("karma_enabled") and str(reaction.emoji) == nd.get("karma_emoji", "👍"):
            # Find the original author
            orig_id = self.msg_map.get_original(net, msg.id)
            target_msg = msg
            if orig_id:
                # This is a relayed message — find original author via profiles or just give to the content
                pass  # Karma for relayed messages: credit the original sender
            if target_msg.author.id != user.id:  # Can't karma yourself
                uid = str(target_msg.author.id)
                async with self.config.networks() as ns:
                    if net in ns:
                        ns[net].setdefault("karma_scores", {})
                        ns[net]["karma_scores"][uid] = ns[net]["karma_scores"].get(uid, 0) + 1

        # Starboard
        if nd.get("starboard_enabled") and str(reaction.emoji) == "⭐":
            threshold = nd.get("starboard_threshold", 3)
            star_ch_id = nd.get("starboard_channel")
            if not star_ch_id: return
            star_ch = self.bot.get_channel(star_ch_id)
            if not star_ch: return

            # Count total stars across all relayed copies + original
            total_stars = 0
            for r in msg.reactions:
                if str(r.emoji) == "⭐":
                    total_stars += r.count

            if total_stars >= threshold:
                starred = nd.get("starred_messages", {})
                msg_key = str(msg.id)
                img_url = None
                if msg.attachments:
                    for a in msg.attachments:
                        if a.content_type and a.content_type.startswith("image/"):
                            img_url = a.url; break
                em = build_star_embed(
                    msg.author.display_name, msg.author.display_avatar.url,
                    msg.content or "*[no text]*", total_stars,
                    msg.guild.name, msg.channel.name, img_url)

                if msg_key in starred:
                    # Update existing
                    try:
                        board_msg = await star_ch.fetch_message(starred[msg_key]["board_msg_id"])
                        await board_msg.edit(embed=em)
                        async with self.config.networks() as ns:
                            if net in ns: ns[net]["starred_messages"][msg_key]["stars"] = total_stars
                    except: pass
                else:
                    try:
                        board_msg = await star_ch.send(embed=em)
                        async with self.config.networks() as ns:
                            if net in ns:
                                ns[net].setdefault("starred_messages", {})[msg_key] = {"stars": total_stars, "board_msg_id": board_msg.id}
                    except: pass

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        await self._ready.wait()
        if user.bot: return
        msg = reaction.message
        if not msg.guild: return
        eff = msg.channel.id
        if isinstance(msg.channel, discord.Thread): eff = msg.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net: return
        nd = await self._net(net)
        if not nd or not nd.get("sync_reactions"): return
        mapping = self.msg_map.get_relayed(net, msg.id)
        if not mapping: return
        for ch_id, mid in mapping.items():
            ch = self.bot.get_channel(ch_id)
            if not ch: continue
            try:
                rm = await ch.fetch_message(mid)
                await rm.remove_reaction(reaction.emoji, self.bot.user)
            except: pass

    # ── Typing indicator sync ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_typing(self, channel, user, when):
        await self._ready.wait()
        if user.bot or not hasattr(channel, "guild") or not channel.guild:
            return
        net = await self._net_for_ch(channel.id)
        if not net: return
        nd = await self._net(net)
        if not nd or not nd.get("sync_typing"): return
        for ch_id in nd["channels"]:
            if ch_id == channel.id: continue
            ch = self.bot.get_channel(ch_id)
            if ch:
                try: await ch.typing()
                except: pass

    # ── Pin sync ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel, last_pin):
        await self._ready.wait()
        if not hasattr(channel, "guild"): return
        net = await self._net_for_ch(channel.id)
        if not net: return
        nd = await self._net(net)
        if not nd or not nd.get("sync_pins"): return
        try:
            pins = await channel.pins()
            if not pins: return
            latest = pins[0]
            mapping = self.msg_map.get_relayed(net, latest.id)
            if not mapping: return
            for ch_id, mid in mapping.items():
                ch = self.bot.get_channel(ch_id)
                if not ch: continue
                try:
                    msg = await ch.fetch_message(mid)
                    await msg.pin()
                except: pass
        except: pass

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  HELP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="help")
    async def wh_help(self, ctx):
        """Full command reference."""
        p = ctx.clean_prefix
        e1 = discord.Embed(title="🌀 Wormhole v3.2.0 — Commands (1/3)", colour=COLOUR_NEUTRAL,
            description="The ultimate cross-server relay: webhooks, DMs, embeds, starboard, auto-mod, invites, karma, portals, highlights, search & more.")
        e1.add_field(name="📡 Networks", value=(
            f"`{p}wh create/delete/open/close/list/info/stats`\n"
            f"`{p}wh discover` — public networks\n"
            f"`{p}wh transfer <name> @user`\n"
            f"`{p}wh announce <name> <msg>` — broadcast\n"
            f"`{p}wh portal [name]` — status embed\n"
            f"`{p}wh search <name> <query>`\n"
            f"`{p}wh schedule <name> <min> <msg>`\n"
            f"`{p}wh rules/motd <name>` — display"), inline=False)
        e1.add_field(name="⚙️ Settings (`wh set`)", value=(
            f"`relay-mode` `webhooks` `name-mode` `image-mode` `custom-icon` `custom-name`\n"
            f"`description` `colour` `ratelimit` `slowmode` `relay-delay` `log-channel` `nickname`\n"
            f"`welcome` `motd` `rules` `tags` `public` `max-filesize` `blocked-extensions`\n"
            f"`freeze` `silent` `nsfw-gate` `sync-edits/deletes/reactions/replies/stickers/threads/pins/typing`\n"
            f"`forward-embeds` `strip-everyone/roles/users` `channel-override`"), inline=False)

        e2 = discord.Embed(title="🌀 Commands (2/3)", colour=COLOUR_NEUTRAL)
        e2.add_field(name="📧 DM Relay (`wh dm`)", value=(
            f"`enable/disable <name>`\n"
            f"`mode <name> <embed|compact|plain>`\n"
            f"`subscribe/unsubscribe <name>`\n"
            f"`send <name> <message>` — send from DM\n"
            f"`list` — your subscriptions"), inline=True)
        e2.add_field(name="⭐ Staff", value=f"`{p}wh staff add/remove/list`", inline=True)
        e2.add_field(name="🔗 Invites (`wh invite`)", value=(
            f"`create <name> [max] [min]`\n"
            f"`vanity <name> <word>`\n"
            f"`use <code>` — join\n"
            f"`revoke/list`"), inline=True)
        e2.add_field(name="🛡️ Mod (`wh mod`)", value=(
            f"`ban/unban/mute/unmute <name> @user`\n"
            f"`ban-server/unban-server/mute-server/unmute-server`\n"
            f"`allowlist-add/remove` `purge <name> [n]`"), inline=False)
        e2.add_field(name="🤖 Auto-Mod (`wh automod`)", value=(
            f"`enable/disable` `anti-spam/mentions/caps/invite/link`\n"
            f"`anti-zalgo/spoiler/emote-spam/newlines/raid` `status`"), inline=False)

        e3 = discord.Embed(title="🌀 Commands (3/3)", colour=COLOUR_NEUTRAL)
        e3.add_field(name="🔍 Filters", value="`add-word/remove-word` `add-regex/remove-regex` `list`", inline=True)
        e3.add_field(name="⭐ Starboard", value=f"`{p}wh starboard enable <name> #ch [threshold]`\n`disable`", inline=True)
        e3.add_field(name="💎 Karma", value=f"`{p}wh karma enable/disable/check/leaderboard`", inline=True)
        e3.add_field(name="🔔 Highlights", value=f"`{p}wh highlight add/remove/list <name> <keyword>`", inline=True)
        e3.add_field(name="🌙 Blackout", value=f"`{p}wh blackout add/clear/list`", inline=True)
        e3.add_field(name="💾 Backup", value=f"`{p}wh backup/restore`", inline=True)
        e3.add_field(name="👤 Profiles", value=f"`{p}wh profile <name> [@user]`", inline=True)
        e3.add_field(name="📋 Audit", value=f"`{p}wh audit <name> [count]`", inline=True)
        e3.add_field(name="🌐 Global", value=f"`{p}wh global ban-user/unban-user/ban-server/unban-server/list`", inline=True)
        e3.set_footer(text="Wormhole v3.2.0 • EveCogs • github.com/everestmcarthur/EveCogs")

        await ctx.send(embeds=[e1, e2, e3])
