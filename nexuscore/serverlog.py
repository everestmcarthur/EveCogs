"""NexusCore — Comprehensive server logging with message cache, event routing, ignore filters."""

from __future__ import annotations

import asyncio
import collections
import datetime
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import Clr, safe_send, ts_now, ts_relative

# ── Defaults ───────────────────────────────────────────────────────────────
LOG_DEFAULTS_GUILD = {
    "enabled": False,
    "default_channel": None,
    "channels": {},
    # event_type -> channel_id (override per event)
    # "message_edit", "message_delete", "bulk_delete",
    # "member_join", "member_leave", "member_ban", "member_unban",
    # "member_update", "role_create", "role_delete", "role_update",
    # "channel_create", "channel_delete", "channel_update",
    # "voice", "invite", "emoji", "sticker", "thread",
    # "server_update", "mod_action"
    "ignore_channels": [],
    "ignore_roles": [],
    "ignore_users": [],
    "ignore_bots": True,
    "log_attachments": True,
    "log_embeds": False,
    "message_cache_size": 1000,
    "compact_mode": False,
    "invite_tracking": True,
    "invites_cache": {},  # code -> {uses, inviter_id}
}

EVENT_TYPES = [
    "message_edit", "message_delete", "bulk_delete",
    "member_join", "member_leave", "member_ban", "member_unban",
    "member_update", "role_create", "role_delete", "role_update",
    "channel_create", "channel_delete", "channel_update",
    "voice", "invite", "emoji", "sticker", "thread",
    "server_update", "mod_action",
]


# ── Mixin ──────────────────────────────────────────────────────────────────
class ServerLogMixin:
    """Server logging mixin — handles all Discord events for audit logging."""

    def _init_logging(self, bot):
        self.log_config = Config.get_conf(
            None, identifier=900006, cog_name="NexusCoreLog"
        )
        self.log_config.register_guild(**LOG_DEFAULTS_GUILD)
        self._msg_cache = {}  # guild_id -> collections.OrderedDict of msg_id -> {content, author, channel, attachments}
        self._invite_cache = {}  # guild_id -> {code: uses}
        self.bot = bot

    def _get_cache(self, guild_id: int) -> collections.OrderedDict:
        if guild_id not in self._msg_cache:
            self._msg_cache[guild_id] = collections.OrderedDict()
        return self._msg_cache[guild_id]

    async def _get_log_channel(self, guild: discord.Guild, event_type: str) -> discord.TextChannel | None:
        data = await self.log_config.guild(guild).all()
        if not data["enabled"]:
            return None
        ch_id = data["channels"].get(event_type) or data["default_channel"]
        if not ch_id:
            return None
        return guild.get_channel(ch_id)

    async def _should_ignore(self, guild: discord.Guild, *, channel=None, member=None) -> bool:
        data = await self.log_config.guild(guild).all()
        if channel and channel.id in data["ignore_channels"]:
            return True
        if member:
            if data["ignore_bots"] and member.bot:
                return True
            if member.id in data["ignore_users"]:
                return True
            if any(r.id in data["ignore_roles"] for r in getattr(member, "roles", [])):
                return True
        return False

    # ── Message cache ──────────────────────────────────────────────────────
    async def _cache_message(self, message: discord.Message):
        if not message.guild:
            return
        cache = self._get_cache(message.guild.id)
        cache[message.id] = {
            "content": message.content,
            "author_id": message.author.id,
            "author_str": str(message.author),
            "channel_id": message.channel.id,
            "attachments": [a.url for a in message.attachments],
            "embeds": len(message.embeds),
        }
        data = await self.log_config.guild(message.guild).all()
        max_size = data.get("message_cache_size", 1000)
        while len(cache) > max_size:
            cache.popitem(last=False)

    # ── Event handlers ─────────────────────────────────────────────────────
    async def _log_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or before.content == after.content:
            return
        if await self._should_ignore(after.guild, channel=after.channel, member=after.author):
            return
        log_ch = await self._get_log_channel(after.guild, "message_edit")
        if not log_ch:
            return

        embed = discord.Embed(
            title="✏️ Message Edited",
            colour=discord.Colour(0x3498DB),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_author(
            name=str(after.author),
            icon_url=after.author.display_avatar.url if after.author.display_avatar else None,
        )
        embed.add_field(name="Before", value=(before.content or "*empty*")[:1024], inline=False)
        embed.add_field(name="After", value=(after.content or "*empty*")[:1024], inline=False)
        embed.add_field(name="Channel", value=after.channel.mention, inline=True)
        embed.add_field(name="Author", value=after.author.mention, inline=True)
        embed.add_field(name="Jump", value=f"[Click]({after.jump_url})", inline=True)
        embed.set_footer(text=f"Message ID: {after.id} · User ID: {after.author.id}")
        await safe_send(log_ch, embed=embed)

    async def _log_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        if await self._should_ignore(message.guild, channel=message.channel, member=message.author):
            return
        log_ch = await self._get_log_channel(message.guild, "message_delete")
        if not log_ch:
            return

        content = message.content or ""
        # Try cache if content is empty
        if not content:
            cached = self._get_cache(message.guild.id).get(message.id)
            if cached:
                content = cached.get("content", "")

        embed = discord.Embed(
            title="🗑️ Message Deleted",
            colour=discord.Colour(0xE74C3C),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_author(
            name=str(message.author),
            icon_url=message.author.display_avatar.url if message.author.display_avatar else None,
        )
        if content:
            embed.add_field(name="Content", value=content[:1024], inline=False)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Author", value=message.author.mention, inline=True)

        data = await self.log_config.guild(message.guild).all()
        if data["log_attachments"] and message.attachments:
            att_text = "\n".join(f"[{a.filename}]({a.url})" for a in message.attachments[:5])
            embed.add_field(name="Attachments", value=att_text, inline=False)

        embed.set_footer(text=f"Message ID: {message.id} · User ID: {message.author.id}")
        await safe_send(log_ch, embed=embed)

    async def _log_bulk_delete(self, messages: list[discord.Message]):
        if not messages or not messages[0].guild:
            return
        guild = messages[0].guild
        log_ch = await self._get_log_channel(guild, "bulk_delete")
        if not log_ch:
            return

        embed = discord.Embed(
            title="🗑️ Bulk Message Delete",
            description=f"**{len(messages)}** messages deleted in {messages[0].channel.mention}",
            colour=discord.Colour(0xE74C3C),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        # Build text file of deleted messages
        lines = []
        for m in messages[:200]:
            ts = m.created_at.strftime("%H:%M:%S")
            lines.append(f"[{ts}] {m.author}: {m.content or '[no content]'}")
        content_txt = "\n".join(lines)

        import io
        file = discord.File(io.BytesIO(content_txt.encode()), filename="bulk_delete.txt")
        await safe_send(log_ch, embed=embed, file=file)

    async def _log_member_join(self, member: discord.Member):
        if await self._should_ignore(member.guild, member=member):
            return
        log_ch = await self._get_log_channel(member.guild, "member_join")
        if not log_ch:
            return

        embed = discord.Embed(
            title="📥 Member Joined",
            colour=discord.Colour(0x2ECC71),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Account Created", value=ts_relative(int(member.created_at.timestamp())), inline=True)
        embed.add_field(name="Member #", value=str(member.guild.member_count), inline=True)

        age_days = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days
        if age_days < 7:
            embed.add_field(name="⚠️ New Account", value=f"Created {age_days} day(s) ago", inline=False)

        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)

        # Invite tracking
        data = await self.log_config.guild(member.guild).all()
        if data.get("invite_tracking"):
            try:
                invites = await member.guild.invites()
                old_cache = self._invite_cache.get(member.guild.id, {})
                for inv in invites:
                    old_uses = old_cache.get(inv.code, 0)
                    if inv.uses > old_uses:
                        embed.add_field(name="Invited by", value=f"{inv.inviter.mention if inv.inviter else 'Unknown'} (code: `{inv.code}`)", inline=False)
                        break
                self._invite_cache[member.guild.id] = {inv.code: inv.uses for inv in invites}
            except discord.HTTPException:
                pass

        await safe_send(log_ch, embed=embed)

    async def _log_member_leave(self, member: discord.Member):
        if await self._should_ignore(member.guild, member=member):
            return
        log_ch = await self._get_log_channel(member.guild, "member_leave")
        if not log_ch:
            return

        embed = discord.Embed(
            title="📤 Member Left",
            colour=discord.Colour(0xE74C3C),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url if member.display_avatar else None)
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
        if member.joined_at:
            embed.add_field(name="Joined", value=ts_relative(int(member.joined_at.timestamp())), inline=True)
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        if roles:
            embed.add_field(name="Roles", value=", ".join(roles[:20]), inline=False)

        await safe_send(log_ch, embed=embed)

    async def _log_member_ban(self, guild: discord.Guild, user: discord.User):
        log_ch = await self._get_log_channel(guild, "member_ban")
        if not log_ch:
            return
        embed = discord.Embed(
            title="🔨 Member Banned",
            colour=discord.Colour(0xE74C3C),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url if user.display_avatar else None)
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=True)

        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target and entry.target.id == user.id:
                    embed.add_field(name="Banned by", value=entry.user.mention if entry.user else "Unknown", inline=True)
                    if entry.reason:
                        embed.add_field(name="Reason", value=entry.reason[:1024], inline=False)
                    break
        except discord.HTTPException:
            pass

        await safe_send(log_ch, embed=embed)

    async def _log_member_unban(self, guild: discord.Guild, user: discord.User):
        log_ch = await self._get_log_channel(guild, "member_unban")
        if not log_ch:
            return
        embed = discord.Embed(
            title="🔓 Member Unbanned",
            description=f"{user.mention} (`{user.id}`)",
            colour=discord.Colour(0x2ECC71),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await safe_send(log_ch, embed=embed)

    async def _log_member_update(self, before: discord.Member, after: discord.Member):
        if await self._should_ignore(after.guild, member=after):
            return
        log_ch = await self._get_log_channel(after.guild, "member_update")
        if not log_ch:
            return

        changes = []

        if before.nick != after.nick:
            changes.append(("Nickname", before.nick or "*None*", after.nick or "*None*"))

        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)
        if added_roles:
            changes.append(("Roles Added", "", ", ".join(r.mention for r in added_roles)))
        if removed_roles:
            changes.append(("Roles Removed", "", ", ".join(r.mention for r in removed_roles)))

        if before.communication_disabled_until != after.communication_disabled_until:
            if after.communication_disabled_until and after.communication_disabled_until > datetime.datetime.now(datetime.timezone.utc):
                changes.append(("Timed Out", "No", ts_relative(int(after.communication_disabled_until.timestamp()))))
            elif before.communication_disabled_until:
                changes.append(("Timeout Removed", "", ""))

        if not changes:
            return

        embed = discord.Embed(
            title="👤 Member Updated",
            colour=discord.Colour(0xF39C12),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_author(name=str(after), icon_url=after.display_avatar.url if after.display_avatar else None)
        for name, old, new in changes:
            if old:
                embed.add_field(name=name, value=f"`{old}` → `{new}`", inline=False)
            else:
                embed.add_field(name=name, value=new, inline=False)

        await safe_send(log_ch, embed=embed)

    async def _log_voice(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if await self._should_ignore(member.guild, member=member):
            return
        log_ch = await self._get_log_channel(member.guild, "voice")
        if not log_ch:
            return

        if before.channel is None and after.channel:
            desc = f"🔊 **{member}** joined **{after.channel.name}**"
            colour = discord.Colour(0x2ECC71)
        elif before.channel and after.channel is None:
            desc = f"🔇 **{member}** left **{before.channel.name}**"
            colour = discord.Colour(0xE74C3C)
        elif before.channel and after.channel and before.channel != after.channel:
            desc = f"🔀 **{member}** moved from **{before.channel.name}** → **{after.channel.name}**"
            colour = discord.Colour(0xF39C12)
        elif before.self_mute != after.self_mute:
            desc = f"{'🔇' if after.self_mute else '🔊'} **{member}** {'self-muted' if after.self_mute else 'self-unmuted'}"
            colour = discord.Colour(0x95A5A6)
        elif before.self_deaf != after.self_deaf:
            desc = f"{'🔇' if after.self_deaf else '🔊'} **{member}** {'self-deafened' if after.self_deaf else 'self-undeafened'}"
            colour = discord.Colour(0x95A5A6)
        elif before.mute != after.mute:
            desc = f"{'🔇' if after.mute else '🔊'} **{member}** was {'server muted' if after.mute else 'server unmuted'}"
            colour = discord.Colour(0xE67E22)
        elif before.deaf != after.deaf:
            desc = f"{'🔇' if after.deaf else '🔊'} **{member}** was {'server deafened' if after.deaf else 'server undeafened'}"
            colour = discord.Colour(0xE67E22)
        else:
            return

        embed = discord.Embed(description=desc, colour=colour, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.set_footer(text=f"User ID: {member.id}")
        await safe_send(log_ch, embed=embed)

    async def _log_channel_create(self, channel: discord.abc.GuildChannel):
        log_ch = await self._get_log_channel(channel.guild, "channel_create")
        if not log_ch:
            return
        embed = discord.Embed(
            title="📁 Channel Created",
            description=f"{channel.mention} (`{channel.name}`)\nType: {str(channel.type).title()}",
            colour=discord.Colour(0x2ECC71),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await safe_send(log_ch, embed=embed)

    async def _log_channel_delete(self, channel: discord.abc.GuildChannel):
        log_ch = await self._get_log_channel(channel.guild, "channel_delete")
        if not log_ch:
            return
        embed = discord.Embed(
            title="📁 Channel Deleted",
            description=f"`{channel.name}` ({str(channel.type).title()})",
            colour=discord.Colour(0xE74C3C),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await safe_send(log_ch, embed=embed)

    async def _log_role_create(self, role: discord.Role):
        log_ch = await self._get_log_channel(role.guild, "role_create")
        if not log_ch:
            return
        embed = discord.Embed(
            title="🏷️ Role Created",
            description=f"{role.mention} (`{role.name}`)\nColour: `{role.colour}`",
            colour=role.colour if role.colour.value else discord.Colour(0x2ECC71),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await safe_send(log_ch, embed=embed)

    async def _log_role_delete(self, role: discord.Role):
        log_ch = await self._get_log_channel(role.guild, "role_delete")
        if not log_ch:
            return
        embed = discord.Embed(
            title="🏷️ Role Deleted",
            description=f"`{role.name}` · Members: {len(role.members)}",
            colour=discord.Colour(0xE74C3C),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await safe_send(log_ch, embed=embed)

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except discord.HTTPException:
            pass
