"""VoiceMeister v1.0.0 — Ultimate temporary voice channel management.

Features: Join-to-Create, persistent control panel with 20+ buttons,
name templates, game detection, logging, blacklist/whitelist, cooldowns.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

import discord
from redbot.core import Config, commands, checks
from redbot.core.bot import Red

from .utils import (
    Clr, ok_embed, err_embed, info_embed, warn_embed,
    render_name, build_panel_embed, log_embed, safe_send, ts_now,
)
from .views import VoiceMeisterPanel


class VoiceMeister(commands.Cog):
    """🎙️ VoiceMeister — Ultimate temporary voice channel management."""

    __version__ = "1.0.0"
    __author__ = "EveCogs"

    # ══════════════════════════════════════════════════════════════════════════
    # INIT & CONFIG
    # ══════════════════════════════════════════════════════════════════════════

    GUILD_DEFAULTS = {
        "creators": {},          # {channel_id_str: {category_id, name_template, user_limit, bitrate, ...}}
        "log_channel": None,     # channel ID for logging
        "temp_channels": {},     # {channel_id_str: owner_id}
        "channel_bans": {},      # {channel_id_str: [user_id, ...]}
        "blacklisted_users": [], # user IDs blocked from creating
        "whitelisted_roles": [], # role IDs that bypass blacklist
        "max_channels_per_user": 1,
        "cooldown_seconds": 10,
        "auto_rename_game": False,
        "default_name_template": "🔊 {user}'s Channel",
        "default_user_limit": 0,
        "default_bitrate": 64000,
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7283649152, force_registration=True)
        self.config.register_guild(**self.GUILD_DEFAULTS)

        # Runtime caches (populated on cog_load)
        self.temp_channels: Dict[int, int] = {}     # {vc_id: owner_id}
        self.creator_channels: Dict[int, dict] = {} # {vc_id: settings}
        self.cooldowns: Dict[int, float] = {}        # {user_id: last_create_timestamp}
        self._panel_view = VoiceMeisterPanel()
        self._bg_tasks: list[asyncio.Task] = []

    async def cog_load(self):
        """Load persistent data and register the panel view."""
        self.bot.add_view(self._panel_view)
        await self._load_all_guilds()
        self._bg_tasks.append(asyncio.create_task(self._cleanup_loop()))
        # Always start the game rename loop — it checks per-guild config each cycle
        self._bg_tasks.append(asyncio.create_task(self._game_rename_loop()))

    async def cog_unload(self):
        for task in self._bg_tasks:
            task.cancel()

    # ══════════════════════════════════════════════════════════════════════════
    # DATA LOADING & SAVING
    # ══════════════════════════════════════════════════════════════════════════

    async def _load_all_guilds(self):
        """Load temp_channels and creators from config into memory caches."""
        all_guilds = await self.config.all_guilds()
        for guild_id, data in all_guilds.items():
            for ch_id_str, owner_id in data.get("temp_channels", {}).items():
                self.temp_channels[int(ch_id_str)] = owner_id
            for ch_id_str, settings in data.get("creators", {}).items():
                self.creator_channels[int(ch_id_str)] = settings

    async def _save_temp_channels(self):
        """Persist the temp_channels cache back to config."""
        # Group by guild
        guild_map: Dict[int, Dict[str, int]] = {}
        for ch_id, owner_id in self.temp_channels.items():
            channel = self.bot.get_channel(ch_id)
            if channel and channel.guild:
                gid = channel.guild.id
                guild_map.setdefault(gid, {})[str(ch_id)] = owner_id

        # Clear guilds that no longer have temp channels
        all_guilds = await self.config.all_guilds()
        for gid in all_guilds:
            if gid not in guild_map:
                await self.config.guild_from_id(gid).temp_channels.set({})

        # Save guilds that have temp channels
        for gid, data in guild_map.items():
            await self.config.guild_from_id(gid).temp_channels.set(data)

    async def _add_channel_ban(self, guild_id: int, channel_id: int, user_id: int):
        """Add a user to a channel's ban list in config."""
        async with self.config.guild_from_id(guild_id).channel_bans() as bans:
            key = str(channel_id)
            if key not in bans:
                bans[key] = []
            if user_id not in bans[key]:
                bans[key].append(user_id)

    # ══════════════════════════════════════════════════════════════════════════
    # LOGGING
    # ══════════════════════════════════════════════════════════════════════════

    async def _log_action(
        self,
        guild: discord.Guild,
        action: str,
        *,
        member: discord.Member | discord.User,
        channel: discord.VoiceChannel | None = None,
        detail: str = "",
    ):
        """Send a log embed to the configured log channel."""
        log_ch_id = await self.config.guild(guild).log_channel()
        if not log_ch_id:
            return
        log_ch = guild.get_channel(log_ch_id)
        if log_ch is None:
            return
        try:
            await log_ch.send(embed=log_embed(action, member=member, channel=channel, detail=detail))
        except discord.HTTPException:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # BACKGROUND TASKS
    # ══════════════════════════════════════════════════════════════════════════

    async def _cleanup_loop(self):
        """Periodically clean up orphaned temp channels (empty for >5s)."""
        await self.bot.wait_until_ready()
        while True:
            try:
                to_remove = []
                for ch_id, owner_id in list(self.temp_channels.items()):
                    channel = self.bot.get_channel(ch_id)
                    if channel is None:
                        to_remove.append(ch_id)
                        continue
                    if len(channel.members) == 0:
                        to_remove.append(ch_id)
                        try:
                            await channel.delete(reason="VoiceMeister: auto-cleanup (empty)")
                        except discord.HTTPException:
                            pass

                if to_remove:
                    for ch_id in to_remove:
                        self.temp_channels.pop(ch_id, None)
                    await self._save_temp_channels()

            except Exception:
                pass
            await asyncio.sleep(15)

    async def _game_rename_loop(self):
        """Rename channels based on the owner's current game activity."""
        await self.bot.wait_until_ready()
        while True:
            try:
                for ch_id, owner_id in list(self.temp_channels.items()):
                    channel = self.bot.get_channel(ch_id)
                    if channel is None or not channel.guild:
                        continue

                    auto_rename = await self.config.guild(channel.guild).auto_rename_game()
                    if not auto_rename:
                        continue

                    owner = channel.guild.get_member(owner_id)
                    if owner is None:
                        continue

                    game = None
                    for activity in owner.activities:
                        if activity.type == discord.ActivityType.playing:
                            game = activity.name
                            break

                    if game:
                        new_name = f"🎮 {game}"
                    else:
                        new_name = f"🔊 {owner.display_name}'s Channel"

                    if channel.name != new_name:
                        try:
                            await channel.edit(name=new_name[:100],
                                               reason="VoiceMeister: game activity rename")
                        except discord.HTTPException:
                            pass

            except Exception:
                pass
            await asyncio.sleep(30)

    # ══════════════════════════════════════════════════════════════════════════
    # VOICE STATE LISTENER — THE CORE ENGINE
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # ── User joined a creator channel → spawn temp channel ─────────
        if after.channel and after.channel.id in self.creator_channels:
            await self._handle_join_creator(member, after.channel)

        # ── User left a temp channel → maybe clean up ──────────────────
        if before.channel and before.channel.id in self.temp_channels:
            if len(before.channel.members) == 0:
                ch_id = before.channel.id
                self.temp_channels.pop(ch_id, None)
                await self._save_temp_channels()
                try:
                    await before.channel.delete(reason="VoiceMeister: empty channel cleanup")
                except discord.HTTPException:
                    pass
                await self._log_action(
                    member.guild, "🗑️ Auto-Deleted (Empty)",
                    member=member, channel=before.channel,
                )

    async def _handle_join_creator(self, member: discord.Member, creator: discord.VoiceChannel):
        """Spawn a new temp voice channel for the member."""
        guild = member.guild
        settings = self.creator_channels[creator.id]

        # ── Blacklist check ────────────────────────────────────────────
        blacklisted = await self.config.guild(guild).blacklisted_users()
        if member.id in blacklisted:
            whitelisted_roles = await self.config.guild(guild).whitelisted_roles()
            if not any(r.id in whitelisted_roles for r in member.roles):
                try:
                    await member.move_to(None, reason="VoiceMeister: blacklisted user")
                except discord.HTTPException:
                    pass
                return

        # ── Cooldown check ─────────────────────────────────────────────
        cooldown = await self.config.guild(guild).cooldown_seconds()
        now = time.time()
        last = self.cooldowns.get(member.id, 0)
        if now - last < cooldown:
            try:
                await member.move_to(None, reason="VoiceMeister: cooldown")
            except discord.HTTPException:
                pass
            return

        # ── Max channels per user check ────────────────────────────────
        max_ch = await self.config.guild(guild).max_channels_per_user()
        user_channels = sum(1 for oid in self.temp_channels.values() if oid == member.id)
        if user_channels >= max_ch:
            # Move them to their existing channel instead
            for ch_id, oid in self.temp_channels.items():
                if oid == member.id:
                    existing = guild.get_channel(ch_id)
                    if existing:
                        try:
                            await member.move_to(existing, reason="VoiceMeister: max channels reached")
                        except discord.HTTPException:
                            pass
                        return
            try:
                await member.move_to(None, reason="VoiceMeister: max channels reached")
            except discord.HTTPException:
                pass
            return

        self.cooldowns[member.id] = now

        # ── Resolve settings ───────────────────────────────────────────
        category_id = settings.get("category_id")
        category = guild.get_channel(category_id) if category_id else creator.category
        name_template = settings.get("name_template") or await self.config.guild(guild).default_name_template()
        user_limit = settings.get("user_limit", 0)
        if user_limit == -1:  # -1 means "use guild default"
            user_limit = await self.config.guild(guild).default_user_limit()
        bitrate = settings.get("bitrate", 0)
        if bitrate <= 0:
            bitrate = await self.config.guild(guild).default_bitrate()

        # Clamp bitrate
        bitrate = max(8000, min(bitrate, guild.bitrate_limit))

        # Count existing channels for this creator
        count = sum(
            1 for ch_id, _ in self.temp_channels.items()
            if self.bot.get_channel(ch_id) and
            self.bot.get_channel(ch_id).category == category
        ) + 1

        channel_name = render_name(name_template, member=member, count=count)

        # ── Create the channel ─────────────────────────────────────────
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                connect=True,
                view_channel=True,
            ),
            member: discord.PermissionOverwrite(
                connect=True,
                view_channel=True,
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True,
            ),
            guild.me: discord.PermissionOverwrite(
                connect=True,
                view_channel=True,
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True,
            ),
        }

        try:
            new_vc = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                user_limit=user_limit if user_limit > 0 else 0,
                bitrate=bitrate,
                overwrites=overwrites,
                reason=f"VoiceMeister: created for {member}",
            )
        except discord.HTTPException:
            return

        # Track it
        self.temp_channels[new_vc.id] = member.id
        await self._save_temp_channels()

        # Move the member into the new channel
        try:
            await member.move_to(new_vc, reason="VoiceMeister: moving to new channel")
        except discord.HTTPException:
            # If we can't move them, clean up
            self.temp_channels.pop(new_vc.id, None)
            await self._save_temp_channels()
            try:
                await new_vc.delete(reason="VoiceMeister: failed to move user")
            except discord.HTTPException:
                pass
            return

        await self._log_action(
            guild, "🔊 Channel Created",
            member=member, channel=new_vc,
            detail=f"From creator: {creator.mention}",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ADMIN COMMANDS — voicemeister group
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="voicemeister", aliases=["vm"])
    @commands.guild_only()
    async def voicemeister(self, ctx: commands.Context):
        """🎙️ VoiceMeister — Temporary voice channel management."""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🎙️ VoiceMeister v1.0.0",
                description=(
                    "**The ultimate temporary voice channel system.**\n\n"
                    "Users join a **creator** channel → a personal voice channel spawns → "
                    "they control it via the **panel** or `/vc` commands.\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                colour=Clr.VOICE,
            )

            # Count active channels
            guild_channels = sum(
                1 for ch_id in self.temp_channels
                if (ch := self.bot.get_channel(ch_id)) and ch.guild.id == ctx.guild.id
            )
            guild_creators = sum(
                1 for ch_id in self.creator_channels
                if (ch := self.bot.get_channel(ch_id)) and ch.guild.id == ctx.guild.id
            )

            embed.add_field(name="📊 Status", value=(
                f"**Creators:** {guild_creators}\n"
                f"**Active channels:** {guild_channels}\n"
                f"**Version:** 1.0.0"
            ), inline=False)

            embed.add_field(name="⚡ Quick Start", value=(
                f"`{ctx.clean_prefix}vm setup` — Interactive wizard\n"
                f"`{ctx.clean_prefix}vm creator add #channel` — Add creator\n"
                f"`{ctx.clean_prefix}vm panel #channel` — Send panel\n"
                f"`{ctx.clean_prefix}vm settings` — View settings"
            ), inline=False)

            embed.add_field(name="🔗 User Commands", value=(
                f"`{ctx.clean_prefix}vc lock/unlock/hide/unhide`\n"
                f"`{ctx.clean_prefix}vc rename/limit/bitrate`\n"
                f"`{ctx.clean_prefix}vc kick/ban/permit/reject`\n"
                f"`{ctx.clean_prefix}vc claim/transfer/info/delete`"
            ), inline=False)

            embed.set_footer(text="VoiceMeister by EveCogs")
            await ctx.send(embed=embed)

    # ── Setup Wizard ───────────────────────────────────────────────────────

    @voicemeister.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_setup(self, ctx: commands.Context):
        """Interactive setup wizard for VoiceMeister."""
        embed = discord.Embed(
            title="🎙️ VoiceMeister Setup Wizard",
            description=(
                "I'll walk you through setting up VoiceMeister.\n\n"
                "**Step 1:** I'll create a Join-to-Create voice channel.\n"
                "**Step 2:** I'll create a category for temp channels.\n"
                "**Step 3:** I'll send the control panel.\n\n"
                "React with ✅ to begin or ❌ to cancel."
            ),
            colour=Clr.VOICE,
        )
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return (
                user == ctx.author
                and reaction.message.id == msg.id
                and str(reaction.emoji) in ("✅", "❌")
            )

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=60, check=check)
        except asyncio.TimeoutError:
            await msg.edit(embed=err_embed("Setup timed out."))
            return

        if str(reaction.emoji) == "❌":
            await msg.edit(embed=info_embed("Setup cancelled."))
            return

        # ── Step 1: Create category ────────────────────────────────────
        await msg.edit(embed=info_embed(
            "**Step 1/3:** Creating the VoiceMeister category and creator channel...",
            title="⏳ Setting up...",
        ))

        try:
            category = await ctx.guild.create_category(
                name="🎙️ VoiceMeister",
                reason="VoiceMeister setup wizard",
            )
            creator_vc = await ctx.guild.create_voice_channel(
                name="➕ Join to Create",
                category=category,
                reason="VoiceMeister setup wizard",
            )
        except discord.HTTPException as e:
            await msg.edit(embed=err_embed(f"Failed to create channels: {e}"))
            return

        # Register the creator
        creator_settings = {
            "category_id": category.id,
            "name_template": "🔊 {user}'s Channel",
            "user_limit": 0,
            "bitrate": 64000,
        }
        self.creator_channels[creator_vc.id] = creator_settings
        async with self.config.guild(ctx.guild).creators() as creators:
            creators[str(creator_vc.id)] = creator_settings

        # ── Step 2: Ask for panel channel ──────────────────────────────
        await msg.edit(embed=info_embed(
            f"✅ Created {category.mention} with {creator_vc.mention}.\n\n"
            "**Step 2/3:** Where should I send the control panel?\n"
            "Mention a text channel (e.g. #voice-panel) or type `here` for this channel.\n"
            "Type `skip` to skip the panel.",
            title="📍 Panel Channel",
        ))

        def msg_check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            response = await self.bot.wait_for("message", timeout=60, check=msg_check)
        except asyncio.TimeoutError:
            await msg.edit(embed=err_embed("Setup timed out."))
            return

        panel_channel = None
        if response.content.lower() == "skip":
            pass
        elif response.content.lower() == "here":
            panel_channel = ctx.channel
        elif response.channel_mentions:
            panel_channel = response.channel_mentions[0]

        try:
            await response.delete()
        except (discord.HTTPException, discord.Forbidden):
            pass

        # ── Step 3: Send panel ─────────────────────────────────────────
        if panel_channel:
            panel_embed = build_panel_embed(ctx.guild)
            try:
                await panel_channel.send(embed=panel_embed, view=self._panel_view)
            except discord.HTTPException as e:
                await msg.edit(embed=warn_embed(f"Couldn't send panel: {e}. You can send it manually with `{ctx.clean_prefix}vm panel`."))
                return

        # ── Step 3: Ask for log channel ────────────────────────────────
        await msg.edit(embed=info_embed(
            "**Step 3/3:** Where should I send logs?\n"
            "Mention a text channel or type `skip` to disable logging.",
            title="📋 Log Channel",
        ))

        try:
            response = await self.bot.wait_for("message", timeout=60, check=msg_check)
        except asyncio.TimeoutError:
            pass
        else:
            if response.channel_mentions:
                log_ch = response.channel_mentions[0]
                await self.config.guild(ctx.guild).log_channel.set(log_ch.id)

            try:
                await response.delete()
            except (discord.HTTPException, discord.Forbidden):
                pass

        # ── Done ───────────────────────────────────────────────────────
        final = discord.Embed(
            title="✅ VoiceMeister Setup Complete!",
            description=(
                f"**Creator channel:** {creator_vc.mention}\n"
                f"**Category:** {category.mention}\n"
                f"**Panel:** {'Sent to ' + panel_channel.mention if panel_channel else 'Skipped'}\n"
                f"**Logging:** {'Enabled' if await self.config.guild(ctx.guild).log_channel() else 'Disabled'}\n\n"
                f"Users can now join **{creator_vc.mention}** to get a personal voice channel!\n\n"
                f"Use `{ctx.clean_prefix}vm settings` to customize defaults."
            ),
            colour=Clr.SUCCESS,
        )
        await msg.edit(embed=final)

    # ── Creator Management ─────────────────────────────────────────────────

    @voicemeister.group(name="creator", aliases=["jtc"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_creator(self, ctx: commands.Context):
        """Manage Join-to-Create channels."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @vm_creator.command(name="add")
    async def vm_creator_add(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel,
        category: Optional[discord.CategoryChannel] = None,
    ):
        """Add a voice channel as a Join-to-Create creator.

        If no category is given, temp channels spawn in the same category.
        """
        if channel.id in self.creator_channels:
            await ctx.send(embed=err_embed(f"{channel.mention} is already a creator channel."))
            return

        settings = {
            "category_id": category.id if category else channel.category_id,
            "name_template": await self.config.guild(ctx.guild).default_name_template(),
            "user_limit": -1,  # use guild default
            "bitrate": 0,      # use guild default
        }
        self.creator_channels[channel.id] = settings
        async with self.config.guild(ctx.guild).creators() as creators:
            creators[str(channel.id)] = settings

        cat_mention = category.mention if category else (channel.category.mention if channel.category else "same category")
        await ctx.send(embed=ok_embed(
            f"Added {channel.mention} as a creator channel.\n"
            f"Temp channels will spawn in {cat_mention}."
        ))

    @vm_creator.command(name="remove", aliases=["delete"])
    async def vm_creator_remove(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """Remove a Join-to-Create creator channel."""
        if channel.id not in self.creator_channels:
            await ctx.send(embed=err_embed(f"{channel.mention} is not a creator channel."))
            return

        self.creator_channels.pop(channel.id, None)
        async with self.config.guild(ctx.guild).creators() as creators:
            creators.pop(str(channel.id), None)

        await ctx.send(embed=ok_embed(f"Removed {channel.mention} as a creator channel."))

    @vm_creator.command(name="list")
    async def vm_creator_list(self, ctx: commands.Context):
        """List all Join-to-Create channels."""
        guild_creators = {
            ch_id: s for ch_id, s in self.creator_channels.items()
            if ctx.guild.get_channel(ch_id)
        }
        if not guild_creators:
            await ctx.send(embed=info_embed("No creator channels configured."))
            return

        lines = []
        for ch_id, settings in guild_creators.items():
            ch = ctx.guild.get_channel(ch_id)
            cat = ctx.guild.get_channel(settings.get("category_id"))
            template = settings.get("name_template", "Default")
            lines.append(
                f"• {ch.mention} → Category: {cat.mention if cat else 'N/A'} | "
                f"Template: `{template}`"
            )

        embed = discord.Embed(
            title="🎙️ Creator Channels",
            description="\n".join(lines),
            colour=Clr.VOICE,
        )
        await ctx.send(embed=embed)

    @vm_creator.command(name="template")
    async def vm_creator_template(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel,
        *,
        template: str,
    ):
        """Set a name template for a specific creator.

        Variables: {user}, {game}, {count}, {custom}
        """
        if channel.id not in self.creator_channels:
            await ctx.send(embed=err_embed(f"{channel.mention} is not a creator channel."))
            return

        self.creator_channels[channel.id]["name_template"] = template
        async with self.config.guild(ctx.guild).creators() as creators:
            if str(channel.id) in creators:
                creators[str(channel.id)]["name_template"] = template

        await ctx.send(embed=ok_embed(f"Name template for {channel.mention} set to: `{template}`"))

    @vm_creator.command(name="userlimit", aliases=["limit"])
    async def vm_creator_limit(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel,
        limit: int,
    ):
        """Set default user limit for a creator (0 = unlimited, -1 = guild default)."""
        if channel.id not in self.creator_channels:
            await ctx.send(embed=err_embed(f"{channel.mention} is not a creator channel."))
            return

        self.creator_channels[channel.id]["user_limit"] = limit
        async with self.config.guild(ctx.guild).creators() as creators:
            if str(channel.id) in creators:
                creators[str(channel.id)]["user_limit"] = limit

        label = str(limit) if limit > 0 else ("guild default" if limit == -1 else "unlimited")
        await ctx.send(embed=ok_embed(f"User limit for {channel.mention} set to **{label}**."))

    @vm_creator.command(name="bitrate")
    async def vm_creator_bitrate(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel,
        bitrate: int,
    ):
        """Set default bitrate (kbps) for a creator. 0 = guild default."""
        if channel.id not in self.creator_channels:
            await ctx.send(embed=err_embed(f"{channel.mention} is not a creator channel."))
            return

        self.creator_channels[channel.id]["bitrate"] = bitrate * 1000 if bitrate > 0 else 0
        async with self.config.guild(ctx.guild).creators() as creators:
            if str(channel.id) in creators:
                creators[str(channel.id)]["bitrate"] = bitrate * 1000 if bitrate > 0 else 0

        label = f"{bitrate} kbps" if bitrate > 0 else "guild default"
        await ctx.send(embed=ok_embed(f"Bitrate for {channel.mention} set to **{label}**."))

    # ── Panel ──────────────────────────────────────────────────────────────

    @voicemeister.command(name="panel")
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_panel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Send the control panel to a channel (defaults to current)."""
        target = channel or ctx.channel
        panel_embed = build_panel_embed(ctx.guild)
        await target.send(embed=panel_embed, view=self._panel_view)
        if target != ctx.channel:
            await ctx.send(embed=ok_embed(f"Panel sent to {target.mention}."))

    # ── Settings ───────────────────────────────────────────────────────────

    @voicemeister.command(name="settings", aliases=["config"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_settings(self, ctx: commands.Context):
        """View current VoiceMeister settings."""
        data = await self.config.guild(ctx.guild).all()
        log_ch = ctx.guild.get_channel(data["log_channel"]) if data["log_channel"] else None

        embed = discord.Embed(
            title="⚙️ VoiceMeister Settings",
            colour=Clr.VOICE,
        )
        embed.add_field(name="📝 Default Name Template", value=f"`{data['default_name_template']}`",
                        inline=False)
        embed.add_field(name="👥 Default User Limit",
                        value=str(data["default_user_limit"]) if data["default_user_limit"] > 0 else "Unlimited",
                        inline=True)
        embed.add_field(name="📡 Default Bitrate",
                        value=f"{data['default_bitrate'] // 1000} kbps", inline=True)
        embed.add_field(name="📋 Log Channel",
                        value=log_ch.mention if log_ch else "Disabled", inline=True)
        embed.add_field(name="⏱️ Cooldown",
                        value=f"{data['cooldown_seconds']}s", inline=True)
        embed.add_field(name="🔢 Max Channels/User",
                        value=str(data["max_channels_per_user"]), inline=True)
        embed.add_field(name="🎮 Game Auto-Rename",
                        value="Enabled" if data["auto_rename_game"] else "Disabled", inline=True)
        embed.add_field(name="🚫 Blacklisted Users",
                        value=str(len(data["blacklisted_users"])), inline=True)
        embed.add_field(name="✅ Whitelisted Roles",
                        value=str(len(data["whitelisted_roles"])), inline=True)

        await ctx.send(embed=embed)

    @voicemeister.command(name="logchannel", aliases=["log"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_logchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Set the log channel. Omit channel to disable."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id if channel else None)
        if channel:
            await ctx.send(embed=ok_embed(f"Log channel set to {channel.mention}."))
        else:
            await ctx.send(embed=ok_embed("Logging disabled."))

    @voicemeister.command(name="defaultname", aliases=["template"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_defaultname(self, ctx: commands.Context, *, template: str):
        """Set the default name template for new channels.

        Variables: {user}, {game}, {count}, {custom}
        Example: 🔊 {user}'s Lounge
        """
        await self.config.guild(ctx.guild).default_name_template.set(template)
        await ctx.send(embed=ok_embed(f"Default name template set to: `{template}`"))

    @voicemeister.command(name="defaultlimit")
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_defaultlimit(self, ctx: commands.Context, limit: int):
        """Set the default user limit (0 = unlimited)."""
        await self.config.guild(ctx.guild).default_user_limit.set(max(0, min(limit, 99)))
        label = str(limit) if limit > 0 else "unlimited"
        await ctx.send(embed=ok_embed(f"Default user limit set to **{label}**."))

    @voicemeister.command(name="defaultbitrate")
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_defaultbitrate(self, ctx: commands.Context, bitrate: int):
        """Set the default bitrate in kbps (8-384)."""
        br = max(8, min(bitrate, 384)) * 1000
        await self.config.guild(ctx.guild).default_bitrate.set(br)
        await ctx.send(embed=ok_embed(f"Default bitrate set to **{br // 1000} kbps**."))

    @voicemeister.command(name="cooldown")
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_cooldown(self, ctx: commands.Context, seconds: int):
        """Set the cooldown between channel creations (in seconds)."""
        await self.config.guild(ctx.guild).cooldown_seconds.set(max(0, seconds))
        await ctx.send(embed=ok_embed(f"Cooldown set to **{seconds}s**."))

    @voicemeister.command(name="maxchannels", aliases=["maxch"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_maxchannels(self, ctx: commands.Context, limit: int):
        """Set max simultaneous channels per user."""
        await self.config.guild(ctx.guild).max_channels_per_user.set(max(1, limit))
        await ctx.send(embed=ok_embed(f"Max channels per user set to **{limit}**."))

    @voicemeister.command(name="gamerename", aliases=["gamedetect"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_gamerename(self, ctx: commands.Context, enabled: bool):
        """Toggle automatic game-activity channel renaming."""
        await self.config.guild(ctx.guild).auto_rename_game.set(enabled)
        status = "enabled" if enabled else "disabled"
        await ctx.send(embed=ok_embed(f"Game auto-rename **{status}**."))

    # ── Blacklist / Whitelist ──────────────────────────────────────────────

    @voicemeister.group(name="blacklist", aliases=["bl"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_blacklist(self, ctx: commands.Context):
        """Manage the VoiceMeister blacklist."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @vm_blacklist.command(name="add")
    async def vm_bl_add(self, ctx: commands.Context, user: discord.Member):
        """Block a user from creating temp channels."""
        async with self.config.guild(ctx.guild).blacklisted_users() as bl:
            if user.id not in bl:
                bl.append(user.id)
        await ctx.send(embed=ok_embed(f"Blacklisted {user.mention}."))

    @vm_blacklist.command(name="remove")
    async def vm_bl_remove(self, ctx: commands.Context, user: discord.Member):
        """Remove a user from the blacklist."""
        async with self.config.guild(ctx.guild).blacklisted_users() as bl:
            if user.id in bl:
                bl.remove(user.id)
        await ctx.send(embed=ok_embed(f"Removed {user.mention} from blacklist."))

    @vm_blacklist.command(name="list")
    async def vm_bl_list(self, ctx: commands.Context):
        """View blacklisted users."""
        bl = await self.config.guild(ctx.guild).blacklisted_users()
        if not bl:
            await ctx.send(embed=info_embed("No blacklisted users."))
            return
        mentions = [f"<@{uid}>" for uid in bl]
        await ctx.send(embed=info_embed(", ".join(mentions), title="🚫 Blacklisted Users"))

    @voicemeister.group(name="whitelist", aliases=["wl"])
    @checks.admin_or_permissions(manage_guild=True)
    async def vm_whitelist(self, ctx: commands.Context):
        """Manage the VoiceMeister role whitelist (bypasses blacklist)."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @vm_whitelist.command(name="add")
    async def vm_wl_add(self, ctx: commands.Context, role: discord.Role):
        """Add a role to the whitelist."""
        async with self.config.guild(ctx.guild).whitelisted_roles() as wl:
            if role.id not in wl:
                wl.append(role.id)
        await ctx.send(embed=ok_embed(f"Whitelisted {role.mention}."))

    @vm_whitelist.command(name="remove")
    async def vm_wl_remove(self, ctx: commands.Context, role: discord.Role):
        """Remove a role from the whitelist."""
        async with self.config.guild(ctx.guild).whitelisted_roles() as wl:
            if role.id in wl:
                wl.remove(role.id)
        await ctx.send(embed=ok_embed(f"Removed {role.mention} from whitelist."))

    @vm_whitelist.command(name="list")
    async def vm_wl_list(self, ctx: commands.Context):
        """View whitelisted roles."""
        wl = await self.config.guild(ctx.guild).whitelisted_roles()
        if not wl:
            await ctx.send(embed=info_embed("No whitelisted roles."))
            return
        mentions = [f"<@&{rid}>" for rid in wl]
        await ctx.send(embed=info_embed(", ".join(mentions), title="✅ Whitelisted Roles"))

    # ── Reset ──────────────────────────────────────────────────────────────

    @voicemeister.command(name="resetall")
    @checks.admin_or_permissions(administrator=True)
    async def vm_resetall(self, ctx: commands.Context):
        """Reset ALL VoiceMeister settings for this server. ⚠️ Destructive!"""
        await ctx.send(embed=warn_embed(
            "This will **delete all settings**, creator channels, and clean up temp channels.\n"
            "Type `CONFIRM` within 15 seconds to proceed."
        ))

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content == "CONFIRM"

        try:
            await self.bot.wait_for("message", timeout=15, check=check)
        except asyncio.TimeoutError:
            await ctx.send(embed=info_embed("Reset cancelled (timed out)."))
            return

        # Delete all temp channels for this guild
        for ch_id in list(self.temp_channels):
            ch = self.bot.get_channel(ch_id)
            if ch and ch.guild.id == ctx.guild.id:
                self.temp_channels.pop(ch_id, None)
                try:
                    await ch.delete(reason="VoiceMeister: reset all")
                except discord.HTTPException:
                    pass

        # Clear creators
        for ch_id in list(self.creator_channels):
            ch = self.bot.get_channel(ch_id)
            if ch and ch.guild.id == ctx.guild.id:
                self.creator_channels.pop(ch_id, None)

        await self.config.guild(ctx.guild).clear()
        await self._save_temp_channels()
        await ctx.send(embed=ok_embed("All VoiceMeister data for this server has been reset."))

    # ══════════════════════════════════════════════════════════════════════════
    # USER COMMANDS — vc group
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="vc")
    @commands.guild_only()
    async def vc(self, ctx: commands.Context):
        """🔊 Control your VoiceMeister channel."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    async def _get_user_vc(self, ctx: commands.Context):
        """Validate the user is in a VoiceMeister channel they own. Return (vc, owner_id) or None."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(embed=err_embed("You must be in a voice channel."))
            return None, None

        vc = ctx.author.voice.channel
        owner_id = self.temp_channels.get(vc.id)
        if owner_id is None:
            await ctx.send(embed=err_embed("You're not in a VoiceMeister channel."))
            return None, None

        if not (ctx.author.id == owner_id or ctx.author.guild_permissions.manage_channels):
            await ctx.send(embed=err_embed("You don't own this channel."))
            return None, None

        return vc, owner_id

    @vc.command(name="lock")
    async def vc_lock(self, ctx: commands.Context):
        """Lock your channel — prevent others from joining."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        overwrite = vc.overwrites_for(ctx.guild.default_role)
        overwrite.connect = False
        await vc.set_permissions(ctx.guild.default_role, overwrite=overwrite,
                                 reason=f"VoiceMeister: locked by {ctx.author}")
        await ctx.send(embed=ok_embed("Channel **locked** 🔒."))
        await self._log_action(ctx.guild, "🔒 Locked", member=ctx.author, channel=vc)

    @vc.command(name="unlock")
    async def vc_unlock(self, ctx: commands.Context):
        """Unlock your channel — allow anyone to join."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        overwrite = vc.overwrites_for(ctx.guild.default_role)
        overwrite.connect = None
        await vc.set_permissions(ctx.guild.default_role, overwrite=overwrite,
                                 reason=f"VoiceMeister: unlocked by {ctx.author}")
        await ctx.send(embed=ok_embed("Channel **unlocked** 🔓."))
        await self._log_action(ctx.guild, "🔓 Unlocked", member=ctx.author, channel=vc)

    @vc.command(name="hide")
    async def vc_hide(self, ctx: commands.Context):
        """Hide your channel from the channel list."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        overwrite = vc.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = False
        await vc.set_permissions(ctx.guild.default_role, overwrite=overwrite,
                                 reason=f"VoiceMeister: hidden by {ctx.author}")
        await ctx.send(embed=ok_embed("Channel **hidden** 👤."))
        await self._log_action(ctx.guild, "👤 Hidden", member=ctx.author, channel=vc)

    @vc.command(name="unhide", aliases=["reveal", "show"])
    async def vc_unhide(self, ctx: commands.Context):
        """Make your channel visible again."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        overwrite = vc.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = None
        await vc.set_permissions(ctx.guild.default_role, overwrite=overwrite,
                                 reason=f"VoiceMeister: unhidden by {ctx.author}")
        await ctx.send(embed=ok_embed("Channel **visible** 👁️."))
        await self._log_action(ctx.guild, "👁️ Unhidden", member=ctx.author, channel=vc)

    @vc.command(name="ghost")
    async def vc_ghost(self, ctx: commands.Context):
        """Ghost your channel — hide AND lock."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        overwrite = vc.overwrites_for(ctx.guild.default_role)
        overwrite.connect = False
        overwrite.view_channel = False
        await vc.set_permissions(ctx.guild.default_role, overwrite=overwrite,
                                 reason=f"VoiceMeister: ghosted by {ctx.author}")
        await ctx.send(embed=ok_embed("Channel **ghosted** 👻 — hidden and locked."))
        await self._log_action(ctx.guild, "👻 Ghosted", member=ctx.author, channel=vc)

    @vc.command(name="rename", aliases=["name"])
    async def vc_rename(self, ctx: commands.Context, *, name: str):
        """Rename your channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        await vc.edit(name=name[:100], reason=f"VoiceMeister: renamed by {ctx.author}")
        await ctx.send(embed=ok_embed(f"Channel renamed to **{name[:100]}**."))
        await self._log_action(ctx.guild, "✏️ Renamed", member=ctx.author, channel=vc,
                              detail=f"New name: `{name[:100]}`")

    @vc.command(name="limit", aliases=["userlimit"])
    async def vc_limit(self, ctx: commands.Context, limit: int):
        """Set user limit (0 = unlimited)."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        limit = max(0, min(limit, 99))
        await vc.edit(user_limit=limit, reason=f"VoiceMeister: limit set by {ctx.author}")
        label = f"**{limit}**" if limit > 0 else "**unlimited**"
        await ctx.send(embed=ok_embed(f"User limit set to {label}."))
        await self._log_action(ctx.guild, "👥 Limit", member=ctx.author, channel=vc,
                              detail=f"New limit: {label}")

    @vc.command(name="bitrate")
    async def vc_bitrate(self, ctx: commands.Context, kbps: int):
        """Set bitrate in kbps (8-384)."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        max_br = ctx.guild.bitrate_limit // 1000
        kbps = max(8, min(kbps, max_br))
        await vc.edit(bitrate=kbps * 1000, reason=f"VoiceMeister: bitrate set by {ctx.author}")
        await ctx.send(embed=ok_embed(f"Bitrate set to **{kbps} kbps**."))
        await self._log_action(ctx.guild, "📡 Bitrate", member=ctx.author, channel=vc,
                              detail=f"New bitrate: {kbps} kbps")

    @vc.command(name="permit", aliases=["allow", "trust"])
    async def vc_permit(self, ctx: commands.Context, user: discord.Member):
        """Allow a specific user to join your channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        await vc.set_permissions(user, connect=True, view_channel=True,
                                 reason=f"VoiceMeister: permitted by {ctx.author}")
        await ctx.send(embed=ok_embed(f"Permitted {user.mention}."))
        await self._log_action(ctx.guild, "➕ Permitted", member=ctx.author, channel=vc,
                              detail=f"Target: {user} ({user.id})")

    @vc.command(name="reject", aliases=["deny", "block"])
    async def vc_reject(self, ctx: commands.Context, user: discord.Member):
        """Block a specific user from joining your channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        await vc.set_permissions(user, connect=False,
                                 reason=f"VoiceMeister: rejected by {ctx.author}")
        if user.voice and user.voice.channel == vc:
            await user.move_to(None, reason=f"VoiceMeister: rejected by {ctx.author}")
        await ctx.send(embed=ok_embed(f"Rejected {user.mention}."))
        await self._log_action(ctx.guild, "➖ Rejected", member=ctx.author, channel=vc,
                              detail=f"Target: {user} ({user.id})")

    @vc.command(name="kick")
    async def vc_kick(self, ctx: commands.Context, user: discord.Member):
        """Kick a user from your channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        if user.voice and user.voice.channel == vc:
            await user.move_to(None, reason=f"VoiceMeister: kicked by {ctx.author}")
            await ctx.send(embed=ok_embed(f"Kicked {user.mention}."))
            await self._log_action(ctx.guild, "👢 Kicked", member=ctx.author, channel=vc,
                                  detail=f"Target: {user} ({user.id})")
        else:
            await ctx.send(embed=err_embed(f"{user.mention} is not in your channel."))

    @vc.command(name="ban")
    async def vc_ban(self, ctx: commands.Context, user: discord.Member):
        """Permanently ban a user from your channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        await vc.set_permissions(user, connect=False, view_channel=False,
                                 reason=f"VoiceMeister: banned by {ctx.author}")
        if user.voice and user.voice.channel == vc:
            await user.move_to(None, reason=f"VoiceMeister: banned by {ctx.author}")
        await self._add_channel_ban(ctx.guild.id, vc.id, user.id)
        await ctx.send(embed=ok_embed(f"Banned {user.mention} from the channel."))
        await self._log_action(ctx.guild, "🔨 Banned", member=ctx.author, channel=vc,
                              detail=f"Target: {user} ({user.id})")

    @vc.command(name="claim")
    async def vc_claim(self, ctx: commands.Context):
        """Claim an ownerless channel (owner must have left)."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(embed=err_embed("You must be in a voice channel."))
            return

        vc = ctx.author.voice.channel
        owner_id = self.temp_channels.get(vc.id)
        if owner_id is None:
            await ctx.send(embed=err_embed("This is not a VoiceMeister channel."))
            return

        if owner_id == ctx.author.id:
            await ctx.send(embed=info_embed("You already own this channel."))
            return

        owner_in_channel = any(m.id == owner_id for m in vc.members)
        if owner_in_channel:
            await ctx.send(embed=err_embed("The owner is still in the channel."))
            return

        self.temp_channels[vc.id] = ctx.author.id
        await self._save_temp_channels()
        await ctx.send(embed=ok_embed("You are now the **owner** of this channel 👑."))
        await self._log_action(ctx.guild, "👑 Claimed", member=ctx.author, channel=vc)

    @vc.command(name="transfer")
    async def vc_transfer(self, ctx: commands.Context, user: discord.Member):
        """Transfer channel ownership to another user in the channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return

        if user.voice is None or user.voice.channel != vc:
            await ctx.send(embed=err_embed(f"{user.mention} must be in the channel."))
            return

        if user.id == ctx.author.id:
            await ctx.send(embed=err_embed("You can't transfer to yourself."))
            return

        self.temp_channels[vc.id] = user.id
        await self._save_temp_channels()
        await ctx.send(embed=ok_embed(f"Ownership transferred to {user.mention} 👑."))
        await self._log_action(ctx.guild, "🔄 Transferred", member=ctx.author, channel=vc,
                              detail=f"New owner: {user} ({user.id})")

    @vc.command(name="info", aliases=["status"])
    async def vc_info(self, ctx: commands.Context):
        """View info about your current VoiceMeister channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(embed=err_embed("You must be in a voice channel."))
            return

        vc = ctx.author.voice.channel
        owner_id = self.temp_channels.get(vc.id)
        if owner_id is None:
            await ctx.send(embed=err_embed("This is not a VoiceMeister channel."))
            return

        owner = ctx.guild.get_member(owner_id)
        owner_str = owner.mention if owner else f"Unknown (`{owner_id}`)"

        overwrites = vc.overwrites_for(ctx.guild.default_role)
        locked = overwrites.connect is False
        hidden = overwrites.view_channel is False

        status_parts = []
        if locked:
            status_parts.append("🔒 Locked")
        else:
            status_parts.append("🔓 Unlocked")
        if hidden:
            status_parts.append("👤 Hidden")
        else:
            status_parts.append("👁️ Visible")

        embed = discord.Embed(title=f"ℹ️ {vc.name}", colour=Clr.VOICE)
        embed.add_field(name="👑 Owner", value=owner_str, inline=True)
        embed.add_field(name="👥 Members", value=f"{len(vc.members)}/{vc.user_limit or '∞'}",
                        inline=True)
        embed.add_field(name="📡 Bitrate", value=f"{vc.bitrate // 1000} kbps", inline=True)
        embed.add_field(name="🔐 Status", value=" • ".join(status_parts), inline=False)
        embed.add_field(name="🌍 Region", value=vc.rtc_region or "Automatic", inline=True)
        embed.add_field(name="📅 Created", value=f"<t:{int(vc.created_at.timestamp())}:R>",
                        inline=True)

        permitted = []
        rejected = []
        for target, overwrite in vc.overwrites.items():
            if isinstance(target, (discord.Member, discord.User)):
                if target.id == owner_id:
                    continue
                if overwrite.connect is True:
                    permitted.append(target.mention)
                elif overwrite.connect is False:
                    rejected.append(target.mention)

        if permitted:
            embed.add_field(name="✅ Permitted", value=", ".join(permitted[:10]), inline=False)
        if rejected:
            embed.add_field(name="🚫 Rejected/Banned", value=", ".join(rejected[:10]), inline=False)

        await ctx.send(embed=embed)

    @vc.command(name="delete")
    async def vc_delete(self, ctx: commands.Context):
        """Delete your VoiceMeister channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return

        await ctx.send(embed=warn_embed(
            f"Are you sure you want to **delete** `{vc.name}`? Type `yes` within 10s."
        ))

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "yes"

        try:
            await self.bot.wait_for("message", timeout=10, check=check)
        except asyncio.TimeoutError:
            await ctx.send(embed=info_embed("Deletion cancelled."))
            return

        await self._log_action(ctx.guild, "🗑️ Deleted", member=ctx.author, channel=vc)
        self.temp_channels.pop(vc.id, None)
        await self._save_temp_channels()
        try:
            await vc.delete(reason=f"VoiceMeister: deleted by {ctx.author}")
        except discord.HTTPException:
            pass
        await ctx.send(embed=ok_embed("Channel deleted."))

    @vc.command(name="muteall")
    async def vc_muteall(self, ctx: commands.Context):
        """Server-mute all users in your channel (except you)."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        count = 0
        for m in vc.members:
            if m.id != ctx.author.id and not m.voice.mute:
                try:
                    await m.edit(mute=True, reason=f"VoiceMeister: muted by {ctx.author}")
                    count += 1
                except discord.HTTPException:
                    pass
        await ctx.send(embed=ok_embed(f"Server-muted **{count}** user(s) 🔇."))
        await self._log_action(ctx.guild, "🔇 Muted All", member=ctx.author, channel=vc,
                              detail=f"Muted {count} user(s)")

    @vc.command(name="unmuteall")
    async def vc_unmuteall(self, ctx: commands.Context):
        """Remove server-mute from all users in your channel."""
        vc, _ = await self._get_user_vc(ctx)
        if not vc:
            return
        count = 0
        for m in vc.members:
            if m.voice.mute:
                try:
                    await m.edit(mute=False, reason=f"VoiceMeister: unmuted by {ctx.author}")
                    count += 1
                except discord.HTTPException:
                    pass
        await ctx.send(embed=ok_embed(f"Unmuted **{count}** user(s) 🔊."))
        await self._log_action(ctx.guild, "🔊 Unmuted All", member=ctx.author, channel=vc,
                              detail=f"Unmuted {count} user(s)")
