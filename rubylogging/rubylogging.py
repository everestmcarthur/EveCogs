"""
RubyLogging - The most comprehensive Discord event logging system.

Tracks every single Discord event with individual toggles, filtering, and formatting.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify

LOG = logging.getLogger("red.evecogs.rubylogging")

# All Discord events organized by category
EVENTS = {
    "connection": [
        "connect",
        "disconnect",
        "resumed",
        "shard_connect",
        "shard_disconnect",
        "shard_ready",
        "shard_resumed",
    ],
    "gateway": [
        "socket_event_type",
        "socket_raw_receive",
        "socket_raw_send",
    ],
    "guilds": [
        "guild_available",
        "guild_join",
        "guild_remove",
        "guild_unavailable",
        "guild_update",
        "guild_role_create",
        "guild_role_delete",
        "guild_role_update",
        "guild_emojis_update",
        "guild_stickers_update",
        "guild_integrations_update",
    ],
    "channels": [
        "guild_channel_create",
        "guild_channel_delete",
        "guild_channel_update",
        "guild_channel_pins_update",
        "private_channel_create",
        "private_channel_delete",
        "private_channel_update",
        "private_channel_pins_update",
        "group_join",
        "group_remove",
    ],
    "members": [
        "member_join",
        "member_remove",
        "member_update",
        "member_ban",
        "member_unban",
        "user_update",
        "presence_update",
    ],
    "messages": [
        "message",
        "message_delete",
        "message_edit",
        "raw_message_delete",
        "raw_message_edit",
        "raw_bulk_message_delete",
        "reaction_add",
        "reaction_remove",
        "reaction_clear",
        "reaction_clear_emoji",
        "raw_reaction_add",
        "raw_reaction_remove",
        "raw_reaction_clear",
        "raw_reaction_clear_emoji",
    ],
    "voice": [
        "voice_state_update",
    ],
    "stage": [
        "stage_instance_create",
        "stage_instance_delete",
        "stage_instance_update",
    ],
    "threads": [
        "thread_create",
        "thread_delete",
        "thread_join",
        "thread_member_join",
        "thread_member_remove",
        "thread_remove",
        "thread_update",
        "raw_thread_delete",
        "raw_thread_member_remove",
        "raw_thread_update",
    ],
    "interactions": [
        "interaction",
    ],
    "integrations": [
        "integration_create",
        "integration_update",
        "integration_delete",
        "webhooks_update",
        "raw_integration_delete",
    ],
    "invites": [
        "invite_create",
        "invite_delete",
    ],
    "typing": [
        "typing",
    ],
    "automod": [
        "automod_rule_create",
        "automod_rule_update",
        "automod_rule_delete",
        "automod_action_execution",
    ],
    "scheduled_events": [
        "scheduled_event_create",
        "scheduled_event_delete",
        "scheduled_event_update",
        "scheduled_event_user_add",
        "scheduled_event_user_remove",
    ],
    "app_commands": [
        "app_command_completion",
    ],
    "entitlements": [
        "entitlement_create",
        "entitlement_update",
        "entitlement_delete",
    ],
    "audit_log": [
        "audit_log_entry_create",
    ],
}


class RubyLogging(commands.Cog):
    """The ultimate Discord event logging system - every event, individually toggleable."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=0x5255425954524143, force_registration=True
        )

        # Default settings
        default_guild = {
            "log_channel": None,
            "enabled_events": [],
            "disabled_categories": [],
            "format": "detailed",  # detailed, compact, json
            "include_timestamp": True,
            "color_coded": True,
            "ignore_bots": False,
            "ignore_users": [],
            "ignore_channels": [],
            "filter_patterns": [],
            # Attachment logging
            "log_attachments": True,
            "log_stickers": True,
            "show_attachment_previews": True,
            "track_deleted_attachments": True,
            "max_preview_attachments": 4,
        }

        self.config.register_guild(**default_guild)

        # Event handler registry
        self._handlers = {}
        self._register_all_handlers()

        # Attachment cache for deleted messages (message_id -> attachments)
        self._attachment_cache: Dict[int, List[Dict[str, Any]]] = {}
        self._cache_max_size = 1000

    def _register_all_handlers(self) -> None:
        """Dynamically register all event handlers."""
        for category, events in EVENTS.items():
            for event in events:
                # Skip message events - we handle those specially for attachment tracking
                if event in ("message_delete", "raw_bulk_message_delete"):
                    continue

                handler_name = f"_log_{event}"

                # Create dynamic handler
                async def handler(*args, _event=event, _category=category, **kwargs):
                    await self._process_event(_event, _category, *args, **kwargs)

                # Store and register
                setattr(self, handler_name, handler)
                self.bot.add_listener(handler, f"on_{event}")
                self._handlers[event] = handler

        # Register special handlers for attachment tracking
        # These replace the default message_delete and bulk_delete handlers
        self.bot.add_listener(self._cache_message_attachments, "on_message")
        self.bot.add_listener(self._handle_message_delete_with_cache, "on_message_delete")
        self.bot.add_listener(self._handle_bulk_delete_with_cache, "on_bulk_message_delete")

    async def cog_unload(self) -> None:
        """Remove all registered event listeners."""
        for event, handler in self._handlers.items():
            self.bot.remove_listener(handler, f"on_{event}")

        # Remove special attachment handlers
        self.bot.remove_listener(self._cache_message_attachments, "on_message")
        self.bot.remove_listener(self._handle_message_delete_with_cache, "on_message_delete")
        self.bot.remove_listener(self._handle_bulk_delete_with_cache, "on_bulk_message_delete")

        # Clear attachment cache
        self._attachment_cache.clear()

    # ═══════════════════════════════════════════════════════════════════════
    # Attachment Caching for Deleted Messages
    # ═══════════════════════════════════════════════════════════════════════

    async def _cache_message_attachments(self, message: discord.Message) -> None:
        """Cache message attachments for later retrieval if deleted."""
        if not message.guild:
            return

        # Check if attachment tracking is enabled
        try:
            config = self.config.guild(message.guild)
            if not await config.track_deleted_attachments():
                return
        except Exception:
            return

        # Only cache if message has attachments or stickers
        if not message.attachments and not message.stickers:
            return

        # Build attachment data
        attachment_data = []
        for att in message.attachments:
            attachment_data.append({
                "filename": att.filename,
                "url": att.url,
                "proxy_url": att.proxy_url,
                "size": att.size,
                "content_type": att.content_type,
                "is_image": att.content_type.startswith("image/") if att.content_type else False,
                "is_video": att.content_type.startswith("video/") if att.content_type else False,
                "is_gif": att.content_type == "image/gif" if att.content_type else att.filename.lower().endswith(".gif"),
                "width": att.width,
                "height": att.height,
            })

        # Add stickers
        for sticker in message.stickers:
            attachment_data.append({
                "filename": f"{sticker.name}.png",
                "url": sticker.url,
                "proxy_url": sticker.url,
                "size": 0,
                "content_type": "sticker",
                "is_image": True,
                "is_video": False,
                "is_gif": sticker.format == discord.StickerFormatType.gif if hasattr(sticker, 'format') else False,
                "width": None,
                "height": None,
                "sticker_id": sticker.id,
                "sticker_name": sticker.name,
            })

        # Store in cache
        self._attachment_cache[message.id] = attachment_data

        # Prevent unbounded growth
        if len(self._attachment_cache) > self._cache_max_size:
            # Remove oldest entries (first 100)
            oldest_keys = list(self._attachment_cache.keys())[:100]
            for key in oldest_keys:
                self._attachment_cache.pop(key, None)

    async def _handle_message_delete_with_cache(self, message: discord.Message) -> None:
        """Handle message deletion with cached attachment data."""
        if not message.guild:
            return

        # Check if there are cached attachments
        cached = self._attachment_cache.pop(message.id, None)

        # Process the normal message_delete event
        await self._process_event("message_delete", "messages", message)

        # If message had cached attachments, log them separately
        if cached:
            await self._log_deleted_attachments(message, cached)

    async def _handle_bulk_delete_with_cache(self, messages: List[discord.Message]) -> None:
        """Handle bulk message deletion with cached attachments."""
        if not messages:
            return

        guild = messages[0].guild if messages else None
        if not guild:
            return

        # Process normal bulk delete event
        await self._process_event("raw_bulk_message_delete", "messages", messages)

        # Check for any cached attachments
        deleted_with_attachments = []
        for message in messages:
            cached = self._attachment_cache.pop(message.id, None)
            if cached:
                deleted_with_attachments.append((message, cached))

        if deleted_with_attachments:
            await self._log_bulk_deleted_attachments(guild, deleted_with_attachments)

    async def _log_deleted_attachments(
        self, message: discord.Message, attachments: List[Dict[str, Any]]
    ) -> None:
        """Log deleted message attachments with previews."""
        if not message.guild:
            return

        config = self.config.guild(message.guild)

        # Check if attachment logging is enabled
        if not await config.log_attachments():
            return

        enabled_events = await config.enabled_events()
        if "message_delete" not in enabled_events:
            return

        channel_id = await config.log_channel()
        if not channel_id:
            return

        channel = message.guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        # Apply filters
        if await self._should_ignore(message.guild, [message], {}):
            return

        # Build embed
        accent = await config.accent_color()
        color_coded = await config.color_coded()
        include_timestamp = await config.include_timestamp()

        color = discord.Color.red() if color_coded else discord.Color.greyple()
        embed = discord.Embed(
            title="📎 Deleted Message Had Attachments",
            color=color,
        )

        if include_timestamp:
            embed.timestamp = datetime.now(timezone.utc)

        embed.add_field(
            name="Message Info",
            value=(
                f"**Author:** {message.author.mention} (`{message.author.id}`)\n"
                f"**Channel:** {message.channel.mention}\n"
                f"**Message ID:** `{message.id}`"
            ),
            inline=False,
        )

        # List all attachments
        attachment_lines = []
        images_for_preview = []
        show_previews = await config.show_attachment_previews()
        max_previews = await config.max_preview_attachments()

        for i, att in enumerate(attachments, 1):
            size_mb = att["size"] / 1024 / 1024
            type_emoji = "🖼️" if att["is_image"] else "🎬" if att["is_video"] else "📎"

            if att["content_type"] == "sticker":
                type_str = "Sticker"
                attachment_lines.append(
                    f"{type_emoji} **{att['sticker_name']}** (Sticker)\n"
                    f"╰ [View]({att['url']})"
                )
            else:
                if att["is_gif"]:
                    type_str = "GIF"
                    type_emoji = "🎞️"
                elif att["is_image"]:
                    type_str = "Image"
                elif att["is_video"]:
                    type_str = "Video"
                else:
                    type_str = att["content_type"] or "File"

                dims = ""
                if att["width"] and att["height"]:
                    dims = f" ({att['width']}x{att['height']})"

                attachment_lines.append(
                    f"{type_emoji} **{att['filename']}** ({size_mb:.2f} MB)\n"
                    f"╰ Type: {type_str}{dims} · [Download]({att['url']})"
                )

            # Collect images for preview
            if show_previews and att["is_image"] and len(images_for_preview) < max_previews:
                images_for_preview.append(att["url"])

        embed.add_field(
            name=f"📋 Attachments ({len(attachments)})",
            value="\n\n".join(attachment_lines)[:1024],
            inline=False,
        )

        # Add preview for first image
        if images_for_preview:
            embed.set_image(url=images_for_preview[0])

        try:
            sent_msg = await channel.send(embed=embed)

            # Send additional previews if multiple images (as separate embeds)
            if len(images_for_preview) > 1:
                for i, preview_url in enumerate(images_for_preview[1:max_previews], 2):
                    preview_embed = discord.Embed(
                        description=f"**Attachment {i}/{min(len(images_for_preview), max_previews)}**",
                        color=color
                    )
                    preview_embed.set_image(url=preview_url)
                    await channel.send(embed=preview_embed)

        except discord.HTTPException as e:
            LOG.error(f"Failed to send deleted attachment log: {e}")

    async def _log_bulk_deleted_attachments(
        self, guild: discord.Guild, deleted_data: List[Tuple[discord.Message, List[Dict[str, Any]]]]
    ) -> None:
        """Log bulk deleted attachments."""
        config = self.config.guild(guild)

        if not await config.log_attachments():
            return

        channel_id = await config.log_channel()
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        accent = await config.accent_color()
        color_coded = await config.color_coded()
        color = discord.Color.red() if color_coded else discord.Color.greyple()

        embed = discord.Embed(
            title="🗑️ Bulk Delete - Attachments Lost",
            description=f"**{len(deleted_data)}** deleted messages contained attachments",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )

        summary_lines = []
        total_attachments = 0
        for message, attachments in deleted_data[:10]:  # Show first 10
            total_attachments += len(attachments)
            summary_lines.append(
                f"**{message.author}** in {message.channel.mention}\n"
                f"╰ {len(attachments)} attachment(s) · Message ID: `{message.id}`"
            )

        if len(deleted_data) > 10:
            summary_lines.append(f"\n*...and {len(deleted_data) - 10} more messages with attachments*")

        embed.add_field(
            name=f"📎 Total Attachments Lost: {total_attachments}",
            value="\n\n".join(summary_lines)[:1024],
            inline=False,
        )

        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            LOG.error(f"Failed to send bulk deleted attachments log: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # Event Processing Core
    # ═══════════════════════════════════════════════════════════════════════

    async def _process_event(
        self, event_name: str, category: str, *args, **kwargs
    ) -> None:
        """Process and log an event if enabled."""
        # Handle both positional and keyword arguments
        all_args = list(args)

        # Get guild context from event data
        guild = self._extract_guild(all_args, kwargs)
        if not guild:
            return

        # Check if event is enabled
        enabled_events = await self.config.guild(guild).enabled_events()
        if event_name not in enabled_events:
            return

        # Check if category is disabled
        disabled_categories = await self.config.guild(guild).disabled_categories()
        if category in disabled_categories:
            return

        # Get log channel
        channel_id = await self.config.guild(guild).log_channel()
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        # Apply filters
        if await self._should_ignore(guild, all_args, kwargs):
            return

        # Format and send log
        try:
            embed = await self._format_event(
                guild, event_name, category, all_args, kwargs
            )
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            LOG.error(f"Failed to send log for {event_name}: {e}")
        except Exception as e:
            LOG.exception(f"Error processing {event_name}: {e}")

    def _extract_guild(
        self, args: List[Any], kwargs: Dict[str, Any]
    ) -> Optional[discord.Guild]:
        """Extract guild from event arguments."""
        # Try to find guild in arguments
        for arg in args:
            if isinstance(arg, discord.Guild):
                return arg
            if hasattr(arg, "guild") and isinstance(arg.guild, discord.Guild):
                return arg.guild

        # Try keyword arguments
        for value in kwargs.values():
            if isinstance(value, discord.Guild):
                return value
            if hasattr(value, "guild") and isinstance(value.guild, discord.Guild):
                return value.guild

        return None

    async def _should_ignore(
        self, guild: discord.Guild, args: List[Any], kwargs: Dict[str, Any]
    ) -> bool:
        """Check if event should be ignored based on filters."""
        config = self.config.guild(guild)

        # Check bot filter
        ignore_bots = await config.ignore_bots()
        if ignore_bots:
            for arg in args:
                if isinstance(arg, (discord.User, discord.Member)) and arg.bot:
                    return True

        # Check user filter
        ignore_users = await config.ignore_users()
        if ignore_users:
            for arg in args:
                if isinstance(arg, (discord.User, discord.Member)):
                    if arg.id in ignore_users:
                        return True

        # Check channel filter
        ignore_channels = await config.ignore_channels()
        if ignore_channels:
            for arg in args:
                if isinstance(arg, discord.abc.GuildChannel):
                    if arg.id in ignore_channels:
                        return True
                if hasattr(arg, "channel") and isinstance(
                    arg.channel, discord.abc.GuildChannel
                ):
                    if arg.channel.id in ignore_channels:
                        return True

        return False

    async def _format_event(
        self,
        guild: discord.Guild,
        event_name: str,
        category: str,
        args: List[Any],
        kwargs: Dict[str, Any],
    ) -> Union[discord.Embed, List[discord.Embed]]:
        """Format event data into a beautiful, detailed embed."""
        config = self.config.guild(guild)
        format_type = await config.format()
        color_coded = await config.color_coded()
        include_timestamp = await config.include_timestamp()

        # Enhanced color mapping with specific event colors
        colors = {
            "connection": discord.Color.from_rgb(88, 101, 242),  # Blurple
            "gateway": discord.Color.from_rgb(153, 170, 181),  # Grey
            "guilds": discord.Color.from_rgb(138, 43, 226),  # Purple
            "channels": discord.Color.from_rgb(87, 242, 135),  # Green
            "members": discord.Color.from_rgb(255, 165, 0),  # Orange
            "messages": discord.Color.from_rgb(255, 215, 0),  # Gold
            "voice": discord.Color.from_rgb(114, 137, 218),  # Light blurple
            "stage": discord.Color.from_rgb(255, 115, 250),  # Magenta
            "threads": discord.Color.from_rgb(32, 178, 170),  # Teal
            "interactions": discord.Color.from_rgb(237, 66, 69),  # Brand red
            "integrations": discord.Color.from_rgb(218, 165, 32),  # Dark gold
            "invites": discord.Color.from_rgb(211, 211, 211),  # Light grey
            "typing": discord.Color.from_rgb(192, 192, 192),  # Silver
            "automod": discord.Color.from_rgb(255, 0, 0),  # Pure red
            "scheduled_events": discord.Color.from_rgb(75, 0, 130),  # Indigo
            "app_commands": discord.Color.from_rgb(87, 242, 135),  # Brand green
            "entitlements": discord.Color.from_rgb(255, 223, 0),  # Yellow
            "audit_log": discord.Color.from_rgb(139, 0, 0),  # Dark red
        }

        color = colors.get(category, discord.Color.greyple()) if color_coded else discord.Color.greyple()

        # Enhanced title with category emoji
        category_emojis = {
            "connection": "🔌",
            "gateway": "📡",
            "guilds": "🏰",
            "channels": "💬",
            "members": "👥",
            "messages": "📨",
            "voice": "🔊",
            "stage": "🎙️",
            "threads": "🧵",
            "interactions": "⚡",
            "integrations": "🔗",
            "invites": "📨",
            "typing": "⌨️",
            "automod": "🛡️",
            "scheduled_events": "📅",
            "app_commands": "⚙️",
            "entitlements": "💎",
            "audit_log": "📜",
        }

        emoji = category_emojis.get(category, "📋")
        title = f"{emoji} {event_name.replace('_', ' ').title()}"

        embed = discord.Embed(
            title=title,
            color=color,
        )

        if include_timestamp:
            embed.timestamp = datetime.now(timezone.utc)

        # Add category badge in footer
        embed.set_footer(
            text=f"{category.upper()} • on_{event_name}",
            icon_url=guild.icon.url if guild.icon else None
        )

        # Format event data based on format type
        if format_type == "detailed":
            await self._add_detailed_fields(embed, event_name, args, kwargs)
        elif format_type == "compact":
            await self._add_compact_fields(embed, event_name, args, kwargs)
        elif format_type == "json":
            await self._add_json_fields(embed, event_name, args, kwargs)

        # Add image preview for messages with attachments
        preview_url = None
        if args and isinstance(args[0], discord.Message):
            msg = args[0]
            if msg.attachments:
                for att in msg.attachments:
                    if att.content_type and att.content_type.startswith("image/"):
                        preview_url = att.url
                        break

        if preview_url:
            embed.set_image(url=preview_url)

        return embed

    async def _add_detailed_fields(
        self, embed: discord.Embed, event_name: str, args: List[Any], kwargs: Dict[str, Any]
    ) -> None:
        """Add detailed field information to embed with before/after comparisons."""
        # Special handling for update events (before, after pattern)
        if "_update" in event_name and len(args) == 2:
            before, after = args[0], args[1]

            # For message edits, show a compact changes summary instead of full before/after
            if isinstance(before, discord.Message) and isinstance(after, discord.Message):
                changes = await self._detect_changes(before, after)
                if changes:
                    changes_str = "\n".join(f"• {change}" for change in changes)
                    if len(changes_str) > 1024:
                        changes_str = changes_str[:1021] + "..."
                    embed.add_field(name="📝 Message Edit", value=changes_str, inline=False)

                # Add message context
                context = (
                    f"**Author:** {after.author.mention}\n"
                    f"**Channel:** {after.channel.mention if hasattr(after.channel, 'mention') else after.channel}\n"
                    f"**Message ID:** `{after.id}`\n"
                    f"**[Jump to Message]({after.jump_url})**"
                )
                embed.add_field(name="📍 Context", value=context, inline=False)
            else:
                # Standard before/after for other updates
                # Add before state
                before_str = await self._format_object(before)
                if len(before_str) > 1024:
                    before_str = before_str[:1021] + "..."
                embed.add_field(name="📤 Before", value=before_str, inline=False)

                # Add after state
                after_str = await self._format_object(after)
                if len(after_str) > 1024:
                    after_str = after_str[:1021] + "..."
                embed.add_field(name="📥 After", value=after_str, inline=False)

                # Add a changes summary for member/guild/role updates
                changes = await self._detect_changes(before, after)
                if changes:
                    changes_str = "\n".join(f"• {change}" for change in changes)
                    if len(changes_str) > 1024:
                        changes_str = changes_str[:1021] + "..."
                    embed.add_field(name="🔄 Changes Detected", value=changes_str, inline=False)

        else:
            # Standard argument parsing
            for i, arg in enumerate(args):
                name = f"Argument {i + 1}"
                value = await self._format_object(arg)
                if len(value) > 1024:
                    value = value[:1021] + "..."
                embed.add_field(name=name, value=value, inline=False)

            for key, value in kwargs.items():
                formatted = await self._format_object(value)
                if len(formatted) > 1024:
                    formatted = formatted[:1021] + "..."
                embed.add_field(name=key.title(), value=formatted, inline=False)

    async def _detect_changes(self, before: Any, after: Any) -> List[str]:
        """Detect specific changes between before and after objects."""
        changes = []

        if isinstance(before, discord.Member) and isinstance(after, discord.Member):
            if before.nick != after.nick:
                changes.append(f"**Nickname:** `{before.nick or 'None'}` → `{after.nick or 'None'}`")
            if before.roles != after.roles:
                added = set(after.roles) - set(before.roles)
                removed = set(before.roles) - set(after.roles)
                if added:
                    changes.append(f"**Roles Added:** {', '.join(r.mention for r in added)}")
                if removed:
                    changes.append(f"**Roles Removed:** {', '.join(r.mention for r in removed)}")
            if before.status != after.status:
                changes.append(f"**Status:** {before.status.name} → {after.status.name}")
            if hasattr(before, 'timed_out_until') and before.timed_out_until != after.timed_out_until:
                if after.timed_out_until:
                    until = f"<t:{int(after.timed_out_until.timestamp())}:R>"
                    changes.append(f"**Timeout:** Set until {until}")
                else:
                    changes.append("**Timeout:** Removed")

        elif isinstance(before, discord.User) and isinstance(after, discord.User):
            if before.name != after.name:
                changes.append(f"**Username:** `{before.name}` → `{after.name}`")
            if before.discriminator != after.discriminator:
                changes.append(f"**Discriminator:** `{before.discriminator}` → `{after.discriminator}`")
            if before.avatar != after.avatar:
                changes.append("**Avatar:** Changed")

        elif isinstance(before, discord.Guild) and isinstance(after, discord.Guild):
            if before.name != after.name:
                changes.append(f"**Name:** `{before.name}` → `{after.name}`")
            if before.icon != after.icon:
                changes.append("**Icon:** Changed")
            if before.owner_id != after.owner_id:
                changes.append(f"**Owner:** <@{before.owner_id}> → <@{after.owner_id}>")
            if before.premium_tier != after.premium_tier:
                changes.append(f"**Boost Level:** {before.premium_tier} → {after.premium_tier}")
            if before.verification_level != after.verification_level:
                changes.append(f"**Verification:** {before.verification_level.name} → {after.verification_level.name}")

        elif isinstance(before, discord.Role) and isinstance(after, discord.Role):
            if before.name != after.name:
                changes.append(f"**Name:** `{before.name}` → `{after.name}`")
            if before.color != after.color:
                changes.append(f"**Color:** {before.color} → {after.color}")
            if before.hoist != after.hoist:
                changes.append(f"**Hoisted:** {before.hoist} → {after.hoist}")
            if before.mentionable != after.mentionable:
                changes.append(f"**Mentionable:** {before.mentionable} → {after.mentionable}")
            if before.permissions != after.permissions:
                changes.append("**Permissions:** Modified")

        elif isinstance(before, (discord.TextChannel, discord.VoiceChannel)) and isinstance(after, (discord.TextChannel, discord.VoiceChannel)):
            if before.name != after.name:
                changes.append(f"**Name:** `{before.name}` → `{after.name}`")
            if before.category != after.category:
                before_cat = before.category.name if before.category else "None"
                after_cat = after.category.name if after.category else "None"
                changes.append(f"**Category:** {before_cat} → {after_cat}")
            if isinstance(before, discord.TextChannel) and isinstance(after, discord.TextChannel):
                if before.slowmode_delay != after.slowmode_delay:
                    changes.append(f"**Slowmode:** {before.slowmode_delay}s → {after.slowmode_delay}s")
                if before.nsfw != after.nsfw:
                    changes.append(f"**NSFW:** {before.nsfw} → {after.nsfw}")
            if isinstance(before, discord.VoiceChannel) and isinstance(after, discord.VoiceChannel):
                if before.user_limit != after.user_limit:
                    before_limit = before.user_limit or "Unlimited"
                    after_limit = after.user_limit or "Unlimited"
                    changes.append(f"**User Limit:** {before_limit} → {after_limit}")
                if before.bitrate != after.bitrate:
                    changes.append(f"**Bitrate:** {before.bitrate//1000}kbps → {after.bitrate//1000}kbps")

        elif isinstance(before, discord.Message) and isinstance(after, discord.Message):
            if before.content != after.content:
                old_content = before.content[:200] + "..." if len(before.content) > 200 else before.content or "*No text*"
                new_content = after.content[:200] + "..." if len(after.content) > 200 else after.content or "*No text*"
                changes.append(f"**Old Content:**\n{old_content}")
                changes.append(f"**New Content:**\n{new_content}")
            if before.pinned != after.pinned:
                status = "📌 Pinned" if after.pinned else "Unpinned"
                changes.append(f"**Pin Status:** {status}")
            if len(before.embeds) != len(after.embeds):
                changes.append(f"**Embeds:** {len(before.embeds)} → {len(after.embeds)}")
            if len(before.attachments) != len(after.attachments):
                changes.append(f"**Attachments:** {len(before.attachments)} → {len(after.attachments)}")

        return changes

    async def _add_compact_fields(
        self, embed: discord.Embed, event_name: str, args: List[Any], kwargs: Dict[str, Any]
    ) -> None:
        """Add compact field information to embed."""
        summary = []
        for arg in args:
            summary.append(await self._format_object_compact(arg))

        for key, value in kwargs.items():
            summary.append(f"{key}: {await self._format_object_compact(value)}")

        if summary:
            embed.description = "\n".join(summary)[:4096]

    async def _add_json_fields(
        self, embed: discord.Embed, event_name: str, args: List[Any], kwargs: Dict[str, Any]
    ) -> None:
        """Add JSON-formatted data to embed."""
        import json

        data = {
            "args": [await self._serialize_object(arg) for arg in args],
            "kwargs": {k: await self._serialize_object(v) for k, v in kwargs.items()},
        }

        json_str = json.dumps(data, indent=2)
        if len(json_str) > 4000:
            json_str = json_str[:4000] + "\n...truncated"

        embed.description = f"```json\n{json_str}\n```"

    async def _format_object(self, obj: Any) -> str:
        """Format an object into a beautiful, detailed string."""
        if isinstance(obj, discord.User):
            created = f"<t:{int(obj.created_at.timestamp())}:R>" if obj.created_at else "Unknown"
            bot_badge = "🤖" if obj.bot else "👤"
            return (
                f"{bot_badge} **User:** {obj.mention} (`{obj.id}`)\n"
                f"**Username:** {obj.name}\n"
                f"**Display Name:** {obj.display_name}\n"
                f"**Bot:** {'Yes' if obj.bot else 'No'}\n"
                f"**Created:** {created}"
            )
        elif isinstance(obj, discord.Member):
            roles = ", ".join(r.mention for r in obj.roles[1:4]) or "None"
            if len(obj.roles) > 4:
                roles += f" *+{len(obj.roles) - 4} more*"

            joined = f"<t:{int(obj.joined_at.timestamp())}:R>" if obj.joined_at else "Unknown"
            created = f"<t:{int(obj.created_at.timestamp())}:R>" if obj.created_at else "Unknown"

            status_emoji = {
                discord.Status.online: "🟢",
                discord.Status.idle: "🟡",
                discord.Status.dnd: "🔴",
                discord.Status.offline: "⚫",
            }

            return (
                f"**Member:** {obj.mention} (`{obj.id}`)\n"
                f"**Display Name:** {obj.display_name}\n"
                f"**Username:** {obj.name}\n"
                f"**Nickname:** {obj.nick or '*None*'}\n"
                f"**Status:** {status_emoji.get(obj.status, '⚫')} {obj.status.name.title()}\n"
                f"**Roles ({len(obj.roles) - 1}):** {roles}\n"
                f"**Joined Server:** {joined}\n"
                f"**Account Created:** {created}\n"
                f"**Top Role:** {obj.top_role.mention if obj.top_role.name != '@everyone' else '*None*'}"
            )
        elif isinstance(obj, discord.Guild):
            created = f"<t:{int(obj.created_at.timestamp())}:D>" if obj.created_at else "Unknown"
            features = ", ".join(f"`{f}`" for f in list(obj.features)[:5]) if obj.features else "*None*"
            if len(obj.features) > 5:
                features += f" *+{len(obj.features) - 5} more*"

            boost_level = f"{'⭐' * obj.premium_tier} Level {obj.premium_tier}" if obj.premium_tier else "No boosts"

            return (
                f"🏰 **Guild:** {obj.name} (`{obj.id}`)\n"
                f"**Owner:** <@{obj.owner_id}>\n"
                f"**Members:** {obj.member_count:,} total\n"
                f"**Channels:** {len(obj.channels)} ({len(obj.text_channels)} text, {len(obj.voice_channels)} voice)\n"
                f"**Roles:** {len(obj.roles)}\n"
                f"**Boost Status:** {boost_level} ({obj.premium_subscription_count or 0} boosts)\n"
                f"**Created:** {created}\n"
                f"**Features:** {features}"
            )
        elif isinstance(obj, discord.TextChannel):
            perms_msg = "🔒 Private" if obj.overwrites else "🌐 Public"
            slowmode = f"{obj.slowmode_delay}s" if obj.slowmode_delay else "None"
            created = f"<t:{int(obj.created_at.timestamp())}:R>" if obj.created_at else "Unknown"

            return (
                f"💬 **Channel:** {obj.mention} (`{obj.id}`)\n"
                f"**Name:** #{obj.name}\n"
                f"**Category:** {obj.category.name if obj.category else '*None*'}\n"
                f"**Privacy:** {perms_msg}\n"
                f"**Slowmode:** {slowmode}\n"
                f"**Position:** {obj.position}\n"
                f"**NSFW:** {'Yes ⚠️' if obj.nsfw else 'No'}\n"
                f"**Created:** {created}"
            )
        elif isinstance(obj, discord.VoiceChannel):
            limit = f"{obj.user_limit}" if obj.user_limit else "Unlimited ∞"
            bitrate = f"{obj.bitrate // 1000}kbps"
            created = f"<t:{int(obj.created_at.timestamp())}:R>" if obj.created_at else "Unknown"

            return (
                f"🔊 **Voice Channel:** {obj.name} (`{obj.id}`)\n"
                f"**Category:** {obj.category.name if obj.category else '*None*'}\n"
                f"**User Limit:** {limit}\n"
                f"**Bitrate:** {bitrate}\n"
                f"**Position:** {obj.position}\n"
                f"**Region:** {obj.rtc_region or 'Automatic'}\n"
                f"**Created:** {created}"
            )
        elif isinstance(obj, discord.Role):
            created = f"<t:{int(obj.created_at.timestamp())}:R>" if obj.created_at else "Unknown"
            perms = obj.permissions
            perm_list = []
            if perms.administrator:
                perm_list.append("Administrator 👑")
            if perms.manage_guild:
                perm_list.append("Manage Server")
            if perms.manage_roles:
                perm_list.append("Manage Roles")
            if perms.manage_channels:
                perm_list.append("Manage Channels")

            key_perms = ", ".join(perm_list[:3]) if perm_list else "*No special permissions*"
            if len(perm_list) > 3:
                key_perms += f" *+{len(perm_list) - 3} more*"

            return (
                f"**Role:** {obj.mention} (`{obj.id}`)\n"
                f"**Name:** {obj.name}\n"
                f"**Color:** {obj.color} (`#{obj.color.value:06X}`)\n"
                f"**Position:** {obj.position}\n"
                f"**Hoisted:** {'Yes 📌' if obj.hoist else 'No'}\n"
                f"**Mentionable:** {'Yes @' if obj.mentionable else 'No'}\n"
                f"**Members:** {len(obj.members)}\n"
                f"**Key Permissions:** {key_perms}\n"
                f"**Created:** {created}"
            )
        elif isinstance(obj, discord.Message):
            content = obj.content[:150] + "..." if len(obj.content) > 150 else obj.content or "*No text content*"

            # Format timestamp
            created = f"<t:{int(obj.created_at.timestamp())}:f>"

            # Add attachment info with icons
            attachment_info = ""
            if obj.attachments:
                att_types = []
                for att in obj.attachments:
                    if att.content_type:
                        if att.content_type.startswith("image/"):
                            if att.content_type == "image/gif":
                                att_types.append("🎞️ GIF")
                            else:
                                att_types.append("🖼️ Image")
                        elif att.content_type.startswith("video/"):
                            att_types.append("🎬 Video")
                        elif att.content_type.startswith("audio/"):
                            att_types.append("🎵 Audio")
                        else:
                            att_types.append("📎 File")
                    else:
                        att_types.append("📎 File")
                attachment_info = f"\n**Attachments ({len(obj.attachments)}):** {', '.join(att_types)}"

            if obj.stickers:
                sticker_names = ", ".join(s.name for s in obj.stickers)
                attachment_info += f"\n**Stickers:** {sticker_names}"

            # Add embeds/reactions
            extras = []
            if obj.embeds:
                extras.append(f"{len(obj.embeds)} embed(s)")
            if obj.reactions:
                extras.append(f"{len(obj.reactions)} reaction(s)")
            if obj.mentions:
                extras.append(f"{len(obj.mentions)} mention(s)")
            if obj.reference:
                extras.append("Reply")

            extras_str = f"\n**Extras:** {', '.join(extras)}" if extras else ""

            return (
                f"📨 **Author:** {obj.author.mention} ({obj.author.name})\n"
                f"**Channel:** {obj.channel.mention if hasattr(obj.channel, 'mention') else obj.channel}\n"
                f"**Sent:** {created}\n"
                f"**Content:** {content}{attachment_info}{extras_str}\n"
                f"**Message ID:** `{obj.id}`\n"
                f"**[Jump to Message]({obj.jump_url})**"
            )
        elif isinstance(obj, discord.Emoji):
            return f"**Emoji:** {obj} (`{obj.id}`)\n**Name:** {obj.name}\n**Animated:** {obj.animated}"
        elif isinstance(obj, discord.Invite):
            return (
                f"**Code:** {obj.code}\n"
                f"**Channel:** {obj.channel}\n"
                f"**Inviter:** {obj.inviter or 'Unknown'}\n"
                f"**Uses:** {obj.uses or 0}/{obj.max_uses or '∞'}"
            )
        elif isinstance(obj, discord.Integration):
            return f"**Name:** {obj.name} (`{obj.id}`)\n**Type:** {obj.type}\n**Enabled:** {obj.enabled}"
        elif isinstance(obj, discord.Thread):
            return (
                f"**Thread:** {obj.mention} (`{obj.id}`)\n"
                f"**Parent:** {obj.parent.mention if obj.parent else 'Unknown'}\n"
                f"**Archived:** {obj.archived}"
            )
        elif isinstance(obj, discord.StageInstance):
            return f"**Topic:** {obj.topic}\n**Channel:** <#{obj.channel_id}>"
        elif isinstance(obj, discord.ScheduledEvent):
            return (
                f"**Event:** {obj.name}\n"
                f"**Location:** {obj.location or 'Unknown'}\n"
                f"**Start:** {obj.start_time.strftime('%Y-%m-%d %H:%M')}"
            )
        elif isinstance(obj, discord.AutoModRule):
            return f"**Rule:** {obj.name} (`{obj.id}`)\n**Enabled:** {obj.enabled}\n**Actions:** {len(obj.actions)}"
        elif isinstance(obj, discord.AutoModAction):
            return f"**Action:** {obj.type}\n**Rule:** <@{obj.rule_id}>"
        elif isinstance(obj, discord.Interaction):
            return (
                f"**User:** {obj.user.mention}\n"
                f"**Type:** {obj.type}\n"
                f"**Command:** {obj.command.name if obj.command else 'Unknown'}"
            )
        elif isinstance(obj, discord.VoiceState):
            channel = obj.channel.mention if obj.channel else "None"
            return (
                f"**Channel:** {channel}\n"
                f"**Muted:** {obj.mute} | **Deafened:** {obj.deaf}\n"
                f"**Streaming:** {obj.self_stream} | **Video:** {obj.self_video}"
            )
        else:
            return f"`{type(obj).__name__}`: {str(obj)[:200]}"

    async def _format_object_compact(self, obj: Any) -> str:
        """Format an object into a compact string."""
        if isinstance(obj, (discord.User, discord.Member)):
            return f"{obj.mention} ({obj.id})"
        elif isinstance(obj, discord.Guild):
            return f"{obj.name} ({obj.id})"
        elif isinstance(obj, (discord.TextChannel, discord.VoiceChannel)):
            return f"#{obj.name} ({obj.id})"
        elif isinstance(obj, discord.Role):
            return f"{obj.mention}"
        elif isinstance(obj, discord.Message):
            return f"Message {obj.id} by {obj.author}"
        else:
            return str(obj)[:100]

    async def _serialize_object(self, obj: Any) -> Any:
        """Serialize an object for JSON output."""
        if isinstance(obj, (discord.User, discord.Member, discord.Guild, discord.Role)):
            return {"id": obj.id, "name": getattr(obj, "name", str(obj)), "type": type(obj).__name__}
        elif isinstance(obj, (discord.TextChannel, discord.VoiceChannel)):
            return {"id": obj.id, "name": obj.name, "type": type(obj).__name__}
        elif isinstance(obj, discord.Message):
            return {
                "id": obj.id,
                "author_id": obj.author.id,
                "content": obj.content[:500],
                "channel_id": obj.channel.id,
            }
        elif hasattr(obj, "id"):
            return {"id": obj.id, "type": type(obj).__name__}
        else:
            return str(obj)[:200]

    # ═══════════════════════════════════════════════════════════════════════
    # Commands
    # ═══════════════════════════════════════════════════════════════════════

    @commands.group(name="rlog", aliases=["rubylog"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def rlog(self, ctx: commands.Context) -> None:
        """RubyLogging - Ultimate Discord event logging system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @rlog.command(name="channel")
    async def rlog_channel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Set the logging channel."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"✅ Logging channel set to {channel.mention}")

    @rlog.command(name="enable")
    async def rlog_enable(self, ctx: commands.Context, *events: str) -> None:
        """Enable specific events for logging.

        Use `all` to enable all events in a category.
        Example: `[p]rlog enable message_delete member_join`
        Example: `[p]rlog enable all:members` to enable all member events
        """
        if not events:
            await ctx.send("❌ Please specify at least one event or category.")
            return

        guild_config = self.config.guild(ctx.guild)
        enabled = await guild_config.enabled_events()
        added = []

        for event in events:
            if event.startswith("all:"):
                # Enable all events in category
                category = event.split(":", 1)[1]
                if category in EVENTS:
                    for cat_event in EVENTS[category]:
                        if cat_event not in enabled:
                            enabled.append(cat_event)
                            added.append(cat_event)
                else:
                    await ctx.send(f"❌ Unknown category: `{category}`")
                    return
            else:
                # Enable specific event
                found = False
                for category, cat_events in EVENTS.items():
                    if event in cat_events:
                        if event not in enabled:
                            enabled.append(event)
                            added.append(event)
                        found = True
                        break
                if not found:
                    await ctx.send(f"❌ Unknown event: `{event}`")
                    return

        await guild_config.enabled_events.set(enabled)

        if added:
            await ctx.send(f"✅ Enabled {len(added)} event(s): {humanize_list([f'`{e}`' for e in added])}")
        else:
            await ctx.send("ℹ️ All specified events were already enabled.")

    @rlog.command(name="disable")
    async def rlog_disable(self, ctx: commands.Context, *events: str) -> None:
        """Disable specific events.

        Example: `[p]rlog disable message_delete`
        Example: `[p]rlog disable all:messages` to disable all message events
        """
        if not events:
            await ctx.send("❌ Please specify at least one event or category.")
            return

        guild_config = self.config.guild(ctx.guild)
        enabled = await guild_config.enabled_events()
        removed = []

        for event in events:
            if event.startswith("all:"):
                # Disable all events in category
                category = event.split(":", 1)[1]
                if category in EVENTS:
                    for cat_event in EVENTS[category]:
                        if cat_event in enabled:
                            enabled.remove(cat_event)
                            removed.append(cat_event)
                else:
                    await ctx.send(f"❌ Unknown category: `{category}`")
                    return
            else:
                # Disable specific event
                if event in enabled:
                    enabled.remove(event)
                    removed.append(event)

        await guild_config.enabled_events.set(enabled)

        if removed:
            await ctx.send(f"✅ Disabled {len(removed)} event(s): {humanize_list([f'`{e}`' for e in removed])}")
        else:
            await ctx.send("ℹ️ None of the specified events were enabled.")

    @rlog.command(name="list")
    async def rlog_list(self, ctx: commands.Context, category: Optional[str] = None) -> None:
        """List all available events, optionally filtered by category."""
        if category and category not in EVENTS:
            await ctx.send(f"❌ Unknown category: `{category}`\nAvailable: {humanize_list([f'`{c}`' for c in EVENTS.keys()])}")
            return

        enabled = await self.config.guild(ctx.guild).enabled_events()

        output = []
        categories = {category: EVENTS[category]} if category else EVENTS

        for cat, events in categories.items():
            output.append(f"\n**{cat.upper()}** ({len(events)} events):")
            for event in sorted(events):
                status = "✅" if event in enabled else "⬜"
                output.append(f"  {status} `{event}`")

        for page in pagify("\n".join(output), delims=["\n"], page_length=1900):
            await ctx.send(page)

    @rlog.command(name="categories")
    async def rlog_categories(self, ctx: commands.Context) -> None:
        """Show all event categories and their event counts."""
        enabled = await self.config.guild(ctx.guild).enabled_events()

        lines = ["**📋 Event Categories**\n"]
        for category, events in EVENTS.items():
            enabled_count = sum(1 for e in events if e in enabled)
            total = len(events)
            status = "🟢" if enabled_count > 0 else "⬜"
            lines.append(f"{status} **{category.title()}**: {enabled_count}/{total} events enabled")

        await ctx.send("\n".join(lines))

    @rlog.command(name="format")
    async def rlog_format(self, ctx: commands.Context, format_type: str) -> None:
        """Set the log format: detailed, compact, or json."""
        format_type = format_type.lower()
        if format_type not in ["detailed", "compact", "json"]:
            await ctx.send("❌ Invalid format. Choose: `detailed`, `compact`, or `json`")
            return

        await self.config.guild(ctx.guild).format.set(format_type)
        await ctx.send(f"✅ Log format set to **{format_type}**")

    @rlog.command(name="ignorebots")
    async def rlog_ignorebots(self, ctx: commands.Context, enabled: bool) -> None:
        """Toggle ignoring events from bots."""
        await self.config.guild(ctx.guild).ignore_bots.set(enabled)
        status = "enabled" if enabled else "disabled"
        await ctx.send(f"✅ Bot filtering **{status}**")

    @rlog.command(name="ignoreuser")
    async def rlog_ignoreuser(
        self, ctx: commands.Context, user: discord.User, action: str = "add"
    ) -> None:
        """Add or remove a user from the ignore list."""
        guild_config = self.config.guild(ctx.guild)
        ignore_list = await guild_config.ignore_users()

        if action.lower() == "add":
            if user.id not in ignore_list:
                ignore_list.append(user.id)
                await guild_config.ignore_users.set(ignore_list)
                await ctx.send(f"✅ Now ignoring events from {user.mention}")
            else:
                await ctx.send(f"ℹ️ {user.mention} is already being ignored.")
        elif action.lower() == "remove":
            if user.id in ignore_list:
                ignore_list.remove(user.id)
                await guild_config.ignore_users.set(ignore_list)
                await ctx.send(f"✅ No longer ignoring events from {user.mention}")
            else:
                await ctx.send(f"ℹ️ {user.mention} was not being ignored.")
        else:
            await ctx.send("❌ Action must be `add` or `remove`")

    @rlog.command(name="ignorechannel")
    async def rlog_ignorechannel(
        self, ctx: commands.Context, channel: discord.TextChannel, action: str = "add"
    ) -> None:
        """Add or remove a channel from the ignore list."""
        guild_config = self.config.guild(ctx.guild)
        ignore_list = await guild_config.ignore_channels()

        if action.lower() == "add":
            if channel.id not in ignore_list:
                ignore_list.append(channel.id)
                await guild_config.ignore_channels.set(ignore_list)
                await ctx.send(f"✅ Now ignoring events from {channel.mention}")
            else:
                await ctx.send(f"ℹ️ {channel.mention} is already being ignored.")
        elif action.lower() == "remove":
            if channel.id in ignore_list:
                ignore_list.remove(channel.id)
                await guild_config.ignore_channels.set(ignore_list)
                await ctx.send(f"✅ No longer ignoring events from {channel.mention}")
            else:
                await ctx.send(f"ℹ️ {channel.mention} was not being ignored.")
        else:
            await ctx.send("❌ Action must be `add` or `remove`")

    @rlog.command(name="settings")
    async def rlog_settings(self, ctx: commands.Context) -> None:
        """Show current logging configuration."""
        config = self.config.guild(ctx.guild)

        channel_id = await config.log_channel()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        enabled_events = await config.enabled_events()
        format_type = await config.format()
        ignore_bots = await config.ignore_bots()
        ignore_users = await config.ignore_users()
        ignore_channels = await config.ignore_channels()

        # Attachment settings
        log_attachments = await config.log_attachments()
        log_stickers = await config.log_stickers()
        show_previews = await config.show_attachment_previews()
        track_deleted = await config.track_deleted_attachments()
        max_previews = await config.max_preview_attachments()

        embed = discord.Embed(
            title="🔧 RubyLogging Settings",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="Log Channel",
            value=channel.mention if channel else "❌ Not set",
            inline=False,
        )

        embed.add_field(
            name="Enabled Events",
            value=f"{len(enabled_events)} events" if enabled_events else "None",
            inline=True,
        )

        embed.add_field(name="Format", value=format_type.title(), inline=True)
        embed.add_field(name="Ignore Bots", value="✅" if ignore_bots else "❌", inline=True)

        embed.add_field(
            name="Ignored Users",
            value=f"{len(ignore_users)} users" if ignore_users else "None",
            inline=True,
        )

        embed.add_field(
            name="Ignored Channels",
            value=f"{len(ignore_channels)} channels" if ignore_channels else "None",
            inline=True,
        )

        # Attachment settings
        attachment_status = (
            f"{'✅' if log_attachments else '❌'} Logging\n"
            f"{'✅' if log_stickers else '❌'} Stickers\n"
            f"{'✅' if show_previews else '❌'} Previews\n"
            f"{'✅' if track_deleted else '❌'} Track Deleted\n"
            f"📊 Max Previews: {max_previews}\n"
            f"💾 Cached: {len(self._attachment_cache)}"
        )
        embed.add_field(
            name="📎 Attachments",
            value=attachment_status,
            inline=True,
        )

        # Event breakdown by category
        category_stats = []
        for category, events in EVENTS.items():
            enabled_count = sum(1 for e in events if e in enabled_events)
            if enabled_count > 0:
                category_stats.append(f"**{category.title()}**: {enabled_count}/{len(events)}")

        if category_stats:
            embed.add_field(
                name="Category Breakdown",
                value="\n".join(category_stats),
                inline=False,
            )

        await ctx.send(embed=embed)

    @rlog.command(name="quickstart")
    async def rlog_quickstart(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Quick setup: enable common events and set log channel."""
        # Common events to enable
        common_events = [
            "member_join",
            "member_remove",
            "member_ban",
            "member_unban",
            "message_delete",
            "message_edit",
            "guild_channel_create",
            "guild_channel_delete",
            "guild_role_create",
            "guild_role_delete",
            "voice_state_update",
        ]

        guild_config = self.config.guild(ctx.guild)
        await guild_config.log_channel.set(channel.id)
        await guild_config.enabled_events.set(common_events)
        await guild_config.ignore_bots.set(True)

        # Enable attachment logging by default
        await guild_config.log_attachments.set(True)
        await guild_config.log_stickers.set(True)
        await guild_config.show_attachment_previews.set(True)
        await guild_config.track_deleted_attachments.set(True)

        await ctx.send(
            f"✅ **Quick setup complete!**\n"
            f"• Log channel: {channel.mention}\n"
            f"• Enabled {len(common_events)} common events\n"
            f"• Bot events ignored\n"
            f"• Attachment logging enabled (images, GIFs, videos)\n"
            f"• Deleted attachment tracking enabled\n\n"
            f"Use `{ctx.prefix}rlog list` to see all events and customize further.\n"
            f"Use `{ctx.prefix}rlog attachments` to configure media logging."
        )

    @rlog.group(name="attachments", aliases=["attach", "files"])
    async def rlog_attachments(self, ctx: commands.Context) -> None:
        """Attachment and media logging settings."""
        if ctx.invoked_subcommand is None:
            config = self.config.guild(ctx.guild)
            log_attachments = await config.log_attachments()
            log_stickers = await config.log_stickers()
            show_previews = await config.show_attachment_previews()
            track_deleted = await config.track_deleted_attachments()
            max_previews = await config.max_preview_attachments()

            status = (
                f"**📎 Attachment Logging**\n"
                f"{'✅' if log_attachments else '❌'} Log Attachments: {'On' if log_attachments else 'Off'}\n"
                f"{'✅' if log_stickers else '❌'} Log Stickers: {'On' if log_stickers else 'Off'}\n"
                f"{'✅' if show_previews else '❌'} Show Previews: {'On' if show_previews else 'Off'}\n"
                f"{'✅' if track_deleted else '❌'} Track Deleted: {'On' if track_deleted else 'Off'}\n"
                f"📊 Max Previews: {max_previews}\n\n"
                f"**Cache Status:** {len(self._attachment_cache)} messages cached"
            )
            await ctx.send(status)

    @rlog_attachments.command(name="toggle")
    async def rlog_attach_toggle(self, ctx: commands.Context) -> None:
        """Toggle attachment logging on/off."""
        current = await self.config.guild(ctx.guild).log_attachments()
        new_val = not current
        await self.config.guild(ctx.guild).log_attachments.set(new_val)
        status = "enabled" if new_val else "disabled"
        await ctx.send(f"✅ Attachment logging **{status}**")

    @rlog_attachments.command(name="stickers")
    async def rlog_attach_stickers(self, ctx: commands.Context) -> None:
        """Toggle sticker logging on/off."""
        current = await self.config.guild(ctx.guild).log_stickers()
        new_val = not current
        await self.config.guild(ctx.guild).log_stickers.set(new_val)
        status = "enabled" if new_val else "disabled"
        await ctx.send(f"✅ Sticker logging **{status}**")

    @rlog_attachments.command(name="previews")
    async def rlog_attach_previews(self, ctx: commands.Context) -> None:
        """Toggle attachment preview embeds on/off."""
        current = await self.config.guild(ctx.guild).show_attachment_previews()
        new_val = not current
        await self.config.guild(ctx.guild).show_attachment_previews.set(new_val)
        status = "enabled" if new_val else "disabled"
        await ctx.send(
            f"✅ Attachment previews **{status}**\n"
            f"Images/GIFs will {'be shown' if new_val else 'not be shown'} in log embeds."
        )

    @rlog_attachments.command(name="tracking")
    async def rlog_attach_tracking(self, ctx: commands.Context) -> None:
        """Toggle deleted attachment tracking on/off.

        When enabled, the bot caches attachments from all messages so they can
        be logged when messages are deleted. Slight memory overhead.
        """
        current = await self.config.guild(ctx.guild).track_deleted_attachments()
        new_val = not current
        await self.config.guild(ctx.guild).track_deleted_attachments.set(new_val)
        status = "enabled" if new_val else "disabled"

        if new_val:
            await ctx.send(
                f"✅ Deleted attachment tracking **{status}**\n"
                f"The bot will now cache attachments to log them when messages are deleted.\n"
                f"**Note:** Only attachments from messages sent *after* enabling this will be tracked."
            )
        else:
            # Clear cache when disabled
            self._attachment_cache.clear()
            await ctx.send(
                f"✅ Deleted attachment tracking **{status}**\n"
                f"Cleared {len(self._attachment_cache)} cached attachments."
            )

    @rlog_attachments.command(name="maxpreviews")
    async def rlog_attach_maxpreviews(self, ctx: commands.Context, count: int) -> None:
        """Set maximum number of attachment previews to show (1-10)."""
        count = max(1, min(10, count))
        await self.config.guild(ctx.guild).max_preview_attachments.set(count)
        await ctx.send(f"✅ Max attachment previews set to **{count}**")

    @rlog_attachments.command(name="clearcache")
    @commands.admin_or_permissions(manage_guild=True)
    async def rlog_attach_clearcache(self, ctx: commands.Context) -> None:
        """Clear the attachment cache (admin only)."""
        count = len(self._attachment_cache)
        self._attachment_cache.clear()
        await ctx.send(f"✅ Cleared **{count}** cached attachments from memory.")

    @rlog.command(name="reset")
    async def rlog_reset(self, ctx: commands.Context) -> None:
        """Reset all logging settings to default."""
        await self.config.guild(ctx.guild).clear()
        self._attachment_cache.clear()
        await ctx.send("✅ All logging settings have been reset.")
