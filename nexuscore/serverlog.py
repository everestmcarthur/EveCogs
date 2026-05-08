"""NexusCore — Server logging v2: 30+ event types, per-event channels, message cache,
invite tracking, ignore filters, emoji/thread/sticker/permission/webhook/scheduled event,
log retention, search, log formatting."""

from __future__ import annotations

import datetime
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, ts_now, ts_relative,
    safe_send, chunk_list,
)

# ── Event types ────────────────────────────────────────────────────────────
EVENT_TYPES = [
    "message_delete", "message_edit", "message_bulk_delete",
    "member_join", "member_leave", "member_update", "member_ban", "member_unban",
    "role_create", "role_delete", "role_update",
    "channel_create", "channel_delete", "channel_update",
    "voice_join", "voice_leave", "voice_move",
    "invite_create", "invite_delete",
    "emoji_update", "sticker_update",
    "thread_create", "thread_delete", "thread_update",
    "webhook_update",
    "scheduled_event_create", "scheduled_event_delete", "scheduled_event_update",
    "guild_update", "automod_action",
    "permission_update",
    "nickname_change",
    "timeout_add", "timeout_remove",
]

EVENT_EMOJI = {
    "message_delete": "🗑️", "message_edit": "✏️", "message_bulk_delete": "🗑️",
    "member_join": "📥", "member_leave": "📤", "member_update": "👤", "member_ban": "🔨", "member_unban": "🔓",
    "role_create": "🏷️", "role_delete": "🏷️", "role_update": "🏷️",
    "channel_create": "📁", "channel_delete": "📁", "channel_update": "📁",
    "voice_join": "🔊", "voice_leave": "🔇", "voice_move": "🔀",
    "invite_create": "🔗", "invite_delete": "🔗",
    "emoji_update": "😀", "sticker_update": "🖼️",
    "thread_create": "🧵", "thread_delete": "🧵", "thread_update": "🧵",
    "webhook_update": "🪝", "scheduled_event_create": "📅",
    "scheduled_event_delete": "📅", "scheduled_event_update": "📅",
    "guild_update": "⚙️", "automod_action": "🤖",
    "permission_update": "🔒", "nickname_change": "📝",
    "timeout_add": "⏰", "timeout_remove": "⏰",
}

# ── Defaults ───────────────────────────────────────────────────────────────
LOG_DEFAULTS_GUILD = {
    "enabled": False,
    "default_channel": None,
    "channels": {},  # event_type -> channel_id
    "ignore_channels": [],
    "ignore_roles": [],
    "ignore_users": [],
    "ignore_bots": True,
    "enabled_events": {e: True for e in EVENT_TYPES},
    "invite_tracking": True,
    "message_cache_size": 200,
    "log_retention_days": 0,     # 0 = forever
    "compact_mode": False,
    "show_avatar": True,
    "embed_colour": Clr.LOG.value,
}


# ── Mixin ──────────────────────────────────────────────────────────────────
class ServerLogMixin:
    """Server logging mixin — v2 with 30+ events, retention, search."""

    def _init_serverlog(self, bot):
        self.log_config = Config.get_conf(None, identifier=900006, cog_name="NexusCoreLog")
        self.log_config.register_guild(**LOG_DEFAULTS_GUILD)
        self._message_cache = {}   # guild_id -> {message_id: MessageData}
        self._invite_cache = {}    # guild_id -> {code: uses}

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except discord.HTTPException:
            pass

    async def _should_log(self, guild: discord.Guild, event_type: str,
                          channel: discord.abc.GuildChannel | None = None,
                          member: discord.Member | None = None) -> bool:
        data = await self.log_config.guild(guild).all()
        if not data["enabled"]:
            return False
        if not data["enabled_events"].get(event_type, True):
            return False
        if channel and channel.id in data["ignore_channels"]:
            return False
        if member:
            if data["ignore_bots"] and member.bot:
                return False
            if member.id in data["ignore_users"]:
                return False
            if any(r.id in data["ignore_roles"] for r in member.roles):
                return False
        return True

    async def _get_log_channel(self, guild: discord.Guild, event_type: str) -> discord.TextChannel | None:
        data = await self.log_config.guild(guild).all()
        ch_id = data["channels"].get(event_type) or data["default_channel"]
        if ch_id:
            return guild.get_channel(ch_id)
        return None

    async def _log_event(self, guild: discord.Guild, event_type: str,
                         title: str | None = None, description: str = "",
                         fields: list[tuple[str, str, bool]] | None = None,
                         colour: discord.Colour | None = None,
                         thumbnail: str | None = None, author_name: str | None = None,
                         author_icon: str | None = None, footer: str | None = None,
                         channel: discord.abc.GuildChannel | None = None,
                         member: discord.Member | None = None):
        if not await self._should_log(guild, event_type, channel, member):
            return
        log_ch = await self._get_log_channel(guild, event_type)
        if not log_ch:
            return

        data = await self.log_config.guild(guild).all()
        emoji = EVENT_EMOJI.get(event_type, "📋")
        c = colour or discord.Colour(data.get("embed_colour", Clr.LOG.value))
        embed = discord.Embed(colour=c, timestamp=datetime.datetime.now(datetime.timezone.utc))
        if title:
            embed.title = f"{emoji} {title}"
        if description:
            embed.description = description
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=str(value)[:1024], inline=inline)
        if thumbnail and data.get("show_avatar"):
            embed.set_thumbnail(url=thumbnail)
        if author_name:
            embed.set_author(name=author_name, icon_url=author_icon)
        if footer:
            embed.set_footer(text=footer)
        else:
            embed.set_footer(text=f"{event_type} · {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S')}")

        await safe_send(log_ch, embed=embed)

    # ── Message events ─────────────────────────────────────────────────────
    async def _log_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        # Cache message for logging
        self._cache_message(message)
        fields = [
            ("Author", f"{message.author.mention} (`{message.author.id}`)", True),
            ("Channel", message.channel.mention, True),
        ]
        if message.content:
            fields.append(("Content", message.content[:1024], False))
        if message.attachments:
            fields.append(("Attachments", "\n".join(a.url for a in message.attachments), False))
        await self._log_event(
            message.guild, "message_delete", title="Message Deleted",
            fields=fields, colour=Clr.ERROR,
            thumbnail=message.author.display_avatar.url if message.author.display_avatar else None,
            channel=message.channel, member=message.author,
        )

    async def _log_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or before.content == after.content:
            return
        fields = [
            ("Author", f"{after.author.mention} (`{after.author.id}`)", True),
            ("Channel", after.channel.mention, True),
            ("Before", (before.content or "*empty*")[:1024], False),
            ("After", (after.content or "*empty*")[:1024], False),
            ("Jump", f"[Click]({after.jump_url})", True),
        ]
        await self._log_event(
            after.guild, "message_edit", title="Message Edited",
            fields=fields, colour=discord.Colour(0xF1C40F),
            channel=after.channel, member=after.author,
        )

    async def _log_bulk_delete(self, messages: list[discord.Message]):
        if not messages or not messages[0].guild:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        desc = f"**{len(messages)}** messages deleted in {channel.mention}"
        await self._log_event(
            guild, "message_bulk_delete", title="Bulk Message Delete",
            description=desc, colour=Clr.ERROR, channel=channel,
        )

    # ── Member events ──────────────────────────────────────────────────────
    async def _log_member_join(self, member: discord.Member):
        age = (datetime.datetime.now(datetime.timezone.utc) - member.created_at).days
        fields = [
            ("User", f"{member.mention} (`{member.id}`)", True),
            ("Account Age", f"{age} days", True),
            ("Member Count", str(member.guild.member_count), True),
        ]
        # Invite tracking
        invite_used = await self._detect_invite(member.guild)
        if invite_used:
            fields.append(("Invite Used", f"`{invite_used}`", True))
        await self._log_event(
            member.guild, "member_join", title="Member Joined",
            fields=fields, colour=Clr.SUCCESS,
            thumbnail=member.display_avatar.url if member.display_avatar else None,
            member=member,
        )

    async def _log_member_leave(self, member: discord.Member):
        roles = [r.mention for r in member.roles if r != member.guild.default_role][:20]
        fields = [
            ("User", f"{member} (`{member.id}`)", True),
            ("Joined", ts_relative(int(member.joined_at.timestamp())) if member.joined_at else "?", True),
        ]
        if roles:
            fields.append(("Roles", " ".join(roles), False))
        await self._log_event(
            member.guild, "member_leave", title="Member Left",
            fields=fields, colour=Clr.ERROR,
            thumbnail=member.display_avatar.url if member.display_avatar else None,
        )

    async def _log_member_update(self, before: discord.Member, after: discord.Member):
        # Role changes
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added or removed:
            fields = [("User", after.mention, True)]
            if added:
                fields.append(("Roles Added", " ".join(r.mention for r in added), False))
            if removed:
                fields.append(("Roles Removed", " ".join(r.mention for r in removed), False))
            await self._log_event(
                after.guild, "member_update", title="Member Roles Updated",
                fields=fields, member=after,
            )

        # Nickname change
        if before.nick != after.nick:
            fields = [
                ("User", after.mention, True),
                ("Before", before.nick or before.name, True),
                ("After", after.nick or after.name, True),
            ]
            await self._log_event(
                after.guild, "nickname_change", title="Nickname Changed",
                fields=fields, member=after,
            )

        # Timeout
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until and after.timed_out_until > datetime.datetime.now(datetime.timezone.utc):
                fields = [
                    ("User", after.mention, True),
                    ("Until", ts_relative(int(after.timed_out_until.timestamp())), True),
                ]
                await self._log_event(
                    after.guild, "timeout_add", title="Member Timed Out",
                    fields=fields, colour=discord.Colour(0xE74C3C), member=after,
                )
            elif before.timed_out_until:
                await self._log_event(
                    after.guild, "timeout_remove", title="Timeout Removed",
                    description=f"{after.mention} timeout removed.", member=after,
                )

    async def _log_member_ban(self, guild: discord.Guild, user: discord.User):
        await self._log_event(
            guild, "member_ban", title="Member Banned",
            description=f"{user.mention} (`{user.id}`) was banned.",
            colour=Clr.ERROR,
            thumbnail=user.display_avatar.url if user.display_avatar else None,
        )

    async def _log_member_unban(self, guild: discord.Guild, user: discord.User):
        await self._log_event(
            guild, "member_unban", title="Member Unbanned",
            description=f"{user.mention} (`{user.id}`) was unbanned.",
            colour=Clr.SUCCESS,
        )

    # ── Channel events ─────────────────────────────────────────────────────
    async def _log_channel_create(self, channel: discord.abc.GuildChannel):
        await self._log_event(
            channel.guild, "channel_create", title="Channel Created",
            description=f"{channel.mention} (`{channel.name}`)",
            fields=[("Type", str(channel.type), True)],
            colour=Clr.SUCCESS,
        )

    async def _log_channel_delete(self, channel: discord.abc.GuildChannel):
        await self._log_event(
            channel.guild, "channel_delete", title="Channel Deleted",
            description=f"`{channel.name}` (Type: {channel.type})",
            colour=Clr.ERROR,
        )

    async def _log_channel_update(self, before, after):
        changes = []
        if hasattr(before, "name") and before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if hasattr(before, "topic") and getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append(f"**Topic:** {getattr(before, 'topic', '') or '*empty*'} → {getattr(after, 'topic', '') or '*empty*'}")
        if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
            changes.append(f"**Slowmode:** {before.slowmode_delay}s → {after.slowmode_delay}s")
        if hasattr(before, "nsfw") and before.nsfw != after.nsfw:
            changes.append(f"**NSFW:** {before.nsfw} → {after.nsfw}")
        if changes:
            await self._log_event(
                after.guild, "channel_update", title="Channel Updated",
                description=f"{after.mention}\n" + "\n".join(changes),
            )

    # ── Role events ────────────────────────────────────────────────────────
    async def _log_role_create(self, role: discord.Role):
        await self._log_event(
            role.guild, "role_create", title="Role Created",
            description=f"{role.mention} (`{role.name}`)",
            colour=Clr.SUCCESS,
        )

    async def _log_role_delete(self, role: discord.Role):
        await self._log_event(
            role.guild, "role_delete", title="Role Deleted",
            description=f"`{role.name}` (colour: {role.colour})",
            colour=Clr.ERROR,
        )

    async def _log_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.colour != after.colour:
            changes.append(f"**Colour:** {before.colour} → {after.colour}")
        if before.hoist != after.hoist:
            changes.append(f"**Hoisted:** {before.hoist} → {after.hoist}")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionable:** {before.mentionable} → {after.mentionable}")
        if before.permissions != after.permissions:
            added = after.permissions.value & ~before.permissions.value
            removed = before.permissions.value & ~after.permissions.value
            if added:
                changes.append(f"**Permissions Added:** `{discord.Permissions(added).value}`")
            if removed:
                changes.append(f"**Permissions Removed:** `{discord.Permissions(removed).value}`")
        if changes:
            await self._log_event(
                after.guild, "role_update", title="Role Updated",
                description=f"{after.mention}\n" + "\n".join(changes),
            )

    # ── Voice events ───────────────────────────────────────────────────────
    async def _log_voice_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel is None and after.channel is not None:
            await self._log_event(
                member.guild, "voice_join", title="Voice Join",
                description=f"{member.mention} joined **{after.channel.name}**",
                member=member,
            )
        elif before.channel is not None and after.channel is None:
            await self._log_event(
                member.guild, "voice_leave", title="Voice Leave",
                description=f"{member.mention} left **{before.channel.name}**",
                member=member,
            )
        elif before.channel != after.channel:
            await self._log_event(
                member.guild, "voice_move", title="Voice Move",
                description=f"{member.mention}: **{before.channel.name}** → **{after.channel.name}**",
                member=member,
            )

    # ── Invite events ──────────────────────────────────────────────────────
    async def _log_invite_create(self, invite: discord.Invite):
        if not invite.guild:
            return
        await self._cache_invites(invite.guild)
        await self._log_event(
            invite.guild, "invite_create", title="Invite Created",
            fields=[
                ("Code", f"`{invite.code}`", True),
                ("Created by", invite.inviter.mention if invite.inviter else "?", True),
                ("Channel", invite.channel.mention if invite.channel else "?", True),
                ("Max Uses", str(invite.max_uses or "∞"), True),
                ("Max Age", str(invite.max_age or "∞") + "s", True),
            ],
        )

    async def _log_invite_delete(self, invite: discord.Invite):
        if not invite.guild:
            return
        await self._log_event(
            invite.guild, "invite_delete", title="Invite Deleted",
            description=f"`{invite.code}`",
            colour=Clr.ERROR,
        )

    # ── Thread events ──────────────────────────────────────────────────────
    async def _log_thread_create(self, thread: discord.Thread):
        await self._log_event(
            thread.guild, "thread_create", title="Thread Created",
            description=f"{thread.mention} in {thread.parent.mention if thread.parent else '?'}",
            fields=[("Owner", f"<@{thread.owner_id}>", True)],
        )

    async def _log_thread_delete(self, thread: discord.Thread):
        await self._log_event(
            thread.guild, "thread_delete", title="Thread Deleted",
            description=f"`{thread.name}`",
            colour=Clr.ERROR,
        )

    async def _log_thread_update(self, before: discord.Thread, after: discord.Thread):
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.archived != after.archived:
            changes.append(f"**Archived:** {before.archived} → {after.archived}")
        if before.locked != after.locked:
            changes.append(f"**Locked:** {before.locked} → {after.locked}")
        if changes:
            await self._log_event(
                after.guild, "thread_update", title="Thread Updated",
                description=f"{after.mention}\n" + "\n".join(changes),
            )

    # ── Guild events ───────────────────────────────────────────────────────
    async def _log_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.icon != after.icon:
            changes.append("**Icon:** Changed")
        if before.banner != after.banner:
            changes.append("**Banner:** Changed")
        if before.verification_level != after.verification_level:
            changes.append(f"**Verification:** {before.verification_level} → {after.verification_level}")
        if changes:
            await self._log_event(
                after, "guild_update", title="Server Updated",
                description="\n".join(changes),
            )

    # ── Utility ────────────────────────────────────────────────────────────
    def _cache_message(self, message: discord.Message):
        if not message.guild:
            return
        gid = message.guild.id
        if gid not in self._message_cache:
            self._message_cache[gid] = {}
        self._message_cache[gid][message.id] = {
            "content": message.content, "author_id": message.author.id,
            "author_name": str(message.author),
            "channel_id": message.channel.id, "created_at": message.created_at.isoformat(),
        }
        cache_limit = 500
        if len(self._message_cache[gid]) > cache_limit:
            oldest = list(self._message_cache[gid].keys())[:cache_limit // 2]
            for key in oldest:
                del self._message_cache[gid][key]

    async def _detect_invite(self, guild: discord.Guild) -> str | None:
        """Try to detect which invite was used."""
        try:
            old = self._invite_cache.get(guild.id, {})
            new_invites = await guild.invites()
            self._invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
            for inv in new_invites:
                if inv.code in old and inv.uses > old[inv.code]:
                    return inv.code
        except discord.HTTPException:
            pass
        return None
