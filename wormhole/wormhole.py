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
        self._startup_task = asyncio.ensure_future(self._init())

    async def _init(self):
        try:
            await self.bot.wait_until_ready()
            networks = await self.config.networks()
            for name, data in networks.items():
                self.cooldowns[name] = CooldownBucket(data.get("rate_limit_rate", 5), data.get("rate_limit_per", 10.0))
                am = data.get("automod", {})
                self.dup_detectors[name] = DuplicateDetector(am.get("spam_window", 30.0), am.get("spam_threshold", 3))
                self.raid_detectors[name] = RaidDetector(am.get("raid_window", 60.0), am.get("raid_threshold", 10))
            self._bg_tasks.append(asyncio.ensure_future(self._blackout_loop()))
            self._bg_tasks.append(asyncio.ensure_future(self._portal_update_loop()))
            self._bg_tasks.append(asyncio.ensure_future(self._scheduled_msg_loop()))
            log.info("Wormhole v3.2.0 ready — %d networks loaded.", len(networks))
        except Exception as exc:
            log.error("Wormhole init error (relay will still work): %s", exc, exc_info=True)
        finally:
            # ALWAYS set ready so the relay isn't permanently stuck
            self._ready.set()

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

    async def _wh(self, ch: discord.TextChannel, *, force_refresh: bool = False) -> discord.Webhook:
        if not force_refresh and ch.id in self.webhook_cache:
            return self.webhook_cache[ch.id]
        try:
            for w in await ch.webhooks():
                if w.user and w.user.id == self.bot.user.id and w.name == "Wormhole Relay":
                    self.webhook_cache[ch.id] = w
                    return w
            w = await ch.create_webhook(name="Wormhole Relay")
            self.webhook_cache[ch.id] = w
            return w
        except discord.Forbidden:
            self.webhook_cache.pop(ch.id, None)
            raise
        except Exception:
            self.webhook_cache.pop(ch.id, None)
            raise

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

    # ━━━━━━━━━━━━━━━━━━━━━━�