"""
ImageVault - Auto-deletes posted images, silently re-hosting them in a
private vault channel first, so they can be retrieved on request. Spoilered
images stay spoilered when they're sent back.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

LOG = logging.getLogger("red.evecogs.imagevault")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".apng")

COLOUR_OK = discord.Colour.green()
COLOUR_INFO = discord.Colour.blurple()

RETRIEVE_MODES = ("anyone", "author", "staff")


def _is_image(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


def _is_staff(member: discord.Member) -> bool:
    perms = member.guild_permissions
    return perms.administrator or perms.manage_messages or member.id == member.guild.owner_id


class ImageVault(commands.Cog):
    """Auto-deletes images and re-hosts them in a private vault for on-request retrieval."""

    __version__ = "1.0.0"
    __author__ = ["everestmcarthur"]

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x696D6167_65766175_6C74, force_registration=True)

        default_guild: Dict[str, Any] = {
            "enabled": False,
            "vault_channel": None,

            "watch_channels": [],      # empty = watch every channel
            "ignored_channels": [],

            "ignore_bots": True,
            "delete_original": True,
            "repost_text": True,
            "max_size_mb": 25,
            "retrieve_permission": "anyone",  # anyone | author | staff

            "stats": {"total_stored": 0},
        }
        self.config.register_guild(**default_guild)

        self._locks: Dict[int, asyncio.Lock] = {}

    # ══════════════════════════════════════════════════════════
    # Index storage (per-guild JSON file: {"next_id": int, "entries": {id: {...}}})
    # ══════════════════════════════════════════════════════════

    def _index_path(self, guild_id: int) -> Path:
        path = cog_data_path(self) / str(guild_id)
        path.mkdir(parents=True, exist_ok=True)
        return path / "index.json"

    def _lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    def _load_index(self, guild_id: int) -> Dict[str, Any]:
        path = self._index_path(guild_id)
        if not path.exists():
            return {"next_id": 1, "entries": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            LOG.exception("Failed to read ImageVault index for guild %s, resetting.", guild_id)
            return {"next_id": 1, "entries": {}}

    def _save_index(self, guild_id: int, data: Dict[str, Any]) -> None:
        self._index_path(guild_id).write_text(json.dumps(data), encoding="utf-8")

    async def _store_entry(self, guild_id: int, record: Dict[str, Any]) -> int:
        async with self._lock(guild_id):
            data = self._load_index(guild_id)
            entry_id = data["next_id"]
            data["next_id"] = entry_id + 1
            data["entries"][str(entry_id)] = record
            self._save_index(guild_id, data)
            return entry_id

    async def _get_entry(self, guild_id: int, entry_id: int) -> Optional[Dict[str, Any]]:
        async with self._lock(guild_id):
            data = self._load_index(guild_id)
            return data["entries"].get(str(entry_id))

    async def _delete_entry(self, guild_id: int, entry_id: int) -> bool:
        async with self._lock(guild_id):
            data = self._load_index(guild_id)
            if str(entry_id) in data["entries"]:
                del data["entries"][str(entry_id)]
                self._save_index(guild_id, data)
                return True
            return False

    async def _list_entries(self, guild_id: int):
        async with self._lock(guild_id):
            data = self._load_index(guild_id)
            return data["entries"]

    # ══════════════════════════════════════════════════════════
    # Core: vault + delete
    # ══════════════════════════════════════════════════════════

    async def _handle_image_message(self, message: discord.Message, conf: Dict[str, Any]) -> None:
        guild = message.guild
        vault_channel_id = conf["vault_channel"]
        vault_channel = guild.get_channel(vault_channel_id) if vault_channel_id else None
        if not isinstance(vault_channel, discord.TextChannel):
            LOG.warning("ImageVault enabled in guild %s but vault channel is missing/invalid.", guild.id)
            return

        perms = vault_channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.attach_files and perms.embed_links):
            LOG.warning("ImageVault missing permissions in vault channel for guild %s.", guild.id)
            return

        max_bytes = conf["max_size_mb"] * 1024 * 1024
        images = [a for a in message.attachments if _is_image(a)]
        if not images:
            return
        if any(a.size > max_bytes for a in images):
            # Can't selectively strip one attachment from someone else's message,
            # so if any qualifying image is oversized, leave the whole message alone.
            return

        try:
            files = [await a.to_file(spoiler=a.is_spoiler()) for a in images]
        except (discord.HTTPException, discord.NotFound):
            LOG.exception("ImageVault failed to fetch attachment bytes in guild %s.", guild.id)
            return

        embed = discord.Embed(
            description=(message.content or "")[:1000] or None,
            colour=COLOUR_INFO,
            timestamp=message.created_at,
        )
        embed.set_author(
            name=f"{message.author} ({message.author.id})",
            icon_url=message.author.display_avatar.url if message.author.display_avatar else None,
        )
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Images", value=str(len(images)), inline=True)
        embed.set_footer(text="ImageVault archive")

        try:
            vault_message = await vault_channel.send(embed=embed, files=files)
        except discord.HTTPException:
            LOG.exception("ImageVault failed to post to vault channel in guild %s.", guild.id)
            return

        entry_id = await self._store_entry(
            guild.id,
            {
                "author_id": message.author.id,
                "author_name": str(message.author),
                "origin_channel_id": message.channel.id,
                "origin_message_id": message.id,
                "vault_message_id": vault_message.id,
                "timestamp": message.created_at.astimezone(timezone.utc).isoformat(),
                "content": (message.content or "")[:500],
                "attachment_count": len(images),
            },
        )

        async with self.config.guild(guild).stats() as stats:
            stats["total_stored"] = stats.get("total_stored", 0) + 1

        if conf["delete_original"]:
            try:
                await message.delete()
            except discord.HTTPException:
                LOG.exception("ImageVault failed to delete original message in guild %s.", guild.id)
                return

            if conf["repost_text"]:
                note = discord.Embed(
                    description=message.content or None,
                    colour=COLOUR_INFO,
                )
                note.set_author(
                    name=str(message.author),
                    icon_url=message.author.display_avatar.url if message.author.display_avatar else None,
                )
                note.set_footer(
                    text=f"🖼️ {len(images)} image(s) archived — retrieve with "
                         f"[p]imagevault show {entry_id}"
                )
                try:
                    await message.channel.send(embed=note)
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or not message.attachments:
            return
        guild = message.guild
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return
        if conf["ignore_bots"] and message.author.bot:
            return
        if message.channel.id == conf["vault_channel"]:
            return

        watch = set(conf["watch_channels"])
        ignore = set(conf["ignored_channels"])
        channel_id = message.channel.id
        parent_id = getattr(message.channel, "parent_id", None)
        if watch:
            if channel_id not in watch and parent_id not in watch:
                return
        elif (channel_id in ignore) or (parent_id is not None and parent_id in ignore):
            return

        await self._handle_image_message(message, conf)

    # ══════════════════════════════════════════════════════════
    # Commands
    # ══════════════════════════════════════════════════════════

    @commands.group(name="imagevault", aliases=["iv", "vault"])
    @commands.guild_only()
    async def imagevault(self, ctx: commands.Context):
        """🖼️ ImageVault — auto-delete images, retrievable on request.

        Configuration and `list` are staff-only; `show`/`get`, `mine`, and `stats`
        are open to whoever the `retrieve` permission mode allows.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @imagevault.command(name="enable", aliases=["on"])
    @commands.admin_or_permissions(administrator=True)
    async def iv_enable(self, ctx: commands.Context):
        """Enable ImageVault for this server (requires a vault channel to be set first)."""
        vault_id = await self.config.guild(ctx.guild).vault_channel()
        if not vault_id or not ctx.guild.get_channel(vault_id):
            return await ctx.send(
                "❌ Set a vault channel first: `[p]imagevault vaultchannel #channel`.\n"
                "Use a private channel that regular members can't see."
            )
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send(embed=discord.Embed(
            title="🖼️ ImageVault Enabled",
            description="Images posted in watched channels will now be archived and removed.",
            colour=COLOUR_OK,
        ))

    @imagevault.command(name="disable", aliases=["off"])
    @commands.admin_or_permissions(administrator=True)
    async def iv_disable(self, ctx: commands.Context):
        """Disable ImageVault for this server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send(embed=discord.Embed(
            title="🖼️ ImageVault Disabled", colour=COLOUR_INFO,
            description="ImageVault will no longer act on new images.",
        ))

    @imagevault.command(name="vaultchannel")
    @commands.admin_or_permissions(administrator=True)
    async def iv_vaultchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the private channel images get archived into.

        This should be a channel only staff can see — every removed image is
        reposted here in full (with attribution) before the original is deleted.
        """
        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.send_messages and perms.attach_files and perms.embed_links):
            return await ctx.send(f"❌ I need Send Messages, Attach Files, and Embed Links in {channel.mention}.")
        await self.config.guild(ctx.guild).vault_channel.set(channel.id)
        await ctx.send(embed=discord.Embed(
            title="🖼️ Vault Channel Set",
            description=f"Archived images will be posted to {channel.mention}.\n"
                        f"⚠️ Make sure regular members can't view that channel.",
            colour=COLOUR_OK,
        ))

    @imagevault.group(name="watchchannel")
    @commands.admin_or_permissions(administrator=True)
    async def iv_watchchannel(self, ctx: commands.Context):
        """Manage the channel watch-list. Empty list = watch every channel."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @iv_watchchannel.command(name="add")
    async def iv_watchchannel_add(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).watch_channels() as ids:
            if channel.id not in ids:
                ids.append(channel.id)
        await ctx.send(f"✅ Now watching {channel.mention}.")

    @iv_watchchannel.command(name="remove")
    async def iv_watchchannel_remove(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).watch_channels() as ids:
            if channel.id in ids:
                ids.remove(channel.id)
        await ctx.send(f"✅ No longer watching {channel.mention}.")

    @iv_watchchannel.command(name="list")
    async def iv_watchchannel_list(self, ctx: commands.Context):
        ids = await self.config.guild(ctx.guild).watch_channels()
        if not ids:
            return await ctx.send("Watch list is empty — every channel is watched.")
        await ctx.send("Watched channels:\n" + "\n".join(f"<#{i}>" for i in ids))

    @imagevault.group(name="ignorechannel")
    @commands.admin_or_permissions(administrator=True)
    async def iv_ignorechannel(self, ctx: commands.Context):
        """Manage channels ImageVault never touches (only applies when the watch-list is empty)."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @iv_ignorechannel.command(name="add")
    async def iv_ignorechannel_add(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).ignored_channels() as ids:
            if channel.id not in ids:
                ids.append(channel.id)
        await ctx.send(f"✅ {channel.mention} will be ignored.")

    @iv_ignorechannel.command(name="remove")
    async def iv_ignorechannel_remove(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).ignored_channels() as ids:
            if channel.id in ids:
                ids.remove(channel.id)
        await ctx.send(f"✅ {channel.mention} removed from the ignore list.")

    @iv_ignorechannel.command(name="list")
    async def iv_ignorechannel_list(self, ctx: commands.Context):
        ids = await self.config.guild(ctx.guild).ignored_channels()
        if not ids:
            return await ctx.send("No ignored channels.")
        await ctx.send("Ignored channels:\n" + "\n".join(f"<#{i}>" for i in ids))

    @imagevault.command(name="deleteoriginal")
    @commands.admin_or_permissions(administrator=True)
    async def iv_deleteoriginal(self, ctx: commands.Context, toggle: bool):
        """Toggle whether the original message is actually deleted after archiving."""
        await self.config.guild(ctx.guild).delete_original.set(toggle)
        await ctx.send(f"✅ Deleting originals is now {'enabled' if toggle else 'disabled (archive-only mode)'}.")

    @imagevault.command(name="repost")
    @commands.admin_or_permissions(administrator=True)
    async def iv_repost(self, ctx: commands.Context, toggle: bool):
        """Toggle reposting the original text content (sans image) after deletion."""
        await self.config.guild(ctx.guild).repost_text.set(toggle)
        await ctx.send(f"✅ Text repost {'enabled' if toggle else 'disabled'}.")

    @imagevault.command(name="ignorebots")
    @commands.admin_or_permissions(administrator=True)
    async def iv_ignorebots(self, ctx: commands.Context, toggle: bool):
        """Toggle whether images posted by other bots/webhooks are ignored."""
        await self.config.guild(ctx.guild).ignore_bots.set(toggle)
        await ctx.send(f"✅ Bot messages are now {'ignored' if toggle else 'processed'}.")

    @imagevault.command(name="maxsize")
    @commands.admin_or_permissions(administrator=True)
    async def iv_maxsize(self, ctx: commands.Context, megabytes: int):
        """Set the max image size (MB) ImageVault will archive. Larger images are left alone."""
        if megabytes < 1 or megabytes > 100:
            return await ctx.send("❌ Must be between 1 and 100 MB.")
        await self.config.guild(ctx.guild).max_size_mb.set(megabytes)
        await ctx.send(f"✅ Max archived image size set to **{megabytes}MB**.")

    @imagevault.command(name="retrieve")
    @commands.admin_or_permissions(administrator=True)
    async def iv_retrieve(self, ctx: commands.Context, mode: str):
        """Set who can retrieve archived images: `anyone`, `author`, or `staff`."""
        mode = mode.lower()
        if mode not in RETRIEVE_MODES:
            return await ctx.send(f"❌ Must be one of: {', '.join(RETRIEVE_MODES)}.")
        await self.config.guild(ctx.guild).retrieve_permission.set(mode)
        await ctx.send(f"✅ Retrieval permission set to **{mode}**.")

    @imagevault.command(name="settings", aliases=["status", "config"])
    @commands.admin_or_permissions(administrator=True)
    async def iv_settings(self, ctx: commands.Context):
        """View ImageVault's full configuration for this server."""
        conf = await self.config.guild(ctx.guild).all()
        vault_ch = ctx.guild.get_channel(conf["vault_channel"]) if conf["vault_channel"] else None

        embed = discord.Embed(title="🖼️ ImageVault Settings", colour=COLOUR_INFO, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Status", value="✅ Enabled" if conf["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Vault Channel", value=vault_ch.mention if vault_ch else "⚠️ Not set", inline=True)
        embed.add_field(name="Delete Originals", value="✅" if conf["delete_original"] else "❌ (archive-only)", inline=True)
        embed.add_field(name="Repost Text", value="✅" if conf["repost_text"] else "❌", inline=True)
        embed.add_field(name="Ignore Bots", value="✅" if conf["ignore_bots"] else "❌", inline=True)
        embed.add_field(name="Max Size", value=f"{conf['max_size_mb']}MB", inline=True)
        embed.add_field(name="Retrieval", value=conf["retrieve_permission"].title(), inline=True)
        watch = conf["watch_channels"]
        embed.add_field(
            name="Watched Channels",
            value=(", ".join(f"<#{i}>" for i in watch) if watch else "All channels"),
            inline=False,
        )
        if conf["ignored_channels"]:
            embed.add_field(name="Ignored Channels", value=", ".join(f"<#{i}>" for i in conf["ignored_channels"]), inline=False)
        embed.add_field(name="Total Archived", value=str(conf["stats"].get("total_stored", 0)), inline=True)
        embed.set_footer(text=f"ImageVault v{self.__version__}")
        await ctx.send(embed=embed)

    @imagevault.command(name="show", aliases=["get"])
    async def iv_show(self, ctx: commands.Context, entry_id: int):
        """Retrieve an archived image by its ID (see the archive note or `[p]imagevault list`)."""
        conf = await self.config.guild(ctx.guild).all()
        record = await self._get_entry(ctx.guild.id, entry_id)
        if not record:
            return await ctx.send("❌ No archived image with that ID.")

        mode = conf["retrieve_permission"]
        if mode == "author" and ctx.author.id != record["author_id"] and not _is_staff(ctx.author):
            return await ctx.send("❌ Only the original poster (or staff) can retrieve this image.")
        if mode == "staff" and not _is_staff(ctx.author):
            return await ctx.send("❌ Only staff can retrieve archived images here.")

        vault_channel = ctx.guild.get_channel(conf["vault_channel"])
        if not isinstance(vault_channel, discord.TextChannel):
            return await ctx.send("❌ The vault channel is missing — cannot retrieve.")

        try:
            vault_message = await vault_channel.fetch_message(record["vault_message_id"])
        except discord.NotFound:
            return await ctx.send("❌ That image's vault entry no longer exists.")
        except discord.HTTPException:
            return await ctx.send("❌ Failed to fetch that image from the vault.")

        try:
            files = [await a.to_file(spoiler=a.is_spoiler()) for a in vault_message.attachments]
        except (discord.HTTPException, discord.NotFound):
            return await ctx.send("❌ Failed to re-download that image.")

        embed = discord.Embed(
            description=record.get("content") or None,
            colour=COLOUR_INFO,
        )
        embed.set_author(name=record["author_name"])
        embed.set_footer(text=f"Originally posted {record['timestamp'][:19]} UTC — archive #{entry_id}")
        await ctx.send(embed=embed, files=files)

    @imagevault.command(name="list")
    @commands.admin_or_permissions(administrator=True)
    async def iv_list(self, ctx: commands.Context, page: int = 1):
        """List recently archived images for this server (staff only — shows all members' entries)."""
        entries = await self._list_entries(ctx.guild.id)
        if not entries:
            return await ctx.send("No images archived yet.")

        per_page = 10
        sorted_ids = sorted((int(k) for k in entries), reverse=True)
        total_pages = max(1, (len(sorted_ids) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        chunk = sorted_ids[(page - 1) * per_page: page * per_page]

        embed = discord.Embed(title="🖼️ ImageVault Archive", colour=COLOUR_INFO)
        for eid in chunk:
            e = entries[str(eid)]
            embed.add_field(
                name=f"#{eid} — {e['author_name']}",
                value=f"<#{e['origin_channel_id']}> • {e['attachment_count']} image(s) • {e['timestamp'][:19]} UTC",
                inline=False,
            )
        embed.set_footer(text=f"Page {page}/{total_pages} • [p]imagevault show <id>")
        await ctx.send(embed=embed)

    @imagevault.command(name="mine")
    async def iv_mine(self, ctx: commands.Context, page: int = 1):
        """List your own archived images."""
        entries = await self._list_entries(ctx.guild.id)
        mine = {k: v for k, v in entries.items() if v["author_id"] == ctx.author.id}
        if not mine:
            return await ctx.send("You don't have any archived images.")

        per_page = 10
        sorted_ids = sorted((int(k) for k in mine), reverse=True)
        total_pages = max(1, (len(sorted_ids) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        chunk = sorted_ids[(page - 1) * per_page: page * per_page]

        embed = discord.Embed(title=f"🖼️ Your Archived Images", colour=COLOUR_INFO)
        for eid in chunk:
            e = mine[str(eid)]
            embed.add_field(
                name=f"#{eid}",
                value=f"<#{e['origin_channel_id']}> • {e['attachment_count']} image(s) • {e['timestamp'][:19]} UTC",
                inline=False,
            )
        embed.set_footer(text=f"Page {page}/{total_pages} • [p]imagevault show <id>")
        await ctx.send(embed=embed)

    @imagevault.command(name="forget")
    @commands.admin_or_permissions(administrator=True)
    async def iv_forget(self, ctx: commands.Context, entry_id: int):
        """Remove an entry from the archive index (staff only). The vault message itself is untouched."""
        removed = await self._delete_entry(ctx.guild.id, entry_id)
        if removed:
            await ctx.send(f"✅ Archive entry #{entry_id} forgotten (the vault post itself is untouched).")
        else:
            await ctx.send("❌ No archived image with that ID.")

    @imagevault.command(name="stats")
    async def iv_stats(self, ctx: commands.Context):
        """View lifetime ImageVault stats for this server."""
        conf = await self.config.guild(ctx.guild).all()
        await ctx.send(embed=discord.Embed(
            title="🖼️ ImageVault Stats",
            description=f"**{conf['stats'].get('total_stored', 0)}** images archived",
            colour=COLOUR_INFO,
        ))

