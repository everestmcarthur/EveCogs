"""
Wormhole — Advanced Cross-Server Relay Cog for Red-DiscordBot
==============================================================

Features
--------
• Named wormhole networks with full per-network config
• Webhook relay with custom avatar/name modes (user, server, both, custom)
• Message-edit, message-delete, reply, reaction, thread & sticker sync
• Staff system — owner + staff per network with granular perms
• Moderation — user ban/mute, server ban, word filter, regex filter
• Rate limiting (token-bucket per user per network)
• Per-network logging channel
• Statistics dashboard (messages relayed, top users, top servers)
• Server allowlist / blocklist per network
• NSFW gating, freeze/pause, silent mode
• Custom network icon, description, colour
• Nickname overrides per server
• Transfer network ownership
• Full help embeds
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

from .utils import (
    COLOUR_INFO,
    COLOUR_NEUTRAL,
    COLOUR_OK,
    CooldownBucket,
    check_filters,
    err_embed,
    human_timedelta,
    info_embed,
    ok_embed,
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
    "channels": [],  # list of channel IDs
    # identity
    "use_webhooks": True,
    "image_mode": "user",       # user | server | custom
    "name_mode": "both",        # user | server | both | custom
    "custom_icon": None,        # URL
    "custom_name": None,        # fallback name template
    "colour": None,             # hex int for embed accent
    "description": "",
    # moderation
    "banned_users": [],         # user IDs
    "banned_servers": [],       # guild IDs
    "muted_users": [],          # user IDs
    "muted_servers": [],        # guild IDs
    "word_filters": [],
    "regex_filters": [],
    "allowlist_servers": [],    # if non-empty only these guilds may join
    # features
    "sync_edits": True,
    "sync_deletes": True,
    "sync_reactions": True,
    "sync_replies": True,
    "sync_threads": False,
    "sync_stickers": True,
    "forward_embeds": True,
    "nsfw_gate": True,          # block NSFW channel content relay
    "silent": False,            # suppress join/leave announcements
    "frozen": False,            # pause all relay
    # rate limit
    "rate_limit_rate": 5,       # messages
    "rate_limit_per": 10.0,     # seconds
    # logging
    "log_channel": None,
    # server nicknames  {guild_id_str: "nickname"}
    "server_nicknames": {},
    # stats
    "total_messages": 0,
    "created_at": None,         # ISO timestamp
}

_DEFAULT_GLOBAL = {
    "networks": {},             # {network_name: _DEFAULT_NETWORK}
    "max_networks_per_user": 10,
}

# message map: stores {original_msg_id: {channel_id: relayed_msg_id}}
# Kept in memory only (not persisted — too noisy).  Evicts after 2 000 entries.
_MAP_LIMIT = 2_000


class _MessageMap:
    """In-memory bidirectional message-ID mapping per network."""

    def __init__(self):
        # network -> original_msg_id -> {channel_id: relayed_msg_id}
        self.forward: Dict[str, Dict[int, Dict[int, int]]] = defaultdict(dict)
        # network -> relayed_msg_id -> original_msg_id
        self.reverse: Dict[str, Dict[int, int]] = defaultdict(dict)
        self._order: Dict[str, list] = defaultdict(list)

    def add(self, network: str, original_id: int, mapping: Dict[int, int]):
        self.forward[network][original_id] = mapping
        for ch_id, msg_id in mapping.items():
            self.reverse[network][msg_id] = original_id
        self._order[network].append(original_id)
        # Evict
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
    """Advanced cross-server relay with networks, moderation & full sync."""

    __version__ = "3.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7730187301, force_registration=True)
        self.config.register_global(**_DEFAULT_GLOBAL)

        self.webhook_cache: Dict[int, discord.Webhook] = {}
        self.cooldowns: Dict[str, CooldownBucket] = {}  # per network
        self.msg_map = _MessageMap()

        self._ready = asyncio.Event()
        self._startup_task = self.bot.loop.create_task(self._init())

    async def _init(self):
        await self.bot.wait_until_ready()
        # Warm cooldown buckets
        networks = await self.config.networks()
        for name, data in networks.items():
            self.cooldowns[name] = CooldownBucket(
                data.get("rate_limit_rate", 5),
                data.get("rate_limit_per", 10.0),
            )
        self._ready.set()
        log.info("Wormhole cog ready — %d networks loaded.", len(networks))

    async def cog_unload(self):
        self._startup_task.cancel()
        # Clean up webhooks we created? No — leave them for next load.

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _get_network(self, name: str) -> Optional[dict]:
        networks = await self.config.networks()
        return networks.get(name)

    async def _save_network(self, name: str, data: dict):
        async with self.config.networks() as networks:
            networks[name] = data

    async def _network_for_channel(self, channel_id: int) -> Optional[str]:
        """Return the network name a channel belongs to, or None."""
        networks = await self.config.networks()
        for name, data in networks.items():
            if channel_id in data.get("channels", []):
                return name
        return None

    async def _get_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        if channel.id in self.webhook_cache:
            # Validate it's still alive
            try:
                return self.webhook_cache[channel.id]
            except Exception:
                pass
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.user == self.bot.user and wh.name == "Wormhole Relay":
                    self.webhook_cache[channel.id] = wh
                    return wh
            wh = await channel.create_webhook(name="Wormhole Relay")
            self.webhook_cache[channel.id] = wh
            return wh
        except discord.Forbidden:
            raise commands.UserFeedbackCheckFailure(
                "I don't have permission to manage webhooks in that channel."
            )

    def _resolve_avatar(self, message: discord.Message, mode: str, custom_icon: Optional[str]) -> str:
        if mode == "server":
            icon = message.guild.icon
            return icon.url if icon else (message.author.display_avatar.url)
        if mode == "custom" and custom_icon:
            return custom_icon
        return message.author.display_avatar.url

    def _resolve_name(
        self, message: discord.Message, mode: str, custom_name: Optional[str],
        server_nick: Optional[str] = None,
    ) -> str:
        guild_label = server_nick or message.guild.name
        user_label = message.author.display_name
        if mode == "server":
            return guild_label
        if mode == "both":
            return f"{guild_label} • {user_label}"
        if mode == "custom" and custom_name:
            return custom_name.replace("{user}", user_label).replace("{server}", guild_label)
        return user_label  # default "user"

    async def _is_staff(self, network_data: dict, user_id: int) -> bool:
        return user_id == network_data["owner_id"] or user_id in network_data.get("staff_ids", [])

    async def _is_owner(self, network_data: dict, user_id: int) -> bool:
        return user_id == network_data["owner_id"]

    async def _log_event(self, network_data: dict, embed: discord.Embed):
        ch_id = network_data.get("log_channel")
        if not ch_id:
            return
        ch = self.bot.get_channel(ch_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

    async def _relay_status(self, network_name: str, network_data: dict, source_channel: discord.Channel, text: str):
        """Send a status/announcement embed to every channel in the network except source."""
        if network_data.get("silent"):
            return
        em = info_embed(text, title=f"🌀 {network_name}")
        for ch_id in network_data["channels"]:
            if ch_id == source_channel.id:
                continue
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=em)
                except Exception:
                    pass

    # ── Main group ──────────────────────────────────────────────────────────

    @commands.group(name="wh", aliases=["wormhole"], invoke_without_command=True)
    async def wh(self, ctx: commands.Context):
        """🌀 Wormhole — advanced cross-server relay.

        Use `[p]wh help` for the full command list.
        """
        await ctx.send_help(ctx.command)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  NETWORK MANAGEMENT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="create")
    async def wh_create(self, ctx: commands.Context, name: str, *, description: str = ""):
        """Create a new wormhole network.

        **name** must be alphanumeric + hyphens, max 32 chars.
        """
        name = name.lower().strip()
        if not name.replace("-", "").replace("_", "").isalnum() or len(name) > 32:
            return await ctx.send(embed=err_embed("Network name must be alphanumeric (hyphens/underscores OK), max 32 chars."))

        networks = await self.config.networks()
        if name in networks:
            return await ctx.send(embed=err_embed(f"Network **{name}** already exists."))

        max_nets = await self.config.max_networks_per_user()
        owned = sum(1 for n in networks.values() if n["owner_id"] == ctx.author.id)
        if owned >= max_nets:
            return await ctx.send(embed=err_embed(f"You already own {owned}/{max_nets} networks."))

        data = deepcopy(_DEFAULT_NETWORK)
        data["owner_id"] = ctx.author.id
        data["description"] = description
        data["created_at"] = datetime.now(timezone.utc).isoformat()

        await self._save_network(name, data)
        self.cooldowns[name] = CooldownBucket(data["rate_limit_rate"], data["rate_limit_per"])

        em = ok_embed(
            f"Network **{name}** created!\n\n"
            f"• Add channels: `{ctx.clean_prefix}wh open {name}`\n"
            f"• Customise: `{ctx.clean_prefix}wh set {name} <option> <value>`\n"
            f"• Add staff: `{ctx.clean_prefix}wh staff add {name} @user`",
            title="🌀 Network Created",
        )
        await ctx.send(embed=em)

    @wh.command(name="delete")
    async def wh_delete(self, ctx: commands.Context, name: str):
        """Delete a network you own. Requires confirmation."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_owner(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Only the network owner (or bot owner) can delete a network."))

        await ctx.send(embed=warn_embed(f"Type **`yes`** within 30 s to permanently delete **{name}** and unlink all channels."))

        def pred(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "yes"

        try:
            await self.bot.wait_for("message", check=pred, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send(embed=info_embed("Deletion cancelled — timed out."))

        async with self.config.networks() as networks:
            networks.pop(name, None)
        self.cooldowns.pop(name, None)
        await ctx.send(embed=ok_embed(f"Network **{name}** has been deleted."))

    @wh.command(name="open")
    @commands.guild_only()
    async def wh_open(self, ctx: commands.Context, name: str):
        """Link the current channel to a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found. Create one with `{ctx.clean_prefix}wh create {name}`."))

        # Allowlist check
        if data.get("allowlist_servers") and ctx.guild.id not in data["allowlist_servers"]:
            return await ctx.send(embed=err_embed("This server is not on the network's allowlist."))
        # Banned server check
        if ctx.guild.id in data.get("banned_servers", []):
            return await ctx.send(embed=err_embed("This server is banned from the network."))

        if ctx.channel.id in data["channels"]:
            return await ctx.send(embed=err_embed("This channel is already linked to that network."))

        # Check channel isn't already in another network
        existing = await self._network_for_channel(ctx.channel.id)
        if existing:
            return await ctx.send(embed=err_embed(f"This channel is already linked to **{existing}**. Close it first."))

        async with self.config.networks() as networks:
            networks[name]["channels"].append(ctx.channel.id)
            data = networks[name]

        await ctx.send(embed=ok_embed(f"This channel is now linked to **{name}**. Messages will relay across {len(data['channels'])} channel(s)."))
        await self._relay_status(name, data, ctx.channel, f"📡 **{ctx.guild.name}** › #{ctx.channel.name} has joined the network.")

    @wh.command(name="close")
    @commands.guild_only()
    async def wh_close(self, ctx: commands.Context, name: str = None):
        """Unlink the current channel from a network (auto-detects if name omitted)."""
        if name is None:
            name = await self._network_for_channel(ctx.channel.id)
            if not name:
                return await ctx.send(embed=err_embed("This channel isn't linked to any network."))
        else:
            name = name.lower()

        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if ctx.channel.id not in data["channels"]:
            return await ctx.send(embed=err_embed("This channel isn't linked to that network."))

        async with self.config.networks() as networks:
            networks[name]["channels"].remove(ctx.channel.id)
            data = networks[name]

        # Remove cached webhook
        self.webhook_cache.pop(ctx.channel.id, None)

        await ctx.send(embed=ok_embed(f"This channel has been severed from **{name}**."))
        await self._relay_status(name, data, ctx.channel, f"📡 **{ctx.guild.name}** › #{ctx.channel.name} has left the network.")

    @wh.command(name="list")
    async def wh_list(self, ctx: commands.Context):
        """List all wormhole networks."""
        networks = await self.config.networks()
        if not networks:
            return await ctx.send(embed=info_embed("No wormhole networks exist yet."))

        lines = []
        for name, data in sorted(networks.items()):
            status = "❄️ frozen" if data.get("frozen") else f"✅ {len(data['channels'])} ch"
            owner = self.bot.get_user(data["owner_id"])
            owner_str = str(owner) if owner else str(data["owner_id"])
            lines.append(f"**{name}** — {status} — owner: {owner_str}")

        em = info_embed("\n".join(lines), title="🌀 Wormhole Networks")
        await ctx.send(embed=em)

    @wh.command(name="info")
    async def wh_info(self, ctx: commands.Context, name: str):
        """Show detailed info about a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))

        owner = self.bot.get_user(data["owner_id"])
        owner_str = str(owner) if owner else str(data["owner_id"])

        channels_list = []
        for ch_id in data["channels"]:
            ch = self.bot.get_channel(ch_id)
            if ch:
                channels_list.append(f"• **{ch.guild.name}** › #{ch.name}")
            else:
                channels_list.append(f"• `{ch_id}` (unreachable)")

        colour = discord.Colour(data["colour"]) if data.get("colour") else COLOUR_INFO
        em = discord.Embed(title=f"🌀 {name}", description=data.get("description") or "*No description.*", colour=colour)
        em.add_field(name="Owner", value=owner_str, inline=True)
        em.add_field(name="Staff", value=str(len(data.get("staff_ids", []))), inline=True)
        em.add_field(name="Channels", value=str(len(data["channels"])), inline=True)
        em.add_field(name="Total relayed", value=f"{data.get('total_messages', 0):,}", inline=True)
        em.add_field(name="Webhooks", value="✅" if data["use_webhooks"] else "❌", inline=True)
        em.add_field(name="Frozen", value="✅" if data.get("frozen") else "❌", inline=True)

        sync_flags = []
        for flag in ("sync_edits", "sync_deletes", "sync_reactions", "sync_replies", "sync_stickers", "forward_embeds"):
            emoji = "✅" if data.get(flag) else "❌"
            sync_flags.append(f"{emoji} {flag.replace('_', ' ').title()}")
        em.add_field(name="Sync", value="\n".join(sync_flags), inline=False)

        em.add_field(
            name="Identity",
            value=f"Name mode: `{data['name_mode']}`\nImage mode: `{data['image_mode']}`",
            inline=True,
        )
        em.add_field(
            name="Rate limit",
            value=f"{data.get('rate_limit_rate', 5)} msgs / {data.get('rate_limit_per', 10)}s",
            inline=True,
        )

        if channels_list:
            em.add_field(name="Linked channels", value="\n".join(channels_list[:20]), inline=False)

        if data.get("banned_users"):
            em.add_field(name="Banned users", value=str(len(data["banned_users"])), inline=True)
        if data.get("muted_users"):
            em.add_field(name="Muted users", value=str(len(data["muted_users"])), inline=True)
        if data.get("word_filters") or data.get("regex_filters"):
            em.add_field(name="Filters", value=f"{len(data.get('word_filters', []))} word / {len(data.get('regex_filters', []))} regex", inline=True)

        if data.get("created_at"):
            em.set_footer(text=f"Created {data['created_at'][:10]}")
        if data.get("custom_icon"):
            em.set_thumbnail(url=data["custom_icon"])
        await ctx.send(embed=em)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  SETTINGS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="set", invoke_without_command=True)
    async def wh_set(self, ctx: commands.Context):
        """Customise a network's settings."""
        await ctx.send_help(ctx.command)

    async def _set_toggle(self, ctx, name, key, value):
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("You need to be staff or owner of this network."))
        async with self.config.networks() as networks:
            networks[name][key] = value
        status = "enabled" if value else "disabled"
        await ctx.send(embed=ok_embed(f"**{key.replace('_', ' ').title()}** {status} for **{name}**."))

    @wh_set.command(name="webhooks")
    async def wh_set_webhooks(self, ctx, name: str, toggle: bool):
        """Enable/disable webhook relay."""
        await self._set_toggle(ctx, name, "use_webhooks", toggle)

    @wh_set.command(name="sync-edits")
    async def wh_set_sync_edits(self, ctx, name: str, toggle: bool):
        """Toggle edit synchronisation."""
        await self._set_toggle(ctx, name, "sync_edits", toggle)

    @wh_set.command(name="sync-deletes")
    async def wh_set_sync_deletes(self, ctx, name: str, toggle: bool):
        """Toggle delete synchronisation."""
        await self._set_toggle(ctx, name, "sync_deletes", toggle)

    @wh_set.command(name="sync-reactions")
    async def wh_set_sync_reactions(self, ctx, name: str, toggle: bool):
        """Toggle reaction synchronisation."""
        await self._set_toggle(ctx, name, "sync_reactions", toggle)

    @wh_set.command(name="sync-replies")
    async def wh_set_sync_replies(self, ctx, name: str, toggle: bool):
        """Toggle reply context forwarding."""
        await self._set_toggle(ctx, name, "sync_replies", toggle)

    @wh_set.command(name="sync-stickers")
    async def wh_set_sync_stickers(self, ctx, name: str, toggle: bool):
        """Toggle sticker forwarding."""
        await self._set_toggle(ctx, name, "sync_stickers", toggle)

    @wh_set.command(name="sync-threads")
    async def wh_set_sync_threads(self, ctx, name: str, toggle: bool):
        """Toggle thread message relaying."""
        await self._set_toggle(ctx, name, "sync_threads", toggle)

    @wh_set.command(name="forward-embeds")
    async def wh_set_forward_embeds(self, ctx, name: str, toggle: bool):
        """Toggle forwarding of embeds from messages."""
        await self._set_toggle(ctx, name, "forward_embeds", toggle)

    @wh_set.command(name="nsfw-gate")
    async def wh_set_nsfw(self, ctx, name: str, toggle: bool):
        """Block relay from NSFW channels."""
        await self._set_toggle(ctx, name, "nsfw_gate", toggle)

    @wh_set.command(name="silent")
    async def wh_set_silent(self, ctx, name: str, toggle: bool):
        """Toggle join/leave announcements."""
        await self._set_toggle(ctx, name, "silent", toggle)

    @wh_set.command(name="freeze")
    async def wh_set_freeze(self, ctx, name: str, toggle: bool):
        """Freeze (pause) or unfreeze a network."""
        await self._set_toggle(ctx, name, "frozen", toggle)

    @wh_set.command(name="name-mode")
    async def wh_set_name_mode(self, ctx, name: str, mode: str):
        """Set name display: user | server | both | custom"""
        mode = mode.lower()
        if mode not in ("user", "server", "both", "custom"):
            return await ctx.send(embed=err_embed("Mode must be `user`, `server`, `both`, or `custom`."))
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name]["name_mode"] = mode
        await ctx.send(embed=ok_embed(f"Name mode → `{mode}` for **{name}**."))

    @wh_set.command(name="image-mode")
    async def wh_set_image_mode(self, ctx, name: str, mode: str):
        """Set avatar: user | server | custom"""
        mode = mode.lower()
        if mode not in ("user", "server", "custom"):
            return await ctx.send(embed=err_embed("Mode must be `user`, `server`, or `custom`."))
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name]["image_mode"] = mode
        await ctx.send(embed=ok_embed(f"Image mode → `{mode}` for **{name}**."))

    @wh_set.command(name="custom-icon")
    async def wh_set_custom_icon(self, ctx, name: str, url: str):
        """Set a custom network icon URL (used when image_mode=custom)."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name]["custom_icon"] = url
        await ctx.send(embed=ok_embed(f"Custom icon set for **{name}**."))

    @wh_set.command(name="custom-name")
    async def wh_set_custom_name(self, ctx, name: str, *, template: str):
        """Set a custom name template. Use `{user}` and `{server}` placeholders."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name]["custom_name"] = template
        await ctx.send(embed=ok_embed(f"Custom name template → `{template}` for **{name}**."))

    @wh_set.command(name="description")
    async def wh_set_description(self, ctx, name: str, *, text: str):
        """Set the network description."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name]["description"] = text[:1024]
        await ctx.send(embed=ok_embed(f"Description updated for **{name}**."))

    @wh_set.command(name="colour", aliases=["color"])
    async def wh_set_colour(self, ctx, name: str, hex_colour: str):
        """Set the network accent colour (hex, e.g. #7289DA)."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        hex_colour = hex_colour.strip("#")
        try:
            val = int(hex_colour, 16)
        except ValueError:
            return await ctx.send(embed=err_embed("Invalid hex colour."))
        async with self.config.networks() as networks:
            networks[name]["colour"] = val
        await ctx.send(embed=ok_embed(f"Colour updated for **{name}**."))

    @wh_set.command(name="ratelimit")
    async def wh_set_ratelimit(self, ctx, name: str, rate: int, per: float):
        """Set rate limit: <rate> messages per <per> seconds."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        if rate < 1 or per < 1:
            return await ctx.send(embed=err_embed("Rate must be ≥1, per must be ≥1."))
        async with self.config.networks() as networks:
            networks[name]["rate_limit_rate"] = rate
            networks[name]["rate_limit_per"] = per
        if name in self.cooldowns:
            self.cooldowns[name].update(rate, per)
        else:
            self.cooldowns[name] = CooldownBucket(rate, per)
        await ctx.send(embed=ok_embed(f"Rate limit → {rate} msgs / {per}s for **{name}**."))

    @wh_set.command(name="log-channel")
    async def wh_set_log_channel(self, ctx, name: str, channel: discord.TextChannel = None):
        """Set (or clear) the logging channel for a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name]["log_channel"] = channel.id if channel else None
        if channel:
            await ctx.send(embed=ok_embed(f"Log channel → {channel.mention} for **{name}**."))
        else:
            await ctx.send(embed=ok_embed(f"Logging disabled for **{name}**."))

    @wh_set.command(name="nickname")
    async def wh_set_nickname(self, ctx, name: str, *, nickname: str):
        """Set a custom server nickname for this guild in the network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        async with self.config.networks() as networks:
            if "server_nicknames" not in networks[name]:
                networks[name]["server_nicknames"] = {}
            networks[name]["server_nicknames"][str(ctx.guild.id)] = nickname
        await ctx.send(embed=ok_embed(f"This server will appear as **{nickname}** in the **{name}** network."))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STAFF MANAGEMENT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="staff", invoke_without_command=True)
    async def wh_staff(self, ctx):
        """Manage network staff."""
        await ctx.send_help(ctx.command)

    @wh_staff.command(name="add")
    async def wh_staff_add(self, ctx, name: str, user: discord.User):
        """Add a staff member to a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_owner(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Only the network owner can manage staff."))
        if user.id in data.get("staff_ids", []):
            return await ctx.send(embed=err_embed(f"{user} is already staff."))
        async with self.config.networks() as networks:
            networks[name].setdefault("staff_ids", []).append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} is now staff on **{name}**."))

    @wh_staff.command(name="remove")
    async def wh_staff_remove(self, ctx, name: str, user: discord.User):
        """Remove a staff member from a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_owner(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Only the network owner can manage staff."))
        if user.id not in data.get("staff_ids", []):
            return await ctx.send(embed=err_embed(f"{user} is not staff."))
        async with self.config.networks() as networks:
            networks[name]["staff_ids"].remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} removed from staff on **{name}**."))

    @wh_staff.command(name="list")
    async def wh_staff_list(self, ctx, name: str):
        """List staff members of a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        owner = self.bot.get_user(data["owner_id"])
        lines = [f"👑 **Owner:** {owner or data['owner_id']}"]
        for uid in data.get("staff_ids", []):
            u = self.bot.get_user(uid)
            lines.append(f"⭐ {u or uid}")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"Staff — {name}"))

    @wh.command(name="transfer")
    async def wh_transfer(self, ctx, name: str, new_owner: discord.User):
        """Transfer network ownership."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_owner(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Only the network owner can transfer ownership."))
        async with self.config.networks() as networks:
            networks[name]["owner_id"] = new_owner.id
            # Remove new owner from staff if present
            if new_owner.id in networks[name].get("staff_ids", []):
                networks[name]["staff_ids"].remove(new_owner.id)
        await ctx.send(embed=ok_embed(f"Ownership of **{name}** transferred to {new_owner.mention}."))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  MODERATION
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.group(name="mod", invoke_without_command=True)
    async def wh_mod(self, ctx):
        """Moderation commands for networks."""
        await ctx.send_help(ctx.command)

    # ── User ban/unban ──

    @wh_mod.command(name="ban")
    async def wh_mod_ban(self, ctx, name: str, user: discord.User):
        """Ban a user from a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        if user.id in data.get("banned_users", []):
            return await ctx.send(embed=err_embed(f"{user} is already banned."))
        async with self.config.networks() as networks:
            networks[name].setdefault("banned_users", []).append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} banned from **{name}**."))
        await self._log_event(data, warn_embed(f"{ctx.author} banned {user} from **{name}**."))

    @wh_mod.command(name="unban")
    async def wh_mod_unban(self, ctx, name: str, user: discord.User):
        """Unban a user from a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            if user.id in networks[name].get("banned_users", []):
                networks[name]["banned_users"].remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} unbanned from **{name}**."))

    # ── User mute/unmute ──

    @wh_mod.command(name="mute")
    async def wh_mod_mute(self, ctx, name: str, user: discord.User):
        """Mute a user in a network (messages won't relay)."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            if user.id not in networks[name].get("muted_users", []):
                networks[name].setdefault("muted_users", []).append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} muted in **{name}**."))

    @wh_mod.command(name="unmute")
    async def wh_mod_unmute(self, ctx, name: str, user: discord.User):
        """Unmute a user in a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            if user.id in networks[name].get("muted_users", []):
                networks[name]["muted_users"].remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} unmuted in **{name}**."))

    # ── Server ban/unban ──

    @wh_mod.command(name="ban-server")
    async def wh_mod_ban_server(self, ctx, name: str, guild_id: int):
        """Ban a server from a network by guild ID."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            if guild_id not in networks[name].get("banned_servers", []):
                networks[name].setdefault("banned_servers", []).append(guild_id)
            # Also remove any channels belonging to this server
            to_remove = []
            for ch_id in networks[name]["channels"]:
                ch = self.bot.get_channel(ch_id)
                if ch and ch.guild.id == guild_id:
                    to_remove.append(ch_id)
            for ch_id in to_remove:
                networks[name]["channels"].remove(ch_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` banned from **{name}** and {len(to_remove)} channel(s) removed."))

    @wh_mod.command(name="unban-server")
    async def wh_mod_unban_server(self, ctx, name: str, guild_id: int):
        """Unban a server from a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            if guild_id in networks[name].get("banned_servers", []):
                networks[name]["banned_servers"].remove(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` unbanned from **{name}**."))

    # ── Server mute/unmute ──

    @wh_mod.command(name="mute-server")
    async def wh_mod_mute_server(self, ctx, name: str, guild_id: int):
        """Mute a server in a network (its messages won't relay)."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            if guild_id not in networks[name].get("muted_servers", []):
                networks[name].setdefault("muted_servers", []).append(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` muted in **{name}**."))

    @wh_mod.command(name="unmute-server")
    async def wh_mod_unmute_server(self, ctx, name: str, guild_id: int):
        """Unmute a server in a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            if guild_id in networks[name].get("muted_servers", []):
                networks[name]["muted_servers"].remove(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` unmuted in **{name}**."))

    # ── Allowlist ──

    @wh_mod.command(name="allowlist-add")
    async def wh_mod_allowlist_add(self, ctx, name: str, guild_id: int):
        """Add a server to the allowlist (only allowlisted servers can join)."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_owner(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Owner only."))
        async with self.config.networks() as networks:
            if guild_id not in networks[name].get("allowlist_servers", []):
                networks[name].setdefault("allowlist_servers", []).append(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` added to allowlist for **{name}**."))

    @wh_mod.command(name="allowlist-remove")
    async def wh_mod_allowlist_remove(self, ctx, name: str, guild_id: int):
        """Remove a server from the allowlist."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_owner(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Owner only."))
        async with self.config.networks() as networks:
            if guild_id in networks[name].get("allowlist_servers", []):
                networks[name]["allowlist_servers"].remove(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` removed from allowlist for **{name}**."))

    # ── Filters ──

    @wh.group(name="filter", invoke_without_command=True)
    async def wh_filter(self, ctx):
        """Manage word and regex filters."""
        await ctx.send_help(ctx.command)

    @wh_filter.command(name="add-word")
    async def wh_filter_add_word(self, ctx, name: str, *, word: str):
        """Add a word to the filter list."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name].setdefault("word_filters", []).append(word)
        await ctx.send(embed=ok_embed(f"Word filter added to **{name}**."))

    @wh_filter.command(name="remove-word")
    async def wh_filter_remove_word(self, ctx, name: str, *, word: str):
        """Remove a word from the filter list."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            filters = networks[name].get("word_filters", [])
            if word in filters:
                filters.remove(word)
        await ctx.send(embed=ok_embed(f"Word filter removed from **{name}**."))

    @wh_filter.command(name="add-regex")
    async def wh_filter_add_regex(self, ctx, name: str, *, pattern: str):
        """Add a regex pattern to the filter."""
        import re as _re
        try:
            _re.compile(pattern)
        except _re.error as e:
            return await ctx.send(embed=err_embed(f"Invalid regex: {e}"))
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            networks[name].setdefault("regex_filters", []).append(pattern)
        await ctx.send(embed=ok_embed(f"Regex filter added to **{name}**."))

    @wh_filter.command(name="remove-regex")
    async def wh_filter_remove_regex(self, ctx, name: str, *, pattern: str):
        """Remove a regex pattern from the filter."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        if not await self._is_staff(data, ctx.author.id) and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed("Staff or owner only."))
        async with self.config.networks() as networks:
            filters = networks[name].get("regex_filters", [])
            if pattern in filters:
                filters.remove(pattern)
        await ctx.send(embed=ok_embed(f"Regex filter removed from **{name}**."))

    @wh_filter.command(name="list")
    async def wh_filter_list(self, ctx, name: str):
        """List all filters on a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        words = data.get("word_filters", [])
        regexes = data.get("regex_filters", [])
        lines = []
        if words:
            lines.append("**Word filters:**")
            for w in words:
                lines.append(f"• `{w}`")
        if regexes:
            lines.append("**Regex filters:**")
            for r in regexes:
                lines.append(f"• `{r}`")
        if not lines:
            lines.append("No filters configured.")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"Filters — {name}"))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STATISTICS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="stats")
    async def wh_stats(self, ctx, name: str):
        """Show relay statistics for a network."""
        name = name.lower()
        data = await self._get_network(name)
        if not data:
            return await ctx.send(embed=err_embed(f"Network **{name}** not found."))
        total = data.get("total_messages", 0)
        channels = len(data.get("channels", []))
        created = data.get("created_at", "Unknown")
        if created and created != "Unknown":
            created = created[:10]

        em = discord.Embed(title=f"📊 Stats — {name}", colour=COLOUR_INFO)
        em.add_field(name="Total messages relayed", value=f"{total:,}", inline=True)
        em.add_field(name="Linked channels", value=str(channels), inline=True)
        em.add_field(name="Created", value=created, inline=True)
        em.add_field(name="Banned users", value=str(len(data.get("banned_users", []))), inline=True)
        em.add_field(name="Muted users", value=str(len(data.get("muted_users", []))), inline=True)
        em.add_field(name="Filters", value=f"{len(data.get('word_filters', []))}w / {len(data.get('regex_filters', []))}r", inline=True)
        await ctx.send(embed=em)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  MESSAGE RELAY  (the core engine)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._ready.wait()
        if not message.guild or message.author.bot:
            return
        if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return

        # Determine effective channel for network lookup
        effective_channel_id = message.channel.id
        is_thread = isinstance(message.channel, discord.Thread)
        if is_thread:
            effective_channel_id = message.channel.parent_id

        networks = await self.config.networks()
        network_name = None
        net_data = None
        for n, d in networks.items():
            if effective_channel_id in d.get("channels", []):
                network_name = n
                net_data = d
                break
        if not network_name:
            return

        # Thread check
        if is_thread and not net_data.get("sync_threads"):
            return

        # Frozen check
        if net_data.get("frozen"):
            return

        # Ignore bot prefix / commands
        prefixes = await self.bot.get_prefix(message)
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        if any(message.content.startswith(p) for p in prefixes):
            return

        # NSFW gate
        if net_data.get("nsfw_gate") and hasattr(message.channel, "is_nsfw") and message.channel.is_nsfw():
            return

        # Ban / mute checks
        if message.author.id in net_data.get("banned_users", []):
            return
        if message.author.id in net_data.get("muted_users", []):
            return
        if message.guild.id in net_data.get("banned_servers", []):
            return
        if message.guild.id in net_data.get("muted_servers", []):
            return

        # Content filter
        if message.content:
            matched = check_filters(
                message.content,
                net_data.get("word_filters", []),
                net_data.get("regex_filters", []),
            )
            if matched:
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=warn_embed(f"{message.author.mention}, your message was blocked by a filter."),
                        delete_after=5,
                    )
                except Exception:
                    pass
                return

        # Rate limit
        bucket = self.cooldowns.get(network_name)
        if bucket and bucket.is_rate_limited(message.author.id, network_name):
            try:
                await message.add_reaction("🕐")
            except Exception:
                pass
            return

        # ── Build relay payload ──

        use_webhooks = net_data.get("use_webhooks", True)
        image_mode = net_data.get("image_mode", "user")
        name_mode = net_data.get("name_mode", "both")
        custom_icon = net_data.get("custom_icon")
        custom_name = net_data.get("custom_name")
        server_nick = net_data.get("server_nicknames", {}).get(str(message.guild.id))

        avatar_url = self._resolve_avatar(message, image_mode, custom_icon)
        username = self._resolve_name(message, name_mode, custom_name, server_nick)

        content = message.content or ""
        embeds_to_send: List[discord.Embed] = []

        # ── Reply context ──
        if net_data.get("sync_replies") and message.reference and message.reference.message_id:
            try:
                ref_msg = message.reference.cached_message or await message.channel.fetch_message(message.reference.message_id)
                reply_preview = truncate(ref_msg.content, 100) if ref_msg.content else "*[attachment/embed]*"
                reply_author = ref_msg.author.display_name
                content = f"> **↩ {reply_author}:** {reply_preview}\n{content}"
            except Exception:
                content = f"> ↩ *[reply]*\n{content}"

        # ── Stickers ──
        if net_data.get("sync_stickers") and message.stickers:
            sticker_lines = []
            for sticker in message.stickers:
                sticker_lines.append(f"[Sticker: {sticker.name}]({sticker.url})")
            if sticker_lines:
                content = content + "\n" + "\n".join(sticker_lines) if content else "\n".join(sticker_lines)

        # ── Forward embeds ──
        if net_data.get("forward_embeds") and message.embeds:
            for em in message.embeds:
                if em.type == "rich":
                    embeds_to_send.append(em)

        # ── Files ──
        files = []
        for att in message.attachments:
            try:
                files.append(await att.to_file())
            except Exception:
                pass

        # ── Relay ──
        mapping: Dict[int, int] = {}

        for ch_id in net_data["channels"]:
            if ch_id == effective_channel_id:
                continue
            relay_ch = self.bot.get_channel(ch_id)
            if not relay_ch:
                continue

            try:
                if use_webhooks:
                    wh = await self._get_webhook(relay_ch)
                    # Re-create files for each send (files are consumed)
                    send_files = []
                    for att in message.attachments:
                        try:
                            send_files.append(await att.to_file())
                        except Exception:
                            pass
                    sent = await wh.send(
                        content=content if content else None,
                        username=truncate(username, 80),
                        avatar_url=avatar_url,
                        files=send_files if send_files else discord.utils.MISSING,
                        embeds=embeds_to_send if embeds_to_send else discord.utils.MISSING,
                        wait=True,
                    )
                    mapping[ch_id] = sent.id
                else:
                    display = username
                    prefix_text = f"**{display}:** " if content else f"**{display}** "
                    send_files = []
                    for att in message.attachments:
                        try:
                            send_files.append(await att.to_file())
                        except Exception:
                            pass
                    sent = await relay_ch.send(
                        content=truncate(prefix_text + content, 2000),
                        files=send_files if send_files else None,
                        embeds=embeds_to_send if embeds_to_send else None,
                    )
                    mapping[ch_id] = sent.id
            except Exception as exc:
                log.warning("Failed to relay to %s: %s", ch_id, exc)

        # Store mapping
        if mapping:
            self.msg_map.add(network_name, message.id, mapping)

        # Increment stats
        async with self.config.networks() as nets:
            if network_name in nets:
                nets[network_name]["total_messages"] = nets[network_name].get("total_messages", 0) + 1

    # ── Edit sync ───────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        await self._ready.wait()
        if not after.guild or after.author.bot:
            return
        if before.content == after.content:
            return

        effective_channel_id = after.channel.id
        if isinstance(after.channel, discord.Thread):
            effective_channel_id = after.channel.parent_id

        network_name = await self._network_for_channel(effective_channel_id)
        if not network_name:
            return
        net_data = await self._get_network(network_name)
        if not net_data or not net_data.get("sync_edits"):
            return

        mapping = self.msg_map.get_relayed(network_name, after.id)
        if not mapping:
            return

        use_webhooks = net_data.get("use_webhooks", True)

        for ch_id, msg_id in mapping.items():
            relay_ch = self.bot.get_channel(ch_id)
            if not relay_ch:
                continue
            try:
                if use_webhooks:
                    wh = await self._get_webhook(relay_ch)
                    await wh.edit_message(msg_id, content=after.content or "")
                else:
                    msg = await relay_ch.fetch_message(msg_id)
                    # Preserve the prefix
                    old_content = msg.content
                    colon_pos = old_content.find(":** ")
                    if colon_pos != -1:
                        prefix = old_content[: colon_pos + 4]
                        await msg.edit(content=truncate(prefix + after.content, 2000))
            except Exception as exc:
                log.debug("Edit sync failed for %s/%s: %s", ch_id, msg_id, exc)

    # ── Delete sync ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        await self._ready.wait()
        if not message.guild or message.author.bot:
            return

        effective_channel_id = message.channel.id
        if isinstance(message.channel, discord.Thread):
            effective_channel_id = message.channel.parent_id

        network_name = await self._network_for_channel(effective_channel_id)
        if not network_name:
            return
        net_data = await self._get_network(network_name)
        if not net_data or not net_data.get("sync_deletes"):
            return

        mapping = self.msg_map.get_relayed(network_name, message.id)
        if not mapping:
            return

        use_webhooks = net_data.get("use_webhooks", True)

        for ch_id, msg_id in mapping.items():
            relay_ch = self.bot.get_channel(ch_id)
            if not relay_ch:
                continue
            try:
                if use_webhooks:
                    wh = await self._get_webhook(relay_ch)
                    await wh.delete_message(msg_id)
                else:
                    msg = await relay_ch.fetch_message(msg_id)
                    await msg.delete()
            except Exception as exc:
                log.debug("Delete sync failed for %s/%s: %s", ch_id, msg_id, exc)

    # ── Reaction sync ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        await self._ready.wait()
        if user.bot:
            return
        message = reaction.message
        if not message.guild:
            return

        effective_channel_id = message.channel.id
        if isinstance(message.channel, discord.Thread):
            effective_channel_id = message.channel.parent_id

        network_name = await self._network_for_channel(effective_channel_id)
        if not network_name:
            return
        net_data = await self._get_network(network_name)
        if not net_data or not net_data.get("sync_reactions"):
            return

        mapping = self.msg_map.get_relayed(network_name, message.id)
        if not mapping:
            return

        for ch_id, msg_id in mapping.items():
            relay_ch = self.bot.get_channel(ch_id)
            if not relay_ch:
                continue
            try:
                relay_msg = await relay_ch.fetch_message(msg_id)
                await relay_msg.add_reaction(reaction.emoji)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        await self._ready.wait()
        if user.bot:
            return
        message = reaction.message
        if not message.guild:
            return

        effective_channel_id = message.channel.id
        if isinstance(message.channel, discord.Thread):
            effective_channel_id = message.channel.parent_id

        network_name = await self._network_for_channel(effective_channel_id)
        if not network_name:
            return
        net_data = await self._get_network(network_name)
        if not net_data or not net_data.get("sync_reactions"):
            return

        mapping = self.msg_map.get_relayed(network_name, message.id)
        if not mapping:
            return

        for ch_id, msg_id in mapping.items():
            relay_ch = self.bot.get_channel(ch_id)
            if not relay_ch:
                continue
            try:
                relay_msg = await relay_ch.fetch_message(msg_id)
                await relay_msg.remove_reaction(reaction.emoji, self.bot.user)
            except Exception:
                pass

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  HELP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @wh.command(name="help")
    async def wh_help(self, ctx):
        """Full command reference."""
        p = ctx.clean_prefix
        em = discord.Embed(
            title="🌀 Wormhole — Command Reference",
            colour=COLOUR_NEUTRAL,
            description=(
                "Wormhole connects channels across servers into named networks. "
                "Messages, edits, deletes, reactions, replies, stickers, embeds and files "
                "are all relayed in real-time."
            ),
        )
        em.add_field(
            name="📡 Network Management",
            value=(
                f"`{p}wh create <name> [description]` — Create a network\n"
                f"`{p}wh delete <name>` — Delete a network\n"
                f"`{p}wh open <name>` — Link this channel\n"
                f"`{p}wh close [name]` — Unlink this channel\n"
                f"`{p}wh list` — List all networks\n"
                f"`{p}wh info <name>` — Network details\n"
                f"`{p}wh stats <name>` — Relay statistics\n"
                f"`{p}wh transfer <name> @user` — Transfer ownership"
            ),
            inline=False,
        )
        em.add_field(
            name="⚙️ Settings (`wh set`)",
            value=(
                f"`{p}wh set webhooks <name> <true/false>`\n"
                f"`{p}wh set name-mode <name> <user|server|both|custom>`\n"
                f"`{p}wh set image-mode <name> <user|server|custom>`\n"
                f"`{p}wh set custom-icon <name> <url>`\n"
                f"`{p}wh set custom-name <name> <template>`\n"
                f"`{p}wh set description <name> <text>`\n"
                f"`{p}wh set colour <name> <hex>`\n"
                f"`{p}wh set ratelimit <name> <rate> <per>`\n"
                f"`{p}wh set log-channel <name> [#channel]`\n"
                f"`{p}wh set nickname <name> <nickname>`\n"
                f"`{p}wh set freeze <name> <true/false>`\n"
                f"`{p}wh set silent <name> <true/false>`\n"
                f"`{p}wh set nsfw-gate <name> <true/false>`\n"
                f"`{p}wh set sync-edits/deletes/reactions/replies/stickers/threads <name> <true/false>`\n"
                f"`{p}wh set forward-embeds <name> <true/false>`"
            ),
            inline=False,
        )
        em.add_field(
            name="⭐ Staff",
            value=(
                f"`{p}wh staff add <name> @user`\n"
                f"`{p}wh staff remove <name> @user`\n"
                f"`{p}wh staff list <name>`"
            ),
            inline=True,
        )
        em.add_field(
            name="🛡️ Moderation (`wh mod`)",
            value=(
                f"`{p}wh mod ban/unban <name> @user`\n"
                f"`{p}wh mod mute/unmute <name> @user`\n"
                f"`{p}wh mod ban-server/unban-server <name> <id>`\n"
                f"`{p}wh mod mute-server/unmute-server <name> <id>`\n"
                f"`{p}wh mod allowlist-add/remove <name> <id>`"
            ),
            inline=True,
        )
        em.add_field(
            name="🔍 Filters (`wh filter`)",
            value=(
                f"`{p}wh filter add-word <name> <word>`\n"
                f"`{p}wh filter remove-word <name> <word>`\n"
                f"`{p}wh filter add-regex <name> <pattern>`\n"
                f"`{p}wh filter remove-regex <name> <pattern>`\n"
                f"`{p}wh filter list <name>`"
            ),
            inline=False,
        )
        em.set_footer(text="Wormhole v3.0.0 • EveCogs")
        await ctx.send(embed=em)
