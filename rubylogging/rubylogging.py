"""
RubyLogging - The most comprehensive Discord event logging system.

Tracks every single Discord event with individual toggles, filtering, and formatting.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

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
        }

        self.config.register_guild(**default_guild)

        # Event handler registry
        self._handlers = {}
        self._register_all_handlers()

    def _register_all_handlers(self) -> None:
        """Dynamically register all event handlers."""
        for category, events in EVENTS.items():
            for event in events:
                handler_name = f"_log_{event}"

                # Create dynamic handler
                async def handler(*args, _event=event, _category=category, **kwargs):
                    await self._process_event(_event, _category, *args, **kwargs)

                # Store and register
                setattr(self, handler_name, handler)
                self.bot.add_listener(handler, f"on_{event}")
                self._handlers[event] = handler

    async def cog_unload(self) -> None:
        """Remove all registered event listeners."""
        for event, handler in self._handlers.items():
            self.bot.remove_listener(handler, f"on_{event}")

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
    ) -> discord.Embed:
        """Format event data into an embed."""
        config = self.config.guild(guild)
        format_type = await config.format()
        color_coded = await config.color_coded()
        include_timestamp = await config.include_timestamp()

        # Color mapping by category
        colors = {
            "connection": discord.Color.blue(),
            "gateway": discord.Color.dark_grey(),
            "guilds": discord.Color.purple(),
            "channels": discord.Color.green(),
            "members": discord.Color.orange(),
            "messages": discord.Color.gold(),
            "voice": discord.Color.blurple(),
            "stage": discord.Color.magenta(),
            "threads": discord.Color.teal(),
            "interactions": discord.Color.brand_red(),
            "integrations": discord.Color.dark_gold(),
            "invites": discord.Color.light_grey(),
            "typing": discord.Color.lighter_grey(),
            "automod": discord.Color.red(),
            "scheduled_events": discord.Color.dark_purple(),
            "app_commands": discord.Color.brand_green(),
            "entitlements": discord.Color.yellow(),
            "audit_log": discord.Color.dark_red(),
        }

        color = colors.get(category, discord.Color.greyple()) if color_coded else discord.Color.greyple()

        embed = discord.Embed(
            title=f"📋 {event_name.replace('_', ' ').title()}",
            color=color,
        )

        if include_timestamp:
            embed.timestamp = datetime.now(timezone.utc)

        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Event", value=f"`on_{event_name}`", inline=True)

        # Format event data based on format type
        if format_type == "detailed":
            await self._add_detailed_fields(embed, event_name, args, kwargs)
        elif format_type == "compact":
            await self._add_compact_fields(embed, event_name, args, kwargs)
        elif format_type == "json":
            await self._add_json_fields(embed, event_name, args, kwargs)

        return embed

    async def _add_detailed_fields(
        self, embed: discord.Embed, event_name: str, args: List[Any], kwargs: Dict[str, Any]
    ) -> None:
        """Add detailed field information to embed."""
        # Parse arguments into readable format
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
        """Format an object into a readable string."""
        if isinstance(obj, discord.User):
            return f"**User:** {obj.mention} (`{obj.id}`)\n**Name:** {obj.name}\n**Bot:** {obj.bot}"
        elif isinstance(obj, discord.Member):
            roles = ", ".join(r.mention for r in obj.roles[1:]) or "None"
            return (
                f"**Member:** {obj.mention} (`{obj.id}`)\n"
                f"**Name:** {obj.name}\n"
                f"**Nickname:** {obj.nick or 'None'}\n"
                f"**Roles:** {roles}\n"
                f"**Joined:** {obj.joined_at.strftime('%Y-%m-%d %H:%M') if obj.joined_at else 'Unknown'}"
            )
        elif isinstance(obj, discord.Guild):
            return (
                f"**Guild:** {obj.name} (`{obj.id}`)\n"
                f"**Owner:** <@{obj.owner_id}>\n"
                f"**Members:** {obj.member_count}"
            )
        elif isinstance(obj, discord.TextChannel):
            return f"**Channel:** {obj.mention} (`{obj.id}`)\n**Category:** {obj.category or 'None'}"
        elif isinstance(obj, discord.VoiceChannel):
            return f"**Voice Channel:** {obj.name} (`{obj.id}`)\n**User Limit:** {obj.user_limit or 'Unlimited'}"
        elif isinstance(obj, discord.Role):
            return f"**Role:** {obj.mention} (`{obj.id}`)\n**Color:** {obj.color}\n**Position:** {obj.position}"
        elif isinstance(obj, discord.Message):
            content = obj.content[:100] + "..." if len(obj.content) > 100 else obj.content
            return (
                f"**Author:** {obj.author.mention}\n"
                f"**Channel:** {obj.channel.mention if hasattr(obj.channel, 'mention') else obj.channel}\n"
                f"**Content:** {content}\n"
                f"**ID:** `{obj.id}`"
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

        await ctx.send(
            f"✅ **Quick setup complete!**\n"
            f"• Log channel: {channel.mention}\n"
            f"• Enabled {len(common_events)} common events\n"
            f"• Bot events ignored\n\n"
            f"Use `{ctx.prefix}rlog list` to see all events and customize further."
        )

    @rlog.command(name="reset")
    async def rlog_reset(self, ctx: commands.Context) -> None:
        """Reset all logging settings to default."""
        await self.config.guild(ctx.guild).clear()
        await ctx.send("✅ All logging settings have been reset.")
