"""
Affiliates - Ping on Join (POJ), a persistent affiliate-server board, and a
separate DM-affiliates list sent to new members on join.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .views import AddAffiliateButtonView, RemoveSelectView, ok_embed, info_embed, err_embed

LOG = logging.getLogger("red.evecogs.affiliates")

COLOUR_INFO = discord.Colour.blurple()

LIST_KEYS = {"aff": "affiliates", "dm": "dm_affiliates"}
NEXT_ID_KEYS = {"aff": "aff_next_id", "dm": "dm_next_id"}
MAX_ENTRIES = 100  # 10 messages x 10 entries/message


def _chunk(items: List[dict], size: int = 10) -> List[List[dict]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def render_pages(entries: List[dict], guild_name: str) -> List[str]:
    """Render entries into plain-text message bodies, 10 per message.

    Deliberately plain text, not embeds/Components V2: a LayoutView's real
    budget (verified against the installed discord.py — 40 total children,
    4000 total text characters across the *whole* view) can't safely hold
    even one 10-entry page in the worst case, and Discord's own 2000-char
    message-content cap is what actually bounds this — see AffiliateModal's
    max_length comment for the field-length math that keeps every page safe.
    """
    header = f"**{guild_name}'s Affiliations:**"
    if not entries:
        return [f"{header}\n\nNothing here yet."]

    chunks = _chunk(entries, 10)[:10]  # cap at 10 pages = 100 entries
    pages = []
    for page_idx, chunk in enumerate(chunks):
        blocks = [header] if page_idx == 0 else []
        for i, entry in enumerate(chunk):
            position = page_idx * 10 + i + 1
            blocks.append(f"{position}. {entry['name']} __==__~~--~~ {entry['invite']}")
        pages.append("\n\n".join(blocks))
    return pages


class Affiliates(commands.Cog):
    """POJ (Ping on Join), an affiliate-server board, and DM affiliates."""

    __version__ = "1.0.0"
    __author__ = ["everestmcarthur"]

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x6166_6669_6C69_6174_6573, force_registration=True)

        default_guild: Dict[str, Any] = {
            # POJ
            "poj_enabled": False,
            "poj_channels": [],
            "poj_delay": 5,
            "poj_message": "{member}",

            # Affiliates (channel board)
            "aff_channel": None,
            "aff_message_ids": [],  # one message ID per 10-entry page
            "aff_next_id": 1,
            "affiliates": [],

            # DM Affiliates (separate list, no channel)
            "dm_enabled": False,
            "dm_next_id": 1,
            "dm_affiliates": [],
        }
        self.config.register_guild(**default_guild)

    # ══════════════════════════════════════════════════════════
    # Shared storage helpers (used by both commands and views.py)
    # ══════════════════════════════════════════════════════════

    async def add_entry(
        self, guild_id: int, list_kind: str, name: str, invite: str, added_by: int
    ) -> Optional[int]:
        """Append an entry; returns its 1-indexed display position, or None if full."""
        list_key = LIST_KEYS[list_kind]
        id_key = NEXT_ID_KEYS[list_kind]
        guild_conf = self.config.guild_from_id(guild_id)

        async with guild_conf.all() as conf:
            entries = conf[list_key]
            if len(entries) >= MAX_ENTRIES:
                return None
            entry_id = conf[id_key]
            conf[id_key] = entry_id + 1
            entries.append({
                "id": entry_id,
                "name": name,
                "invite": invite,
                "added_by": added_by,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            position = len(entries)

        if list_kind == "aff":
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._sync_aff_message(guild)
        return position

    async def remove_entry(self, guild_id: int, list_kind: str, entry_id: int) -> bool:
        list_key = LIST_KEYS[list_kind]
        guild_conf = self.config.guild_from_id(guild_id)

        async with guild_conf.all() as conf:
            entries = conf[list_key]
            filtered = [e for e in entries if e["id"] != entry_id]
            if len(filtered) == len(entries):
                return False
            conf[list_key] = filtered

        if list_kind == "aff":
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._sync_aff_message(guild)
        return True

    async def get_entry(self, guild_id: int, list_kind: str, entry_id: int) -> Optional[dict]:
        list_key = LIST_KEYS[list_kind]
        entries = await getattr(self.config.guild_from_id(guild_id), list_key)()
        for entry in entries:
            if entry["id"] == entry_id:
                return entry
        return None

    async def _sync_aff_message(self, guild: discord.Guild) -> None:
        """(Re)render the persistent affiliate board — one plain-text message per
        10-entry page. Creates new pages as the list grows, edits existing pages
        in place, and deletes trailing pages if the list shrank."""
        conf = await self.config.guild(guild).all()
        channel_id = conf["aff_channel"]
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        pages = render_pages(conf["affiliates"], guild.name)
        old_ids = conf["aff_message_ids"]
        new_ids: List[int] = []

        for i, page_text in enumerate(pages):
            message = None
            if i < len(old_ids):
                try:
                    message = await channel.fetch_message(old_ids[i])
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    message = None

            if message:
                try:
                    await message.edit(content=page_text)
                    new_ids.append(message.id)
                    continue
                except discord.HTTPException:
                    pass  # fall through and recreate this page below

            try:
                new_message = await channel.send(page_text)
            except discord.HTTPException:
                LOG.exception("Affiliates: failed to send board page %d in guild %s", i + 1, guild.id)
                continue
            new_ids.append(new_message.id)

        # The list shrank — clean up now-unused trailing pages.
        for stale_id in old_ids[len(pages):]:
            try:
                stale_message = await channel.fetch_message(stale_id)
                await stale_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await self.config.guild(guild).aff_message_ids.set(new_ids)

    # ══════════════════════════════════════════════════════════
    # on_member_join: POJ + DM affiliates
    # ══════════════════════════════════════════════════════════

    async def _fire_poj(self, member: discord.Member, conf: Dict[str, Any]) -> None:
        channels = conf["poj_channels"]
        if not channels:
            return
        template = conf["poj_message"] or "{member}"
        delay = conf["poj_delay"]
        content = template.replace("{member}", member.mention)

        async def _ping_one(channel_id: int) -> None:
            channel = member.guild.get_channel(channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
                return
            perms = channel.permissions_for(member.guild.me)
            if not perms.send_messages:
                return
            try:
                msg = await channel.send(content, allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                return
            await asyncio.sleep(delay)
            try:
                await msg.delete()
            except discord.HTTPException:
                pass

        # Fire-and-forget per channel so a slow/rate-limited channel never
        # delays the ping (or the DM affiliate send) in any other channel.
        for channel_id in channels:
            asyncio.create_task(_ping_one(channel_id))

    async def _send_dm_affiliates(self, member: discord.Member, conf: Dict[str, Any]) -> None:
        entries = conf["dm_affiliates"]
        if not entries:
            return
        pages = render_pages(entries, member.guild.name)
        try:
            for page_text in pages:
                await member.send(page_text)
        except (discord.Forbidden, discord.HTTPException):
            pass  # DMs closed or another delivery failure — not actionable

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        conf = await self.config.guild(member.guild).all()

        if conf["poj_enabled"]:
            await self._fire_poj(member, conf)
        if conf["dm_enabled"]:
            await self._send_dm_affiliates(member, conf)

    # ══════════════════════════════════════════════════════════
    # POJ commands — every subcommand here is admin-only, so the check
    # lives once on the top-level group.
    # ══════════════════════════════════════════════════════════

    @commands.group(name="poj")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def poj(self, ctx: commands.Context):
        """👋 POJ — Ping on Join: mention new members, then auto-delete the ping."""

    @poj.command(name="enable", aliases=["on"])
    async def poj_enable(self, ctx: commands.Context):
        """Enable POJ for this server."""
        await self.config.guild(ctx.guild).poj_enabled.set(True)
        await ctx.send(embed=ok_embed("✅ POJ enabled."))

    @poj.command(name="disable", aliases=["off"])
    async def poj_disable(self, ctx: commands.Context):
        """Disable POJ for this server."""
        await self.config.guild(ctx.guild).poj_enabled.set(False)
        await ctx.send(embed=info_embed("POJ disabled."))

    @poj.group(name="channel")
    async def poj_channel(self, ctx: commands.Context):
        """Manage which channels ping new members on join."""

    @poj_channel.command(name="add")
    async def poj_channel_add(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).poj_channels() as chans:
            if channel.id not in chans:
                chans.append(channel.id)
        await ctx.send(embed=ok_embed(f"✅ {channel.mention} will now ping new members."))

    @poj_channel.command(name="remove")
    async def poj_channel_remove(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).poj_channels() as chans:
            if channel.id in chans:
                chans.remove(channel.id)
        await ctx.send(embed=ok_embed(f"✅ {channel.mention} removed from POJ."))

    @poj_channel.command(name="list")
    async def poj_channel_list(self, ctx: commands.Context):
        chans = await self.config.guild(ctx.guild).poj_channels()
        if not chans:
            return await ctx.send(embed=info_embed("No POJ channels configured."))
        await ctx.send("POJ channels:\n" + "\n".join(f"<#{c}>" for c in chans))

    @poj.command(name="delay")
    async def poj_delay(self, ctx: commands.Context, seconds: int):
        """Set how long (1-60s) the ping stays before auto-deleting."""
        if seconds < 1 or seconds > 60:
            return await ctx.send(embed=err_embed("Delay must be between 1 and 60 seconds."))
        await self.config.guild(ctx.guild).poj_delay.set(seconds)
        await ctx.send(embed=ok_embed(f"✅ POJ delete-delay set to **{seconds}s**."))

    @poj.command(name="message")
    async def poj_message(self, ctx: commands.Context, *, template: str):
        """Set the ping message template. Must include `{member}`."""
        if "{member}" not in template:
            return await ctx.send(embed=err_embed("Template must include `{member}`."))
        await self.config.guild(ctx.guild).poj_message.set(template)
        await ctx.send(embed=ok_embed("✅ POJ message template updated."))

    @poj.command(name="settings", aliases=["status"])
    async def poj_settings(self, ctx: commands.Context):
        conf = await self.config.guild(ctx.guild).all()
        embed = discord.Embed(title="👋 POJ Settings", colour=COLOUR_INFO)
        embed.add_field(name="Status", value="✅ Enabled" if conf["poj_enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Delay", value=f"{conf['poj_delay']}s", inline=True)
        embed.add_field(
            name="Channels",
            value=", ".join(f"<#{c}>" for c in conf["poj_channels"]) or "None",
            inline=False,
        )
        embed.add_field(name="Message Template", value=f"`{conf['poj_message']}`", inline=False)
        embed.set_footer(text=f"Affiliates v{self.__version__}")
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════
    # Affiliate board commands — mixed access, so the admin check goes on
    # each management subcommand individually; `list` stays open to anyone.
    # ══════════════════════════════════════════════════════════

    @commands.group(name="aff", aliases=["affiliate", "affiliates"])
    @commands.guild_only()
    async def aff(self, ctx: commands.Context):
        """🤝 Affiliates — the affiliate-server board and DM affiliates."""

    @aff.command(name="channel")
    @commands.admin_or_permissions(administrator=True)
    async def aff_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel the affiliate board is posted/kept updated in."""
        perms = channel.permissions_for(ctx.guild.me)
        if not perms.send_messages:
            return await ctx.send(embed=err_embed(f"I need Send Messages in {channel.mention}."))
        await self.config.guild(ctx.guild).aff_channel.set(channel.id)
        await self.config.guild(ctx.guild).aff_message_ids.set([])
        await self._sync_aff_message(ctx.guild)
        await ctx.send(embed=ok_embed(f"✅ Affiliate board set to {channel.mention}."))

    @aff.command(name="add")
    @commands.admin_or_permissions(administrator=True)
    async def aff_add(self, ctx: commands.Context):
        """Add a new affiliate via a short modal (Server Name + Server Invite)."""
        channel_id = await self.config.guild(ctx.guild).aff_channel()
        if not channel_id:
            return await ctx.send(embed=err_embed("Set a board channel first: `[p]aff channel #channel`."))
        view = AddAffiliateButtonView(self, ctx.guild.id, "aff", ctx.author.id)
        await ctx.send(embed=info_embed("Click below to add a new affiliate."), view=view)

    @aff.command(name="remove")
    @commands.admin_or_permissions(administrator=True)
    async def aff_remove(self, ctx: commands.Context, page: int = 1):
        """Remove an affiliate via a select menu + confirmation.

        Pass a page number if there are more than 25 affiliates (each select menu can only list 25 at a time).
        """
        entries = await self.config.guild(ctx.guild).affiliates()
        if not entries:
            return await ctx.send(embed=info_embed("There are no affiliates to remove."))
        total_pages = (len(entries) + 24) // 25
        page = max(1, min(page, total_pages))
        view = RemoveSelectView(self, ctx.guild.id, "aff", ctx.author.id, entries, page)
        desc = "Choose an affiliate to remove:"
        if total_pages > 1:
            desc += f"\nPage **{page}/{total_pages}** — run `[p]aff remove <page>` to see others."
        await ctx.send(embed=info_embed(desc), view=view)

    @aff.command(name="list")
    async def aff_list(self, ctx: commands.Context):
        """Preview the current affiliate list."""
        entries = await self.config.guild(ctx.guild).affiliates()
        for page_text in render_pages(entries, ctx.guild.name):
            await ctx.send(page_text)

    @aff.command(name="refresh")
    @commands.admin_or_permissions(administrator=True)
    async def aff_refresh(self, ctx: commands.Context):
        """Force-recreate/resync the persistent board message (recovery command)."""
        channel_id = await self.config.guild(ctx.guild).aff_channel()
        if not channel_id:
            return await ctx.send(embed=err_embed("No board channel configured yet."))
        await self._sync_aff_message(ctx.guild)
        await ctx.send(embed=ok_embed("✅ Affiliate board refreshed."))

    @aff.command(name="settings", aliases=["status"])
    @commands.admin_or_permissions(administrator=True)
    async def aff_settings(self, ctx: commands.Context):
        conf = await self.config.guild(ctx.guild).all()
        channel = ctx.guild.get_channel(conf["aff_channel"]) if conf["aff_channel"] else None
        embed = discord.Embed(title="🤝 Affiliates Settings", colour=COLOUR_INFO)
        embed.add_field(name="Board Channel", value=channel.mention if channel else "Not set", inline=True)
        embed.add_field(name="Affiliates", value=str(len(conf["affiliates"])), inline=True)
        embed.add_field(
            name="DM Affiliates",
            value=f"{'✅ Enabled' if conf['dm_enabled'] else '❌ Disabled'} — {len(conf['dm_affiliates'])} entries",
            inline=False,
        )
        embed.set_footer(text=f"Affiliates v{self.__version__}")
        await ctx.send(embed=embed)

    # ── DM affiliates ────────────────────────────────────────

    @aff.group(name="dm")
    async def aff_dm(self, ctx: commands.Context):
        """Manage the separate DM-affiliates list, sent to new members on join."""

    @aff_dm.command(name="add")
    @commands.admin_or_permissions(administrator=True)
    async def aff_dm_add(self, ctx: commands.Context):
        """Add a new DM affiliate via a short modal (Server Name + Server Invite)."""
        view = AddAffiliateButtonView(self, ctx.guild.id, "dm", ctx.author.id)
        await ctx.send(embed=info_embed("Click below to add a new DM affiliate."), view=view)

    @aff_dm.command(name="remove")
    @commands.admin_or_permissions(administrator=True)
    async def aff_dm_remove(self, ctx: commands.Context, page: int = 1):
        """Remove a DM affiliate via a select menu + confirmation.

        Pass a page number if there are more than 25 DM affiliates (each select menu can only list 25 at a time).
        """
        entries = await self.config.guild(ctx.guild).dm_affiliates()
        if not entries:
            return await ctx.send(embed=info_embed("There are no DM affiliates to remove."))
        total_pages = (len(entries) + 24) // 25
        page = max(1, min(page, total_pages))
        view = RemoveSelectView(self, ctx.guild.id, "dm", ctx.author.id, entries, page)
        desc = "Choose a DM affiliate to remove:"
        if total_pages > 1:
            desc += f"\nPage **{page}/{total_pages}** — run `[p]aff dm remove <page>` to see others."
        await ctx.send(embed=info_embed(desc), view=view)

    @aff_dm.command(name="list")
    async def aff_dm_list(self, ctx: commands.Context):
        """Preview the current DM-affiliate list."""
        entries = await self.config.guild(ctx.guild).dm_affiliates()
        for page_text in render_pages(entries, ctx.guild.name):
            await ctx.send(page_text)

    @aff_dm.command(name="enable", aliases=["on"])
    @commands.admin_or_permissions(administrator=True)
    async def aff_dm_enable(self, ctx: commands.Context):
        """Start DMing new members the DM-affiliate list on join."""
        await self.config.guild(ctx.guild).dm_enabled.set(True)
        await ctx.send(embed=ok_embed("✅ New members will now be DMed the DM-affiliate list."))

    @aff_dm.command(name="disable", aliases=["off"])
    @commands.admin_or_permissions(administrator=True)
    async def aff_dm_disable(self, ctx: commands.Context):
        """Stop DMing new members the DM-affiliate list."""
        await self.config.guild(ctx.guild).dm_enabled.set(False)
        await ctx.send(embed=info_embed("DM affiliates disabled."))

