"""
ServerWhitelist v2.0 — Ultimate Server Management Cog for Red-DiscordBot
=========================================================================

Owner-only hybrid commands to control which Discord servers the bot may
operate in.  Every feature uses Red's Config for persistence and discord.py
Views for interactive UI (paginated embeds, leave / blacklist buttons, etc.).

Feature set
-----------
Whitelist & Blacklist
  • ``[p]join <id>``          — whitelist a server
  • ``[p]join remove <id>``   — un-whitelist a server (optionally leave)
  • ``[p]join blacklist <id>``— blacklist a server (auto-leave & never rejoin)
  • ``[p]join unblacklist <id>`` — remove from blacklist
  • ``[p]join whitelist``     — paginated whitelist with ❌ remove buttons
  • ``[p]join blacklisted``   — paginated blacklist

Server Browser
  • ``[p]join servers``       — paginated embed of ALL guilds with 🚪 Leave btns
  • ``[p]join info <id>``     — detailed embed for one guild
  • ``[p]join search <query>``— search servers by name
  • ``[p]join stats``         — high-level overview

Bulk Actions
  • ``[p]join leave <id>``    — leave a guild immediately
  • ``[p]join purge``         — leave every non-whitelisted guild (confirm step)

Bot Lock
  • ``[p]join lock``          — reject ALL new joins (even whitelisted)
  • ``[p]join unlock``        — resume normal whitelist behaviour

Logging
  • ``[p]join log <channel>`` — log join/leave/block events to a channel
  • ``[p]join log off``       — disable logging

Settings
  • ``[p]join settings``      — display current config at a glance

Export
  • ``[p]join export``        — upload a .txt file of all guilds
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import List, Optional, Sequence

import discord
from discord import Interaction
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.serverwhitelist")

EMBED_COLOUR = 0x2F3136
PER_PAGE = 8  # guilds per paginated page


# ═══════════════════════════════════════════════════════════════════
#  Paginated View (reusable)
# ═══════════════════════════════════════════════════════════════════

class PaginatedView(discord.ui.View):
    """Generic paginator that cycles through a list of embeds."""

    def __init__(
        self,
        pages: list[discord.Embed],
        *,
        author_id: int,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self.author_id = author_id
        self.current = 0
        self._update_buttons()

    # ── helpers ───────────────────────────────────────────────

    def _update_buttons(self) -> None:
        self.first_btn.disabled = self.current == 0
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        self.last_btn.disabled = self.current >= len(self.pages) - 1
        self.page_indicator.label = f"{self.current + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the bot owner can use these controls.", ephemeral=True
            )
            return False
        return True

    async def _show(self, interaction: Interaction) -> None:
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    # ── buttons ──────────────────────────────────────────────

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def first_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = 0
        await self._show(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_indicator(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        await self._show(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def last_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = len(self.pages) - 1
        await self._show(interaction)


# ═══════════════════════════════════════════════════════════════════
#  Leave-button View (attached to server list pages)
# ═══════════════════════════════════════════════════════════════════

class ServerLeaveSelect(discord.ui.Select):
    """Dropdown of guilds on the current page — pick one to leave."""

    def __init__(self, guilds: list[discord.Guild], *, cog: "ServerWhitelist"):
        self.cog = cog
        options = [
            discord.SelectOption(
                label=g.name[:100],
                value=str(g.id),
                description=f"ID: {g.id} • {g.member_count} members",
            )
            for g in guilds[:25]
        ]
        super().__init__(
            placeholder="🚪 Select a server to leave…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: Interaction) -> None:
        guild_id = int(self.values[0])
        guild = self.cog.bot.get_guild(guild_id)
        if guild is None:
            await interaction.response.send_message(
                "Bot is no longer in that server.", ephemeral=True
            )
            return
        name = guild.name
        await guild.leave()
        await self.cog._log_event(f"👋 Left **{name}** (`{guild_id}`) via server browser.")
        await interaction.response.send_message(
            f"👋 Left **{name}** (`{guild_id}`).", ephemeral=True
        )


class ServerPageView(discord.ui.View):
    """Paginated server list with a leave-select on each page."""

    def __init__(
        self,
        pages: list[discord.Embed],
        guild_pages: list[list[discord.Guild]],
        *,
        cog: "ServerWhitelist",
        author_id: int,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self.guild_pages = guild_pages
        self.cog = cog
        self.author_id = author_id
        self.current = 0
        self._rebuild_select()
        self._update_buttons()

    # ── helpers ───────────────────────────────────────────────

    def _rebuild_select(self) -> None:
        # Remove existing select if any
        for item in self.children[:]:
            if isinstance(item, ServerLeaveSelect):
                self.remove_item(item)
        if self.guild_pages[self.current]:
            self.add_item(
                ServerLeaveSelect(self.guild_pages[self.current], cog=self.cog)
            )

    def _update_buttons(self) -> None:
        self.first_btn.disabled = self.current == 0
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        self.last_btn.disabled = self.current >= len(self.pages) - 1
        self.page_indicator.label = f"{self.current + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the bot owner can use these controls.", ephemeral=True
            )
            return False
        return True

    async def _show(self, interaction: Interaction) -> None:
        self._update_buttons()
        self._rebuild_select()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    # ── buttons ──────────────────────────────────────────────

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def first_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = 0
        await self._show(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_indicator(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        await self._show(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def last_btn(self, interaction: Interaction, button: discord.ui.Button):
        self.current = len(self.pages) - 1
        await self._show(interaction)


# ═══════════════════════════════════════════════════════════════════
#  Confirm Purge View
# ═══════════════════════════════════════════════════════════════════

class ConfirmPurgeView(discord.ui.View):
    """Two-button confirmation for the purge command."""

    def __init__(self, *, author_id: int, timeout: float = 30.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.result: Optional[bool] = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Yes, purge", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: Interaction, button: discord.ui.Button):
        self.result = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: Interaction, button: discord.ui.Button):
        self.result = False
        self.stop()
        await interaction.response.defer()


# ═══════════════════════════════════════════════════════════════════
#  Main Cog
# ═══════════════════════════════════════════════════════════════════

class ServerWhitelist(commands.Cog):
    """Ultimate server management — whitelist, blacklist, browse, leave, lock & more."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=827364510293,
            force_registration=True,
        )
        self.config.register_global(
            whitelist=[],
            blacklist=[],
            locked=False,
            log_channel=None,  # int or None
        )

    # ── lifecycle ─────────────────────────────────────────────

    async def cog_load(self) -> None:
        """Auto-whitelist every guild the bot is currently in."""
        current_ids = [g.id for g in self.bot.guilds]
        async with self.config.whitelist() as wl:
            merged = list(set(wl) | set(current_ids))
            wl.clear()
            wl.extend(merged)
        log.info(
            "ServerWhitelist loaded — %d current guild(s) merged into whitelist (%d total).",
            len(current_ids),
            len(set(wl) | set(current_ids)),
        )

    # ── internal helpers ──────────────────────────────────────

    async def _log_event(self, message: str) -> None:
        """Send an event message to the configured log channel, if any."""
        channel_id: Optional[int] = await self.config.log_channel()
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(
                embed=discord.Embed(
                    description=message,
                    colour=EMBED_COLOUR,
                    timestamp=datetime.now(timezone.utc),
                ).set_footer(text="ServerWhitelist")
            )
        except discord.HTTPException:
            pass

    @staticmethod
    def _guild_line(guild: discord.Guild) -> str:
        """Single-line summary for embed fields."""
        owner = guild.owner or "Unknown"
        created = discord.utils.format_dt(guild.created_at, style="R")
        joined = discord.utils.format_dt(guild.me.joined_at, style="R") if guild.me and guild.me.joined_at else "?"
        return (
            f"👑 **Owner:** {owner}\n"
            f"👥 **Members:** {guild.member_count:,}\n"
            f"📅 **Created:** {created}\n"
            f"📥 **Joined:** {joined}"
        )

    def _paginate_guilds(
        self, guilds: Sequence[discord.Guild], *, title: str, colour: int = EMBED_COLOUR
    ) -> tuple[list[discord.Embed], list[list[discord.Guild]]]:
        """Build paginated embeds + parallel guild-page lists for the View."""
        pages: list[discord.Embed] = []
        guild_pages: list[list[discord.Guild]] = []
        for i in range(0, max(1, len(guilds)), PER_PAGE):
            chunk = list(guilds[i : i + PER_PAGE])
            em = discord.Embed(title=title, colour=colour)
            if not chunk:
                em.description = "No servers to display."
            for g in chunk:
                em.add_field(
                    name=f"{g.name}  (`{g.id}`)",
                    value=self._guild_line(g),
                    inline=False,
                )
            em.set_footer(
                text=f"Total: {len(guilds)} server(s)"
            )
            pages.append(em)
            guild_pages.append(chunk)
        return pages, guild_pages

    def _paginate_ids(
        self, ids: list[int], *, title: str, colour: int = EMBED_COLOUR
    ) -> list[discord.Embed]:
        """Build paginated embeds for a plain list of IDs."""
        pages: list[discord.Embed] = []
        for i in range(0, max(1, len(ids)), PER_PAGE):
            chunk = ids[i : i + PER_PAGE]
            em = discord.Embed(title=title, colour=colour)
            if not chunk:
                em.description = "List is empty."
            else:
                lines: list[str] = []
                for gid in chunk:
                    guild = self.bot.get_guild(gid)
                    name = guild.name if guild else "Unknown / Not Joined"
                    status = "🟢" if guild else "⚫"
                    members = f" • {guild.member_count:,} members" if guild else ""
                    lines.append(f"{status} `{gid}` — **{name}**{members}")
                em.description = "\n".join(lines)
            em.set_footer(text=f"Total: {len(ids)} server(s)")
            pages.append(em)
        return pages

    # ── listeners ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Enforce whitelist / blacklist / lock on every new guild join."""
        locked: bool = await self.config.locked()
        blacklist: list[int] = await self.config.blacklist()
        whitelist: list[int] = await self.config.whitelist()

        # Blacklist always wins
        if guild.id in blacklist:
            log.info("Leaving BLACKLISTED guild: %s (%d)", guild.name, guild.id)
            await self._log_event(
                f"🚫 Blocked join to **blacklisted** server **{guild.name}** (`{guild.id}`)."
            )
            await guild.leave()
            return

        # Lock mode — reject everything new
        if locked:
            log.info("Leaving guild (LOCKED mode): %s (%d)", guild.name, guild.id)
            await self._log_event(
                f"🔒 Blocked join to **{guild.name}** (`{guild.id}`) — bot is *locked*."
            )
            await guild.leave()
            return

        # Normal whitelist check
        if guild.id not in whitelist:
            log.info("Leaving non-whitelisted guild: %s (%d)", guild.name, guild.id)
            await self._log_event(
                f"⛔ Left non-whitelisted server **{guild.name}** (`{guild.id}`)."
            )
            await guild.leave()
            return

        # Allowed — log it
        await self._log_event(
            f"✅ Joined whitelisted server **{guild.name}** (`{guild.id}`)."
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Log when the bot leaves / is removed from a guild."""
        await self._log_event(
            f"📤 Left/removed from **{guild.name}** (`{guild.id}`)."
        )

    # ═══════════════════════════════════════════════════════════
    #  Command Group
    # ═══════════════════════════════════════════════════════════

    @commands.hybrid_group(
        name="join",
        invoke_without_command=True,
        fallback="add",
    )
    @commands.is_owner()
    async def join_group(self, ctx: commands.Context, server_id: int) -> None:
        """Add a server to the whitelist.

        The bot will stay in this server when invited.

        Usage: ``[p]join <server_id>``
        """
        blacklist: list[int] = await self.config.blacklist()
        if server_id in blacklist:
            await ctx.send(
                f"⚠️ `{server_id}` is currently *blacklisted*. Remove it from "
                f"the blacklist first with `{ctx.clean_prefix}join unblacklist {server_id}`."
            )
            return

        async with self.config.whitelist() as wl:
            if server_id in wl:
                await ctx.send(f"✅ `{server_id}` is already whitelisted.")
                return
            wl.append(server_id)

        await ctx.send(f"✅ `{server_id}` has been added to the whitelist.")
        await self._log_event(f"✅ `{server_id}` whitelisted by **{ctx.author}**.")
        log.info("Whitelisted guild %d (by %s).", server_id, ctx.author)

    # ── remove ────────────────────────────────────────────────

    @join_group.command(name="remove")
    @commands.is_owner()
    async def join_remove(self, ctx: commands.Context, server_id: int) -> None:
        """Remove a server from the whitelist.

        If the bot is currently in that server it will leave immediately.

        Usage: ``[p]join remove <server_id>``
        """
        async with self.config.whitelist() as wl:
            if server_id not in wl:
                await ctx.send(f"⚠️ `{server_id}` is not on the whitelist.")
                return
            wl.remove(server_id)

        await ctx.send(f"🗑️ `{server_id}` removed from the whitelist.")
        await self._log_event(f"🗑️ `{server_id}` un-whitelisted by **{ctx.author}**.")

        guild = self.bot.get_guild(server_id)
        if guild is not None:
            await guild.leave()
            await ctx.send(f"👋 Left **{guild.name}**.")

    # ── whitelist (list) ──────────────────────────────────────

    @join_group.command(name="whitelist", aliases=["list", "wl"])
    @commands.is_owner()
    async def join_whitelist(self, ctx: commands.Context) -> None:
        """Show all whitelisted servers in a paginated embed.

        Usage: ``[p]join whitelist``
        """
        wl: list[int] = await self.config.whitelist()
        pages = self._paginate_ids(sorted(wl), title="📋 Whitelisted Servers")
        view = PaginatedView(pages, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    # ── blacklist ─────────────────────────────────────────────

    @join_group.command(name="blacklist", aliases=["bl", "block"])
    @commands.is_owner()
    async def join_blacklist(self, ctx: commands.Context, server_id: int) -> None:
        """Blacklist a server — the bot will leave and never rejoin.

        Also removes the server from the whitelist if present.

        Usage: ``[p]join blacklist <server_id>``
        """
        async with self.config.blacklist() as bl:
            if server_id in bl:
                await ctx.send(f"⚠️ `{server_id}` is already blacklisted.")
                return
            bl.append(server_id)

        # Remove from whitelist if present
        async with self.config.whitelist() as wl:
            if server_id in wl:
                wl.remove(server_id)

        await ctx.send(f"🚫 `{server_id}` has been blacklisted.")
        await self._log_event(f"🚫 `{server_id}` blacklisted by **{ctx.author}**.")

        guild = self.bot.get_guild(server_id)
        if guild is not None:
            name = guild.name
            await guild.leave()
            await ctx.send(f"👋 Left **{name}**.")

    @join_group.command(name="unblacklist", aliases=["unbl", "unblock"])
    @commands.is_owner()
    async def join_unblacklist(self, ctx: commands.Context, server_id: int) -> None:
        """Remove a server from the blacklist.

        Usage: ``[p]join unblacklist <server_id>``
        """
        async with self.config.blacklist() as bl:
            if server_id not in bl:
                await ctx.send(f"⚠️ `{server_id}` is not on the blacklist.")
                return
            bl.remove(server_id)

        await ctx.send(f"✅ `{server_id}` removed from the blacklist.")
        await self._log_event(f"✅ `{server_id}` un-blacklisted by **{ctx.author}**.")

    @join_group.command(name="blacklisted", aliases=["blist"])
    @commands.is_owner()
    async def join_blacklisted(self, ctx: commands.Context) -> None:
        """View all blacklisted servers.

        Usage: ``[p]join blacklisted``
        """
        bl: list[int] = await self.config.blacklist()
        pages = self._paginate_ids(sorted(bl), title="🚫 Blacklisted Servers", colour=0xE74C3C)
        view = PaginatedView(pages, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    # ── servers (interactive browser) ─────────────────────────

    @join_group.command(name="servers", aliases=["all", "browse"])
    @commands.is_owner()
    async def join_servers(self, ctx: commands.Context) -> None:
        """Browse all servers the bot is in with leave controls.

        A dropdown on each page lets you leave any listed server instantly.

        Usage: ``[p]join servers``
        """
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        if not guilds:
            await ctx.send("The bot is not in any servers.")
            return

        pages, guild_pages = self._paginate_guilds(guilds, title="🌐 All Servers")
        view = ServerPageView(
            pages, guild_pages, cog=self, author_id=ctx.author.id
        )
        await ctx.send(embed=pages[0], view=view)

    # ── info ──────────────────────────────────────────────────

    @join_group.command(name="info")
    @commands.is_owner()
    async def join_info(self, ctx: commands.Context, server_id: int) -> None:
        """Show detailed information about a specific server.

        Usage: ``[p]join info <server_id>``
        """
        guild = self.bot.get_guild(server_id)
        if guild is None:
            await ctx.send(f"⚠️ Bot is not in a server with ID `{server_id}`.")
            return

        whitelist: list[int] = await self.config.whitelist()
        blacklist: list[int] = await self.config.blacklist()
        status_parts: list[str] = []
        if guild.id in whitelist:
            status_parts.append("✅ Whitelisted")
        if guild.id in blacklist:
            status_parts.append("🚫 Blacklisted")
        if not status_parts:
            status_parts.append("⚪ Not listed")

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        roles = len(guild.roles)
        emojis = len(guild.emojis)
        boosts = guild.premium_subscription_count or 0
        boost_tier = guild.premium_tier
        created = discord.utils.format_dt(guild.created_at, style="F")
        created_rel = discord.utils.format_dt(guild.created_at, style="R")
        joined = (
            discord.utils.format_dt(guild.me.joined_at, style="F")
            if guild.me and guild.me.joined_at
            else "Unknown"
        )
        joined_rel = (
            discord.utils.format_dt(guild.me.joined_at, style="R")
            if guild.me and guild.me.joined_at
            else ""
        )
        verification = str(guild.verification_level).replace("_", " ").title()

        em = discord.Embed(title=guild.name, colour=EMBED_COLOUR)
        if guild.icon:
            em.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            em.set_image(url=guild.banner.url)

        em.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        em.add_field(name="Owner", value=str(guild.owner or "Unknown"), inline=True)
        em.add_field(name="Status", value=" • ".join(status_parts), inline=True)
        em.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
        em.add_field(name="Roles", value=str(roles), inline=True)
        em.add_field(name="Emojis", value=str(emojis), inline=True)
        em.add_field(
            name="Channels",
            value=f"💬 {text_channels} text · 🔊 {voice_channels} voice · 📁 {categories} categories",
            inline=False,
        )
        em.add_field(
            name="Boosts",
            value=f"Level {boost_tier} ({boosts} boost{'s' if boosts != 1 else ''})",
            inline=True,
        )
        em.add_field(name="Verification", value=verification, inline=True)
        em.add_field(name="Created", value=f"{created}\n{created_rel}", inline=False)
        em.add_field(name="Bot Joined", value=f"{joined}\n{joined_rel}", inline=False)

        if guild.features:
            em.add_field(
                name="Features",
                value=", ".join(f"`{f}`" for f in sorted(guild.features)[:15]),
                inline=False,
            )

        await ctx.send(embed=em)

    # ── search ────────────────────────────────────────────────

    @join_group.command(name="search", aliases=["find"])
    @commands.is_owner()
    async def join_search(self, ctx: commands.Context, *, query: str) -> None:
        """Search servers by name (case-insensitive).

        Usage: ``[p]join search <query>``
        """
        q = query.lower()
        matches = [g for g in self.bot.guilds if q in g.name.lower()]
        if not matches:
            await ctx.send(f"No servers matched `{query}`.")
            return

        matches.sort(key=lambda g: g.member_count or 0, reverse=True)
        pages, guild_pages = self._paginate_guilds(
            matches, title=f"🔍 Search: \"{query}\" — {len(matches)} result(s)"
        )
        view = ServerPageView(
            pages, guild_pages, cog=self, author_id=ctx.author.id
        )
        await ctx.send(embed=pages[0], view=view)

    # ── leave ─────────────────────────────────────────────────

    @join_group.command(name="leave")
    @commands.is_owner()
    async def join_leave(self, ctx: commands.Context, server_id: int) -> None:
        """Leave a server immediately by ID.

        Does NOT remove it from the whitelist — use ``remove`` for that.

        Usage: ``[p]join leave <server_id>``
        """
        guild = self.bot.get_guild(server_id)
        if guild is None:
            await ctx.send(f"⚠️ Bot is not in a server with ID `{server_id}`.")
            return

        name = guild.name
        await guild.leave()
        await ctx.send(f"👋 Left **{name}** (`{server_id}`).")
        await self._log_event(f"👋 Left **{name}** (`{server_id}`) — manual leave by **{ctx.author}**.")

    # ── purge ─────────────────────────────────────────────────

    @join_group.command(name="purge")
    @commands.is_owner()
    async def join_purge(self, ctx: commands.Context) -> None:
        """Leave ALL servers that are not whitelisted.

        Requires confirmation before executing.

        Usage: ``[p]join purge``
        """
        whitelist: list[int] = await self.config.whitelist()
        to_leave = [g for g in self.bot.guilds if g.id not in whitelist]
        if not to_leave:
            await ctx.send("✅ All current servers are whitelisted — nothing to purge.")
            return

        names = "\n".join(f"• **{g.name}** (`{g.id}`)" for g in to_leave[:20])
        extra = f"\n…and {len(to_leave) - 20} more" if len(to_leave) > 20 else ""
        em = discord.Embed(
            title="⚠️ Confirm Purge",
            description=(
                f"The bot will leave **{len(to_leave)}** non-whitelisted server(s):\n\n"
                f"{names}{extra}"
            ),
            colour=0xE74C3C,
        )

        view = ConfirmPurgeView(author_id=ctx.author.id)
        msg = await ctx.send(embed=em, view=view)
        await view.wait()

        if view.result is True:
            left: list[str] = []
            for g in to_leave:
                try:
                    await g.leave()
                    left.append(g.name)
                except discord.HTTPException:
                    pass
            await msg.edit(
                embed=discord.Embed(
                    title="🗑️ Purge Complete",
                    description=f"Left **{len(left)}** server(s).",
                    colour=0x2ECC71,
                ),
                view=None,
            )
            await self._log_event(
                f"🗑️ Purge by **{ctx.author}** — left {len(left)} server(s)."
            )
        else:
            await msg.edit(
                embed=discord.Embed(
                    title="Purge Cancelled",
                    description="No servers were left.",
                    colour=EMBED_COLOUR,
                ),
                view=None,
            )

    # ── lock / unlock ─────────────────────────────────────────

    @join_group.command(name="lock")
    @commands.is_owner()
    async def join_lock(self, ctx: commands.Context) -> None:
        """Lock the bot — reject ALL new server joins (even whitelisted).

        Usage: ``[p]join lock``
        """
        if await self.config.locked():
            await ctx.send("🔒 Already locked.")
            return
        await self.config.locked.set(True)
        await ctx.send("🔒 Bot is now **locked** — no new servers will be joined.")
        await self._log_event(f"🔒 Bot locked by **{ctx.author}**.")

    @join_group.command(name="unlock")
    @commands.is_owner()
    async def join_unlock(self, ctx: commands.Context) -> None:
        """Unlock the bot — resume normal whitelist behaviour.

        Usage: ``[p]join unlock``
        """
        if not await self.config.locked():
            await ctx.send("🔓 Already unlocked.")
            return
        await self.config.locked.set(False)
        await ctx.send("🔓 Bot is now **unlocked** — whitelist rules apply normally.")
        await self._log_event(f"🔓 Bot unlocked by **{ctx.author}**.")

    # ── log channel ───────────────────────────────────────────

    @join_group.command(name="log")
    @commands.is_owner()
    async def join_log(
        self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None
    ) -> None:
        """Set a channel for join/leave/block event logs.

        Pass no argument or "off" to disable logging.

        Usage: ``[p]join log #channel`` or ``[p]join log off``
        """
        # Check if the raw argument is "off"
        if channel is None:
            await self.config.log_channel.set(None)
            await ctx.send("📝 Event logging **disabled**.")
            return

        await self.config.log_channel.set(channel.id)
        await ctx.send(f"📝 Events will be logged to {channel.mention}.")

    # ── stats ─────────────────────────────────────────────────

    @join_group.command(name="stats")
    @commands.is_owner()
    async def join_stats(self, ctx: commands.Context) -> None:
        """Show a high-level overview of the bot's server footprint.

        Usage: ``[p]join stats``
        """
        whitelist: list[int] = await self.config.whitelist()
        blacklist: list[int] = await self.config.blacklist()
        locked: bool = await self.config.locked()
        log_channel: Optional[int] = await self.config.log_channel()

        total_guilds = len(self.bot.guilds)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        largest = max(self.bot.guilds, key=lambda g: g.member_count or 0) if self.bot.guilds else None
        smallest = min(self.bot.guilds, key=lambda g: g.member_count or 0) if self.bot.guilds else None
        not_whitelisted = [g for g in self.bot.guilds if g.id not in whitelist]

        em = discord.Embed(title="📊 Server Stats", colour=EMBED_COLOUR)
        em.add_field(name="Servers", value=f"{total_guilds:,}", inline=True)
        em.add_field(name="Total Members", value=f"{total_members:,}", inline=True)
        em.add_field(name="Whitelisted", value=str(len(whitelist)), inline=True)
        em.add_field(name="Blacklisted", value=str(len(blacklist)), inline=True)
        em.add_field(name="Not Whitelisted (in bot)", value=str(len(not_whitelisted)), inline=True)
        em.add_field(
            name="Lock Status",
            value="🔒 Locked" if locked else "🔓 Unlocked",
            inline=True,
        )
        if largest:
            em.add_field(
                name="Largest Server",
                value=f"**{largest.name}** ({largest.member_count:,})",
                inline=False,
            )
        if smallest and smallest != largest:
            em.add_field(
                name="Smallest Server",
                value=f"**{smallest.name}** ({smallest.member_count:,})",
                inline=False,
            )
        log_ch = self.bot.get_channel(log_channel) if log_channel else None
        em.add_field(
            name="Log Channel",
            value=log_ch.mention if log_ch else "Disabled",
            inline=False,
        )
        await ctx.send(embed=em)

    # ── settings ──────────────────────────────────────────────

    @join_group.command(name="settings", aliases=["config"])
    @commands.is_owner()
    async def join_settings(self, ctx: commands.Context) -> None:
        """Display current ServerWhitelist configuration.

        Usage: ``[p]join settings``
        """
        whitelist: list[int] = await self.config.whitelist()
        blacklist: list[int] = await self.config.blacklist()
        locked: bool = await self.config.locked()
        log_channel: Optional[int] = await self.config.log_channel()
        log_ch = self.bot.get_channel(log_channel) if log_channel else None

        em = discord.Embed(title="⚙️ ServerWhitelist Settings", colour=EMBED_COLOUR)
        em.add_field(name="Whitelisted", value=str(len(whitelist)), inline=True)
        em.add_field(name="Blacklisted", value=str(len(blacklist)), inline=True)
        em.add_field(name="Current Servers", value=str(len(self.bot.guilds)), inline=True)
        em.add_field(
            name="Lock Mode",
            value="🔒 **ON** — all new joins rejected" if locked else "🔓 OFF — whitelist rules apply",
            inline=False,
        )
        em.add_field(
            name="Log Channel",
            value=log_ch.mention if log_ch else "Not set (`[p]join log #channel`)",
            inline=False,
        )
        em.add_field(
            name="Quick Reference",
            value=(
                f"`{ctx.clean_prefix}join <id>` — whitelist a server\n"
                f"`{ctx.clean_prefix}join remove <id>` — un-whitelist & leave\n"
                f"`{ctx.clean_prefix}join blacklist <id>` — blacklist & leave\n"
                f"`{ctx.clean_prefix}join servers` — browse all servers\n"
                f"`{ctx.clean_prefix}join purge` — leave all non-whitelisted\n"
                f"`{ctx.clean_prefix}join lock/unlock` — toggle lock mode"
            ),
            inline=False,
        )
        await ctx.send(embed=em)

    # ── export ────────────────────────────────────────────────

    @join_group.command(name="export")
    @commands.is_owner()
    async def join_export(self, ctx: commands.Context) -> None:
        """Export the full server list as a .txt file.

        Includes ID, name, member count, whitelist/blacklist status, and join date.

        Usage: ``[p]join export``
        """
        whitelist: list[int] = await self.config.whitelist()
        blacklist: list[int] = await self.config.blacklist()

        lines: list[str] = [
            f"{'ID':<22} {'Members':>8}  {'Status':<14} {'Joined':<26} Name",
            "─" * 100,
        ]
        for g in sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True):
            status_parts = []
            if g.id in whitelist:
                status_parts.append("WL")
            if g.id in blacklist:
                status_parts.append("BL")
            status = ",".join(status_parts) if status_parts else "—"
            joined = (
                g.me.joined_at.strftime("%Y-%m-%d %H:%M UTC")
                if g.me and g.me.joined_at
                else "Unknown"
            )
            lines.append(
                f"{g.id:<22} {g.member_count or 0:>8,}  {status:<14} {joined:<26} {g.name}"
            )

        content = "\n".join(lines)
        buf = io.BytesIO(content.encode())
        file = discord.File(buf, filename="server_export.txt")
        await ctx.send("📄 Here's your server export:", file=file)
