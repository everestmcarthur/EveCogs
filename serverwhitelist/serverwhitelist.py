"""
ServerWhitelist v3.0 — Ultimate Server Management Cog for Red-DiscordBot
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

Attempt Tracking & Auto-Ban
  • ``[p]join attempts``      — view all servers with join attempts
  • ``[p]join attempts reset <id>`` — reset attempts for a server
  • ``[p]join attempts resetall``   — reset all attempt counters
  • ``[p]join maxattempts <n>``     — set the max attempts before auto-ban (default 5)

Owner DM
  • Bot DMs the server owner before leaving non-whitelisted/locked servers
  • Customisable with ``[p]join setmessage <text>`` / ``[p]join resetmessage``

Settings
  • ``[p]join settings``      — display current config at a glance

Export
  • ``[p]join export``        — upload a .txt or .csv file of all guilds
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

DEFAULT_LEAVE_MESSAGE = (
    "Hello! I'm sorry, your server is not in my whitelist. "
    "You can always try to request it to be added! Just ask the bot's owner! "
    "If you can, however, don't add this bot until permission is given, "
    "otherwise it will get banned and never allowed to be whitelisted! "
    "Have a great day!"
)


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
        await self.cog._log_event(
            title="👋 Left Server (Browser)",
            description=f"Left **{name}** (`{guild_id}`) via server browser.",
            colour=0xE67E22,
        )
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
    """Ultimate server management — whitelist, blacklist, browse, leave, lock, attempt tracking & more."""

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
            max_attempts=5,  # auto-ban threshold
            leave_message=None,  # custom DM text (None → DEFAULT_LEAVE_MESSAGE)
            # Per-guild attempt tracking: { "guild_id_str": { "count": int, "last_attempt": iso, "owner_id": int, "name": str } }
            join_attempts={},
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
            len(merged),
        )

    # ── internal helpers ──────────────────────────────────────

    async def _log_event(
        self,
        description: str,
        *,
        title: str = "ServerWhitelist",
        colour: int = EMBED_COLOUR,
        fields: list[tuple[str, str, bool]] | None = None,
        thumbnail_url: str | None = None,
        footer: str | None = None,
    ) -> None:
        """Send a rich event embed to the configured log channel, if any."""
        channel_id: Optional[int] = await self.config.log_channel()
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            em = discord.Embed(
                title=title,
                description=description,
                colour=colour,
                timestamp=datetime.now(timezone.utc),
            )
            if thumbnail_url:
                em.set_thumbnail(url=thumbnail_url)
            if fields:
                for name, value, inline in fields:
                    em.add_field(name=name, value=value, inline=inline)
            em.set_footer(text=footer or "ServerWhitelist v3.0")
            await channel.send(embed=em)
        except discord.HTTPException:
            pass

    def _guild_detail_fields(self, guild: discord.Guild) -> list[tuple[str, str, bool]]:
        """Build a list of (name, value, inline) tuples with rich server info."""
        owner = guild.owner
        owner_str = f"{owner} (`{owner.id}`)" if owner else "Unknown"
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
        text_ch = len(guild.text_channels)
        voice_ch = len(guild.voice_channels)
        categories = len(guild.categories)
        roles = len(guild.roles)
        emojis = len(guild.emojis)
        boosts = guild.premium_subscription_count or 0
        boost_tier = guild.premium_tier
        verification = str(guild.verification_level).replace("_", " ").title()
        humans = sum(1 for m in guild.members if not m.bot) if guild.chunked else "?"
        bots = sum(1 for m in guild.members if m.bot) if guild.chunked else "?"

        fields: list[tuple[str, str, bool]] = [
            ("Server ID", f"`{guild.id}`", True),
            ("Owner", owner_str, True),
            ("Members", f"{guild.member_count:,} (👤 {humans} humans · 🤖 {bots} bots)", False),
            ("Channels", f"💬 {text_ch} text · 🔊 {voice_ch} voice · 📁 {categories} categories", False),
            ("Roles", str(roles), True),
            ("Emojis", str(emojis), True),
            ("Boosts", f"Level {boost_tier} ({boosts} boost{'s' if boosts != 1 else ''})", True),
            ("Verification", verification, True),
            ("Created", f"{created} ({created_rel})", False),
            ("Bot Joined", f"{joined} {joined_rel}".strip(), False),
        ]
        if guild.features:
            fields.append((
                "Features",
                ", ".join(f"`{f}`" for f in sorted(guild.features)[:20]),
                False,
            ))
        return fields

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

    # ── DM the server owner ───────────────────────────────────

    async def _dm_owner(
        self,
        guild: discord.Guild,
        *,
        reason: str,
        extra: str | None = None,
    ) -> bool:
        """Attempt to DM the server owner before the bot leaves.

        Returns True if the DM was sent successfully, False otherwise.
        """
        owner = guild.owner
        if owner is None:
            log.warning("Could not resolve owner for guild %s (%d).", guild.name, guild.id)
            return False

        leave_msg: str | None = await self.config.leave_message()
        text = leave_msg or DEFAULT_LEAVE_MESSAGE

        em = discord.Embed(
            title="⚠️ Server Not Whitelisted",
            description=text,
            colour=0xFFA500,
            timestamp=datetime.now(timezone.utc),
        )
        em.add_field(name="Server", value=f"**{guild.name}** (`{guild.id}`)", inline=False)
        em.add_field(name="Reason", value=reason, inline=False)
        if extra:
            em.add_field(name="⚠️ Warning", value=extra, inline=False)
        em.set_footer(text="ServerWhitelist")
        if guild.icon:
            em.set_thumbnail(url=guild.icon.url)

        try:
            await owner.send(embed=em)
            log.info("Sent leave DM to owner %s (%d) of guild %s.", owner, owner.id, guild.name)
            return True
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.warning("Could not DM owner %s (%d): %s", owner, owner.id, exc)
            return False

    # ── self-ban ──────────────────────────────────────────────

    async def _self_ban(self, guild: discord.Guild) -> bool:
        """Attempt to ban the bot itself from the server.

        This prevents the server from re-inviting the bot until they
        manually unban it.  Requires the bot to have ``ban_members``
        permission in the guild — if it doesn't, we silently fall back
        to a normal leave.

        Returns True if the self-ban succeeded, False otherwise.
        """
        me = guild.me
        if me is None:
            return False

        # Check if the bot has ban_members permission
        if not me.guild_permissions.ban_members:
            log.info(
                "Cannot self-ban from %s (%d) — missing ban_members permission.",
                guild.name, guild.id,
            )
            return False

        try:
            await guild.ban(
                me,
                reason="ServerWhitelist: Auto-ban — this server is blacklisted.",
                delete_message_days=0,
            )
            log.info("Self-banned from guild %s (%d).", guild.name, guild.id)
            return True
        except discord.Forbidden:
            log.warning(
                "Self-ban forbidden in %s (%d) despite having permission (role hierarchy?).",
                guild.name, guild.id,
            )
            return False
        except discord.HTTPException as exc:
            log.warning("Self-ban failed in %s (%d): %s", guild.name, guild.id, exc)
            return False

    # ── attempt tracking ──────────────────────────────────────

    async def _record_attempt(self, guild: discord.Guild) -> tuple[int, bool]:
        """Record a join attempt for a guild.

        Returns (current_count, was_auto_banned).
        """
        max_attempts: int = await self.config.max_attempts()
        gid_str = str(guild.id)
        now_iso = datetime.now(timezone.utc).isoformat()

        async with self.config.join_attempts() as attempts:
            entry = attempts.get(gid_str, {
                "count": 0,
                "first_attempt": now_iso,
                "last_attempt": now_iso,
                "owner_id": guild.owner_id,
                "name": guild.name,
            })
            entry["count"] = entry.get("count", 0) + 1
            entry["last_attempt"] = now_iso
            entry["owner_id"] = guild.owner_id
            entry["name"] = guild.name
            if "first_attempt" not in entry:
                entry["first_attempt"] = now_iso
            attempts[gid_str] = entry
            count = entry["count"]

        auto_banned = False
        if count >= max_attempts:
            # Auto-ban: add to blacklist, remove from whitelist
            async with self.config.blacklist() as bl:
                if guild.id not in bl:
                    bl.append(guild.id)
                    auto_banned = True
            async with self.config.whitelist() as wl:
                if guild.id in wl:
                    wl.remove(guild.id)
            if auto_banned:
                log.warning(
                    "AUTO-BANNED guild %s (%d) after %d unauthorized join attempts.",
                    guild.name, guild.id, count,
                )

        return count, auto_banned

    # ── listeners ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Enforce whitelist / blacklist / lock on every new guild join."""
        locked: bool = await self.config.locked()
        blacklist: list[int] = await self.config.blacklist()
        whitelist: list[int] = await self.config.whitelist()
        max_attempts: int = await self.config.max_attempts()

        # Build common log fields for rich logging
        icon_url = guild.icon.url if guild.icon else None
        owner = guild.owner
        owner_str = f"{owner} (`{owner.id}`)" if owner else "Unknown"
        log_fields: list[tuple[str, str, bool]] = [
            ("Server", f"**{guild.name}** (`{guild.id}`)", False),
            ("Owner", owner_str, True),
            ("Members", f"{guild.member_count:,}" if guild.member_count else "?", True),
            ("Created", discord.utils.format_dt(guild.created_at, style="R"), True),
        ]
        if guild.features:
            log_fields.append((
                "Features",
                ", ".join(f"`{f}`" for f in sorted(guild.features)[:10]),
                False,
            ))

        # ── Blacklisted ──────────────────────────────────────
        if guild.id in blacklist:
            log.info("Leaving BLACKLISTED guild: %s (%d)", guild.name, guild.id)

            # Record the attempt anyway
            count, _ = await self._record_attempt(guild)

            await self._dm_owner(
                guild,
                reason="This server is *permanently blacklisted* and cannot use this bot.",
                extra="⛔ This server has been *banned*. Continued attempts will be ignored.",
            )
            # Attempt to self-ban (prevents re-invite until manually unbanned)
            self_banned = await self._self_ban(guild)

            ban_note = "✅ Bot self-banned from server." if self_banned else "⚠️ Could not self-ban (missing permission) — left normally."
            await self._log_event(
                title="🚫 Blocked — Blacklisted Server",
                description=f"Rejected join to **blacklisted** server **{guild.name}**.",
                colour=0xE74C3C,
                fields=log_fields + [
                    ("Attempts", str(count), True),
                    ("Self-Ban", ban_note, False),
                ],
                thumbnail_url=icon_url,
            )
            if not self_banned:
                await guild.leave()
            return

        # ── Locked mode ──────────────────────────────────────
        if locked:
            log.info("Leaving guild (LOCKED mode): %s (%d)", guild.name, guild.id)

            await self._dm_owner(
                guild,
                reason="The bot is currently in *lock mode* and not accepting any new servers.",
            )
            await self._log_event(
                title="🔒 Blocked — Bot Locked",
                description=f"Rejected join to **{guild.name}** — bot is *locked*.",
                colour=0x95A5A6,
                fields=log_fields,
                thumbnail_url=icon_url,
            )
            await guild.leave()
            return

        # ── Not whitelisted ──────────────────────────────────
        if guild.id not in whitelist:
            count, auto_banned = await self._record_attempt(guild)
            remaining = max(0, max_attempts - count)

            log.info(
                "Leaving non-whitelisted guild: %s (%d) — attempt %d/%d",
                guild.name, guild.id, count, max_attempts,
            )

            # Build warning text for DM
            if auto_banned:
                extra = (
                    f"🚨 *This server has been automatically banned after "
                    f"{count} unauthorized join attempt(s).* The bot has banned "
                    f"itself from this server and will *never* join again. "
                    f"Contact the bot owner if you believe this is a mistake."
                )
                reason = f"Not whitelisted — *auto-banned* after {count}/{max_attempts} attempts."
            elif remaining <= 2 and remaining > 0:
                extra = (
                    f"⚠️ *Warning:* This server has {count}/{max_attempts} attempts used. "
                    f"Only *{remaining}* attempt(s) remain before an automatic permanent ban!"
                )
                reason = f"Not whitelisted (attempt {count}/{max_attempts})."
            else:
                extra = (
                    f"ℹ️ Attempt {count}/{max_attempts}. "
                    f"After {max_attempts} attempts the server will be *permanently banned*."
                ) if count > 1 else None
                reason = f"Not whitelisted (attempt {count}/{max_attempts})."

            await self._dm_owner(guild, reason=reason, extra=extra)

            # Log event with colour escalation
            if auto_banned:
                log_colour = 0xE74C3C  # Red
                log_title = "🚨 Auto-Banned — Max Attempts Reached"
                log_desc = (
                    f"**{guild.name}** (`{guild.id}`) has been *automatically blacklisted* "
                    f"after **{count}** unauthorized join attempts."
                )
            elif remaining <= 2:
                log_colour = 0xE67E22  # Orange
                log_title = f"⚠️ Non-Whitelisted Join (Attempt {count}/{max_attempts})"
                log_desc = (
                    f"Rejected **{guild.name}** — only **{remaining}** attempt(s) remain "
                    f"before auto-ban."
                )
            else:
                log_colour = 0xF1C40F  # Yellow
                log_title = f"⛔ Non-Whitelisted Join (Attempt {count}/{max_attempts})"
                log_desc = f"Rejected **{guild.name}** — not on the whitelist."

            # If auto-banned this attempt, try to self-ban from the server
            self_banned = False
            if auto_banned:
                self_banned = await self._self_ban(guild)

            extra_fields = [
                ("Attempts", f"{count}/{max_attempts}", True),
                ("Remaining", str(remaining) if not auto_banned else "BANNED", True),
            ]
            if auto_banned:
                ban_note = "✅ Bot self-banned from server." if self_banned else "⚠️ Could not self-ban (missing permission) — left normally."
                extra_fields.append(("Self-Ban", ban_note, False))

            await self._log_event(
                title=log_title,
                description=log_desc,
                colour=log_colour,
                fields=log_fields + extra_fields,
                thumbnail_url=icon_url,
            )
            if not self_banned:
                await guild.leave()
            return

        # ── Allowed — whitelisted ────────────────────────────
        await self._log_event(
            title="✅ Joined Whitelisted Server",
            description=f"Successfully joined **{guild.name}** (`{guild.id}`).",
            colour=0x2ECC71,
            fields=log_fields,
            thumbnail_url=icon_url,
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Log when the bot leaves / is removed from a guild."""
        icon_url = guild.icon.url if guild.icon else None
        owner = guild.owner
        owner_str = f"{owner} (`{owner.id}`)" if owner else "Unknown"
        await self._log_event(
            title="📤 Left / Removed From Server",
            description=f"No longer in **{guild.name}** (`{guild.id}`).",
            colour=0x95A5A6,
            fields=[
                ("Server", f"**{guild.name}** (`{guild.id}`)", False),
                ("Owner", owner_str, True),
                ("Members", f"{guild.member_count:,}" if guild.member_count else "?", True),
            ],
            thumbnail_url=icon_url,
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
        Also resets any accumulated join attempts for that server.

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

        # Reset attempts on whitelist
        async with self.config.join_attempts() as attempts:
            attempts.pop(str(server_id), None)

        await ctx.send(f"✅ `{server_id}` has been added to the whitelist. Any previous join attempts have been cleared.")
        await self._log_event(
            title="✅ Server Whitelisted",
            description=f"`{server_id}` whitelisted by **{ctx.author}**.",
            colour=0x2ECC71,
        )
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
        await self._log_event(
            title="🗑️ Server Un-Whitelisted",
            description=f"`{server_id}` un-whitelisted by **{ctx.author}**.",
            colour=0xE67E22,
        )

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
        await self._log_event(
            title="🚫 Server Blacklisted",
            description=f"`{server_id}` blacklisted by **{ctx.author}**.",
            colour=0xE74C3C,
        )

        guild = self.bot.get_guild(server_id)
        if guild is not None:
            name = guild.name
            await guild.leave()
            await ctx.send(f"👋 Left **{name}**.")

    @join_group.command(name="unblacklist", aliases=["unbl", "unblock"])
    @commands.is_owner()
    async def join_unblacklist(self, ctx: commands.Context, server_id: int) -> None:
        """Remove a server from the blacklist.

        Also resets accumulated join attempts for that server.

        Usage: ``[p]join unblacklist <server_id>``
        """
        async with self.config.blacklist() as bl:
            if server_id not in bl:
                await ctx.send(f"⚠️ `{server_id}` is not on the blacklist.")
                return
            bl.remove(server_id)

        # Reset attempts on unblacklist
        async with self.config.join_attempts() as attempts:
            attempts.pop(str(server_id), None)

        await ctx.send(f"✅ `{server_id}` removed from the blacklist. Join attempts have been reset.")
        await self._log_event(
            title="✅ Server Un-Blacklisted",
            description=f"`{server_id}` un-blacklisted by **{ctx.author}**. Attempts reset.",
            colour=0x2ECC71,
        )

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

        Includes owner, channels, roles, emojis, boosts, verification,
        features, whitelist/blacklist status, and join attempts.

        Usage: ``[p]join info <server_id>``
        """
        guild = self.bot.get_guild(server_id)
        if guild is None:
            await ctx.send(f"⚠️ Bot is not in a server with ID `{server_id}`.")
            return

        whitelist: list[int] = await self.config.whitelist()
        blacklist: list[int] = await self.config.blacklist()
        join_attempts: dict = await self.config.join_attempts()

        status_parts: list[str] = []
        if guild.id in whitelist:
            status_parts.append("✅ Whitelisted")
        if guild.id in blacklist:
            status_parts.append("🚫 Blacklisted")
        if not status_parts:
            status_parts.append("⚪ Not listed")

        em = discord.Embed(title=guild.name, colour=EMBED_COLOUR)
        if guild.icon:
            em.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            em.set_image(url=guild.banner.url)

        # Detailed fields
        fields = self._guild_detail_fields(guild)
        for name, value, inline in fields:
            em.add_field(name=name, value=value, inline=inline)

        em.add_field(name="Status", value=" • ".join(status_parts), inline=False)

        # Attempt info
        attempt_data = join_attempts.get(str(server_id))
        if attempt_data:
            max_att = await self.config.max_attempts()
            em.add_field(
                name="Join Attempts",
                value=(
                    f"**{attempt_data['count']}** / {max_att}\n"
                    f"First: `{attempt_data.get('first_attempt', '?')}`\n"
                    f"Last: `{attempt_data.get('last_attempt', '?')}`"
                ),
                inline=False,
            )

        if guild.description:
            em.add_field(name="Description", value=guild.description, inline=False)

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
        icon_url = guild.icon.url if guild.icon else None
        await guild.leave()
        await ctx.send(f"👋 Left **{name}** (`{server_id}`).")
        await self._log_event(
            title="👋 Left Server (Manual)",
            description=f"Left **{name}** (`{server_id}`) — manual leave by **{ctx.author}**.",
            colour=0xE67E22,
            thumbnail_url=icon_url,
        )

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

        names = "\n".join(f"• **{g.name}** (`{g.id}`) — {g.member_count:,} members" for g in to_leave[:20])
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
                    description=f"Left **{len(left)}** server(s):\n" + "\n".join(f"• {n}" for n in left[:30]),
                    colour=0x2ECC71,
                ),
                view=None,
            )
            await self._log_event(
                title="🗑️ Purge Executed",
                description=f"**{ctx.author}** purged {len(left)} non-whitelisted server(s).",
                colour=0xE74C3C,
                fields=[("Servers Left", "\n".join(f"• {n}" for n in left[:20]) or "None", False)],
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
        await self._log_event(
            title="🔒 Bot Locked",
            description=f"Bot locked by **{ctx.author}** — all new joins will be rejected.",
            colour=0x95A5A6,
        )

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
        await self._log_event(
            title="🔓 Bot Unlocked",
            description=f"Bot unlocked by **{ctx.author}** — whitelist rules restored.",
            colour=0x2ECC71,
        )

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

        Includes server counts, member totals, attempt stats, and more.

        Usage: ``[p]join stats``
        """
        whitelist: list[int] = await self.config.whitelist()
        blacklist: list[int] = await self.config.blacklist()
        locked: bool = await self.config.locked()
        log_channel: Optional[int] = await self.config.log_channel()
        max_attempts: int = await self.config.max_attempts()
        join_attempts: dict = await self.config.join_attempts()

        total_guilds = len(self.bot.guilds)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        largest = max(self.bot.guilds, key=lambda g: g.member_count or 0) if self.bot.guilds else None
        smallest = min(self.bot.guilds, key=lambda g: g.member_count or 0) if self.bot.guilds else None
        not_whitelisted = [g for g in self.bot.guilds if g.id not in whitelist]

        # Attempt stats
        total_attempt_servers = len(join_attempts)
        total_attempt_count = sum(e.get("count", 0) for e in join_attempts.values())
        auto_banned_count = sum(1 for e in join_attempts.values() if e.get("count", 0) >= max_attempts)

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
            inline=True,
        )
        em.add_field(name="Max Attempts", value=str(max_attempts), inline=True)
        em.add_field(
            name="Attempt Tracking",
            value=(
                f"**{total_attempt_servers}** server(s) tracked\n"
                f"**{total_attempt_count}** total attempts\n"
                f"**{auto_banned_count}** auto-banned"
            ),
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
        max_attempts: int = await self.config.max_attempts()
        leave_message: str | None = await self.config.leave_message()
        join_attempts: dict = await self.config.join_attempts()

        log_ch = self.bot.get_channel(log_channel) if log_channel else None
        msg_preview = (leave_message or DEFAULT_LEAVE_MESSAGE)[:120] + "…" if len(leave_message or DEFAULT_LEAVE_MESSAGE) > 120 else (leave_message or DEFAULT_LEAVE_MESSAGE)

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
            inline=True,
        )
        em.add_field(name="Max Attempts", value=f"**{max_attempts}** (before auto-ban)", inline=True)
        em.add_field(name="Tracked Servers", value=str(len(join_attempts)), inline=True)
        em.add_field(
            name="Leave DM Message",
            value=f"```{msg_preview}```",
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
                f"`{ctx.clean_prefix}join lock/unlock` — toggle lock mode\n"
                f"`{ctx.clean_prefix}join attempts` — view join attempts\n"
                f"`{ctx.clean_prefix}join maxattempts <n>` — set auto-ban threshold\n"
                f"`{ctx.clean_prefix}join setmessage <text>` — custom leave DM\n"
                f"`{ctx.clean_prefix}join resetmessage` — reset DM to default"
            ),
            inline=False,
        )
        await ctx.send(embed=em)

    # ── export ────────────────────────────────────────────────

    @join_group.command(name="export")
    @commands.is_owner()
    async def join_export(self, ctx: commands.Context) -> None:
        """Export the full server list as a .txt file.

        Includes ID, name, member count, whitelist/blacklist status, join date, and owner.

        Usage: ``[p]join export``
        """
        whitelist: list[int] = await self.config.whitelist()
        blacklist: list[int] = await self.config.blacklist()
        join_attempts: dict = await self.config.join_attempts()

        lines: list[str] = [
            f"{'ID':<22} {'Members':>8}  {'Status':<14} {'Attempts':>8}  {'Joined':<26} {'Owner':<30} Name",
            "─" * 140,
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
            owner = str(g.owner) if g.owner else "Unknown"
            att = join_attempts.get(str(g.id), {}).get("count", 0)
            lines.append(
                f"{g.id:<22} {g.member_count or 0:>8,}  {status:<14} {att:>8}  {joined:<26} {owner:<30} {g.name}"
            )

        # Also export non-joined servers from attempts
        tracked_ids = set(int(k) for k in join_attempts.keys())
        current_ids = set(g.id for g in self.bot.guilds)
        non_joined = tracked_ids - current_ids
        if non_joined:
            lines.append("")
            lines.append("── Tracked Servers (Not Currently Joined) ──")
            lines.append(f"{'ID':<22} {'Attempts':>8}  {'Last Attempt':<26} {'Owner ID':<22} Name")
            lines.append("─" * 100)
            for gid in sorted(non_joined):
                entry = join_attempts[str(gid)]
                lines.append(
                    f"{gid:<22} {entry.get('count', 0):>8}  "
                    f"{entry.get('last_attempt', '?'):<26} "
                    f"{entry.get('owner_id', '?')!s:<22} "
                    f"{entry.get('name', 'Unknown')}"
                )

        content = "\n".join(lines)
        buf = io.BytesIO(content.encode())
        file = discord.File(buf, filename="server_export.txt")
        await ctx.send("📄 Here's your server export:", file=file)

    # ═══════════════════════════════════════════════════════════
    #  Attempt Tracking Commands
    # ═══════════════════════════════════════════════════════════

    @join_group.group(name="attempts", aliases=["att"], invoke_without_command=True)
    @commands.is_owner()
    async def join_attempts_group(self, ctx: commands.Context) -> None:
        """View all servers with recorded join attempts.

        Shows attempt count, last attempt time, and auto-ban status.

        Usage: ``[p]join attempts``
        """
        join_attempts: dict = await self.config.join_attempts()
        max_attempts: int = await self.config.max_attempts()
        blacklist: list[int] = await self.config.blacklist()

        if not join_attempts:
            await ctx.send("📊 No join attempts have been recorded yet.")
            return

        # Sort by count descending
        sorted_entries = sorted(
            join_attempts.items(),
            key=lambda kv: kv[1].get("count", 0),
            reverse=True,
        )

        pages: list[discord.Embed] = []
        for i in range(0, len(sorted_entries), PER_PAGE):
            chunk = sorted_entries[i : i + PER_PAGE]
            em = discord.Embed(
                title="📊 Join Attempt Tracker",
                colour=EMBED_COLOUR,
            )
            for gid_str, entry in chunk:
                gid = int(gid_str)
                count = entry.get("count", 0)
                name = entry.get("name", "Unknown")
                owner_id = entry.get("owner_id", "?")
                first = entry.get("first_attempt", "?")
                last = entry.get("last_attempt", "?")
                is_banned = gid in blacklist
                status = "🚫 BANNED" if is_banned else (
                    f"⚠️ {count}/{max_attempts}" if count >= max_attempts - 2
                    else f"📋 {count}/{max_attempts}"
                )

                em.add_field(
                    name=f"{name}  (`{gid}`)",
                    value=(
                        f"**Status:** {status}\n"
                        f"**Attempts:** {count}\n"
                        f"**Owner ID:** `{owner_id}`\n"
                        f"**First:** `{first[:19] if isinstance(first, str) else first}`\n"
                        f"**Last:** `{last[:19] if isinstance(last, str) else last}`"
                    ),
                    inline=False,
                )
            em.set_footer(text=f"Total: {len(sorted_entries)} tracked server(s) • Max: {max_attempts} attempts")
            pages.append(em)

        view = PaginatedView(pages, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    @join_attempts_group.command(name="reset")
    @commands.is_owner()
    async def join_attempts_reset(self, ctx: commands.Context, server_id: int) -> None:
        """Reset the join attempt counter for a specific server.

        This does NOT remove it from the blacklist — use ``unblacklist`` for that.

        Usage: ``[p]join attempts reset <server_id>``
        """
        async with self.config.join_attempts() as attempts:
            if str(server_id) not in attempts:
                await ctx.send(f"⚠️ No attempts recorded for `{server_id}`.")
                return
            old = attempts.pop(str(server_id))

        await ctx.send(
            f"✅ Reset attempts for `{server_id}` (was **{old.get('count', 0)}** attempts)."
        )
        await self._log_event(
            title="🔄 Attempts Reset",
            description=f"Attempts for `{server_id}` (`{old.get('name', '?')}`) reset by **{ctx.author}** (was {old.get('count', 0)}).",
            colour=0x3498DB,
        )

    @join_attempts_group.command(name="resetall")
    @commands.is_owner()
    async def join_attempts_resetall(self, ctx: commands.Context) -> None:
        """Reset ALL join attempt counters.

        Does NOT affect whitelist or blacklist.

        Usage: ``[p]join attempts resetall``
        """
        join_attempts: dict = await self.config.join_attempts()
        count = len(join_attempts)
        await self.config.join_attempts.set({})
        await ctx.send(f"✅ Cleared attempt data for **{count}** server(s).")
        await self._log_event(
            title="🔄 All Attempts Reset",
            description=f"All attempt counters ({count} servers) cleared by **{ctx.author}**.",
            colour=0x3498DB,
        )

    # ═══════════════════════════════════════════════════════════
    #  Max Attempts Configuration
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="maxattempts", aliases=["setmax", "limit"])
    @commands.is_owner()
    async def join_maxattempts(self, ctx: commands.Context, count: int) -> None:
        """Set the maximum number of join attempts before a server is auto-banned.

        Must be at least 1.

        Usage: ``[p]join maxattempts 5``
        """
        if count < 1:
            await ctx.send("⚠️ Max attempts must be at least **1**.")
            return

        old = await self.config.max_attempts()
        await self.config.max_attempts.set(count)
        await ctx.send(f"✅ Max attempts set to **{count}** (was {old}).")
        await self._log_event(
            title="⚙️ Max Attempts Updated",
            description=f"Max attempts changed from **{old}** → **{count}** by **{ctx.author}**.",
            colour=0x3498DB,
        )

    # ═══════════════════════════════════════════════════════════
    #  Custom Leave DM Message
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="setmessage", aliases=["setmsg", "dmtext"])
    @commands.is_owner()
    async def join_setmessage(self, ctx: commands.Context, *, text: str) -> None:
        """Set a custom DM message sent to server owners when the bot leaves.

        The message is sent in a rich embed along with the server name, reason, and warnings.

        Usage: ``[p]join setmessage Hello! Your server isn't whitelisted...``
        """
        if len(text) > 1500:
            await ctx.send("⚠️ Message is too long (max 1,500 characters).")
            return

        await self.config.leave_message.set(text)
        await ctx.send(
            f"✅ Leave DM message updated!\n\n**Preview:**\n>>> {text[:500]}"
        )

    @join_group.command(name="resetmessage", aliases=["resetmsg", "defaultmsg"])
    @commands.is_owner()
    async def join_resetmessage(self, ctx: commands.Context) -> None:
        """Reset the leave DM message to the default.

        Usage: ``[p]join resetmessage``
        """
        await self.config.leave_message.set(None)
        await ctx.send(
            f"✅ Leave DM message reset to default:\n\n>>> {DEFAULT_LEAVE_MESSAGE}"
        )
