"""
ServerWhitelist v4.0 — The Ultimate Server Management Cog for Red-DiscordBot
=============================================================================

Owner-only commands to control which Discord servers the bot may
operate in.  Uses Red's Config for persistence and discord.py Views for
interactive UI (paginated embeds, dropdowns, approval buttons, etc.).

Feature set
-----------
Whitelist & Blacklist
  • ``[p]join <id>``             — whitelist a server
  • ``[p]join remove <id>``      — un-whitelist (optionally leave)
  • ``[p]join blacklist <id>``   — blacklist (auto-leave & never rejoin)
  • ``[p]join unblacklist <id>`` — remove from blacklist
  • ``[p]join whitelist``        — paginated whitelist
  • ``[p]join blacklisted``      — paginated blacklist

Server Browser
  • ``[p]join servers``          — paginated with 🚪 leave dropdown
  • ``[p]join info <id>``        — detailed embed
  • ``[p]join search <query>``   — search by name
  • ``[p]join stats``            — high-level overview

Bulk Actions
  • ``[p]join leave <id>``       — leave immediately
  • ``[p]join purge``            — leave all non-whitelisted (confirm)

Bot Lock
  • ``[p]join lock / unlock``    — reject ALL new joins

Logging
  • ``[p]join log <channel>``    — rich event logging
  • ``[p]join log off``          — disable

Attempt Tracking & Auto-Ban
  • ``[p]join attempts``         — view tracked servers
  • ``[p]join attempts reset``   — reset one / all
  • ``[p]join maxattempts <n>``  — set threshold (default 5)

Owner DM
  • DMs server owner before leaving
  • ``[p]join setmessage / resetmessage``

Whitelist Request System (NEW v4)
  • Server owners can request whitelist via DM button
  • Bot owner gets approve/deny embed with full server info
  • ``[p]join requests`` — view pending requests
  • ``[p]join requests approve/deny <id>`` — manual approve/deny

Server Notes & Tags (NEW v4)
  • ``[p]join note <id> <text>`` — attach notes
  • ``[p]join note <id>``        — view note
  • ``[p]join tag <id> <tag>``   — categorize (partner, testing, etc.)
  • ``[p]join untag <id> <tag>`` — remove tag
  • ``[p]join tags``             — view all tags

Invite Audit (NEW v4)
  • Checks audit log on join to find who invited the bot

Temporary Whitelist (NEW v4)
  • ``[p]join temp <id> <duration>`` — whitelist for X time
  • Auto-removes & leaves when expired

Server Requirements (NEW v4)
  • ``[p]join minmembers <n>``   — reject small servers
  • ``[p]join maxmembers <n>``   — reject huge servers

Trusted Inviters (NEW v4)
  • ``[p]join trust <user_id>``  — auto-whitelist on invite
  • ``[p]join untrust <user_id>``
  • ``[p]join trusted``          — view list

Owner Alerts (NEW v4)
  • ``[p]join alerts on/off``    — DM bot owner on events

Backup & Restore (NEW v4)
  • ``[p]join backup``           — export full config JSON
  • ``[p]join restore``          — import config from attached file

Settings & Export
  • ``[p]join settings``         — full config overview
  • ``[p]join export``           — .txt server dump
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

import discord
from discord import Interaction
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.serverwhitelist")

EMBED_COLOUR = 0x2F3136
PER_PAGE = 8  # guilds per paginated page
VERSION = "4.0"

DEFAULT_LEAVE_MESSAGE = (
    "Hello! I'm sorry, your server is not in my whitelist. "
    "You can always try to request it to be added! Just ask the bot's owner! "
    "If you can, however, don't add this bot until permission is given, "
    "otherwise it will get banned and never allowed to be whitelisted! "
    "Have a great day!"
)

DURATION_RE = re.compile(
    r"(?:(\d+)\s*d(?:ays?)?)?\s*"
    r"(?:(\d+)\s*h(?:ours?)?)?\s*"
    r"(?:(\d+)\s*m(?:in(?:utes?)?)?)?\s*$",
    re.IGNORECASE,
)


def parse_duration(text: str) -> Optional[timedelta]:
    """Parse a human-friendly duration like '7d', '12h', '2d 6h 30m'."""
    m = DURATION_RE.match(text.strip())
    if m is None:
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    if days == 0 and hours == 0 and minutes == 0:
        return None
    return timedelta(days=days, hours=hours, minutes=minutes)


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
#  Server Leave Select View
# ═══════════════════════════════════════════════════════════════════

class ServerLeaveSelect(discord.ui.Select):
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
        super().__init__(placeholder="🚪 Select a server to leave…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: Interaction) -> None:
        guild_id = int(self.values[0])
        guild = self.cog.bot.get_guild(guild_id)
        if guild is None:
            await interaction.response.send_message("Bot is no longer in that server.", ephemeral=True)
            return
        name = guild.name
        await guild.leave()
        await self.cog._log_event(
            title="👋 Left Server (Browser)",
            description=f"Left **{name}** (`{guild_id}`) via server browser.",
            colour=0xE67E22,
        )
        await interaction.response.send_message(f"👋 Left **{name}** (`{guild_id}`).", ephemeral=True)


class ServerPageView(discord.ui.View):
    def __init__(self, pages, guild_pages, *, cog, author_id, timeout=180.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.guild_pages = guild_pages
        self.cog = cog
        self.author_id = author_id
        self.current = 0
        self._rebuild_select()
        self._update_buttons()

    def _rebuild_select(self):
        for item in self.children[:]:
            if isinstance(item, ServerLeaveSelect):
                self.remove_item(item)
        if self.guild_pages[self.current]:
            self.add_item(ServerLeaveSelect(self.guild_pages[self.current], cog=self.cog))

    def _update_buttons(self):
        self.first_btn.disabled = self.current == 0
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        self.last_btn.disabled = self.current >= len(self.pages) - 1
        self.page_indicator.label = f"{self.current + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the bot owner can use these controls.", ephemeral=True)
            return False
        return True

    async def _show(self, interaction):
        self._update_buttons()
        self._rebuild_select()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def first_btn(self, interaction, button):
        self.current = 0
        await self._show(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction, button):
        self.current = max(0, self.current - 1)
        await self._show(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_indicator(self, interaction, button):
        await interaction.response.defer()

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction, button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        await self._show(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def last_btn(self, interaction, button):
        self.current = len(self.pages) - 1
        await self._show(interaction)


# ═══════════════════════════════════════════════════════════════════
#  Confirm View (reusable)
# ═══════════════════════════════════════════════════════════════════

class ConfirmView(discord.ui.View):
    def __init__(self, *, author_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.result: Optional[bool] = None

    async def interaction_check(self, interaction):
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction, button):
        self.result = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.result = False
        self.stop()
        await interaction.response.defer()


# ═══════════════════════════════════════════════════════════════════
#  Whitelist Request View (sent in owner DM)
# ═══════════════════════════════════════════════════════════════════

class WhitelistRequestView(discord.ui.View):
    """Button sent to the server owner's DM so they can request whitelisting."""

    def __init__(self, *, cog: "ServerWhitelist", guild_id: int, guild_name: str):
        # Persistent view — no timeout
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.guild_name = guild_name

    @discord.ui.button(
        label="📩 Request Whitelist",
        style=discord.ButtonStyle.success,
        custom_id="swl_request_whitelist",
    )
    async def request_btn(self, interaction: Interaction, button: discord.ui.Button):
        # Check if already requested
        requests: dict = await self.cog.config.whitelist_requests()
        gid_str = str(self.guild_id)
        if gid_str in requests:
            await interaction.response.send_message(
                "📨 A whitelist request for this server is already pending! Please be patient.",
                ephemeral=True,
            )
            return

        # Record the request
        now_iso = datetime.now(timezone.utc).isoformat()
        async with self.cog.config.whitelist_requests() as reqs:
            reqs[gid_str] = {
                "name": self.guild_name,
                "requester_id": interaction.user.id,
                "requester_name": str(interaction.user),
                "requested_at": now_iso,
            }

        await interaction.response.send_message(
            "✅ Your whitelist request has been sent to the bot owner! "
            "You'll be notified if it's approved.",
            ephemeral=True,
        )

        # Notify bot owner
        await self.cog._notify_owner_of_request(
            guild_id=self.guild_id,
            guild_name=self.guild_name,
            requester=interaction.user,
        )

        # Disable the button
        button.disabled = True
        button.label = "📨 Request Sent"
        button.style = discord.ButtonStyle.secondary
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass


# ═══════════════════════════════════════════════════════════════════
#  Approval View (sent to bot owner)
# ═══════════════════════════════════════════════════════════════════

class ApprovalView(discord.ui.View):
    """Approve / Deny buttons sent to the bot owner's DM for whitelist requests."""

    def __init__(self, *, cog: "ServerWhitelist", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="swl_approve")
    async def approve_btn(self, interaction: Interaction, button: discord.ui.Button):
        gid_str = str(self.guild_id)

        # Add to whitelist
        async with self.cog.config.whitelist() as wl:
            if self.guild_id not in wl:
                wl.append(self.guild_id)

        # Reset attempts
        async with self.cog.config.join_attempts() as attempts:
            attempts.pop(gid_str, None)

        # Remove from requests
        request_data = None
        async with self.cog.config.whitelist_requests() as reqs:
            request_data = reqs.pop(gid_str, None)

        # Notify requester
        if request_data:
            try:
                requester = await self.cog.bot.fetch_user(request_data["requester_id"])
                em = discord.Embed(
                    title="✅ Whitelist Request Approved!",
                    description=(
                        f"Your whitelist request for **{request_data['name']}** (`{self.guild_id}`) "
                        f"has been *approved*! You can now add the bot to your server."
                    ),
                    colour=0x2ECC71,
                    timestamp=datetime.now(timezone.utc),
                )
                await requester.send(embed=em)
            except (discord.HTTPException, discord.NotFound):
                pass

        await interaction.response.send_message(
            f"✅ `{self.guild_id}` has been whitelisted! The requester has been notified.",
            ephemeral=True,
        )

        # Update the message to show it was approved
        for item in self.children:
            item.disabled = True
        button.label = "✅ Approved"
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await self.cog._log_event(
            title="✅ Whitelist Request Approved",
            description=f"`{self.guild_id}` approved via request system.",
            colour=0x2ECC71,
        )

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="swl_deny")
    async def deny_btn(self, interaction: Interaction, button: discord.ui.Button):
        gid_str = str(self.guild_id)

        # Remove from requests
        request_data = None
        async with self.cog.config.whitelist_requests() as reqs:
            request_data = reqs.pop(gid_str, None)

        # Notify requester
        if request_data:
            try:
                requester = await self.cog.bot.fetch_user(request_data["requester_id"])
                em = discord.Embed(
                    title="❌ Whitelist Request Denied",
                    description=(
                        f"Your whitelist request for **{request_data['name']}** (`{self.guild_id}`) "
                        f"has been *denied*."
                    ),
                    colour=0xE74C3C,
                    timestamp=datetime.now(timezone.utc),
                )
                await requester.send(embed=em)
            except (discord.HTTPException, discord.NotFound):
                pass

        await interaction.response.send_message(
            f"❌ Request for `{self.guild_id}` denied. The requester has been notified.",
            ephemeral=True,
        )

        for item in self.children:
            item.disabled = True
        button.label = "❌ Denied"
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await self.cog._log_event(
            title="❌ Whitelist Request Denied",
            description=f"`{self.guild_id}` denied via request system.",
            colour=0xE74C3C,
        )


# ═══════════════════════════════════════════════════════════════════
#  Main Cog
# ═══════════════════════════════════════════════════════════════════

class ServerWhitelist(commands.Cog):
    """The ultimate server management cog — whitelist, blacklist, browse, leave,
    lock, attempt tracking, request system, notes, tags, temp whitelist,
    trusted inviters, invite audit, owner alerts, backup/restore & more."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=827364510293, force_registration=True)
        self.config.register_global(
            # Core
            whitelist=[],
            blacklist=[],
            locked=False,
            log_channel=None,
            # Attempts
            max_attempts=5,
            join_attempts={},
            # DM
            leave_message=None,
            # Server requirements
            min_members=0,
            max_members=0,  # 0 = no limit
            # Trusted inviters
            trusted_inviters=[],
            # Owner alerts
            owner_alerts=False,
            # Temp whitelist: { "guild_id_str": { "expires": iso, "added_by": str } }
            temp_whitelist={},
            # Notes: { "guild_id_str": "note text" }
            server_notes={},
            # Tags: { "guild_id_str": ["tag1", "tag2"] }
            server_tags={},
            # Whitelist requests: { "guild_id_str": { "name": str, "requester_id": int, ... } }
            whitelist_requests={},
        )
        self._temp_task: Optional[asyncio.Task] = None

    # ── lifecycle ─────────────────────────────────────────────

    async def cog_load(self) -> None:
        current_ids = [g.id for g in self.bot.guilds]
        async with self.config.whitelist() as wl:
            merged = list(set(wl) | set(current_ids))
            wl.clear()
            wl.extend(merged)
        log.info(
            "ServerWhitelist v%s loaded — %d guilds merged (%d total WL).",
            VERSION, len(current_ids), len(merged),
        )
        # Start temp whitelist expiry checker
        self._temp_task = self.bot.loop.create_task(self._temp_whitelist_loop())

    async def cog_unload(self) -> None:
        if self._temp_task and not self._temp_task.done():
            self._temp_task.cancel()

    # ── temp whitelist background loop ────────────────────────

    async def _temp_whitelist_loop(self) -> None:
        """Check every 60 seconds for expired temp-whitelisted servers."""
        await self.bot.wait_until_ready()
        while True:
            try:
                now = datetime.now(timezone.utc)
                expired: list[tuple[int, dict]] = []

                async with self.config.temp_whitelist() as tw:
                    for gid_str, data in list(tw.items()):
                        expires = datetime.fromisoformat(data["expires"])
                        if now >= expires:
                            expired.append((int(gid_str), data))
                            del tw[gid_str]

                for gid, data in expired:
                    # Remove from whitelist
                    async with self.config.whitelist() as wl:
                        if gid in wl:
                            wl.remove(gid)

                    guild = self.bot.get_guild(gid)
                    name = guild.name if guild else data.get("name", str(gid))

                    await self._log_event(
                        title="⏰ Temp Whitelist Expired",
                        description=f"**{name}** (`{gid}`) temp whitelist has expired. Removed from whitelist.",
                        colour=0xE67E22,
                    )
                    await self._alert_owner(
                        f"⏰ Temp whitelist expired for **{name}** (`{gid}`)."
                    )

                    if guild is not None:
                        await self._dm_owner(
                            guild,
                            reason="Your temporary whitelist period has expired.",
                        )
                        await guild.leave()

            except asyncio.CancelledError:
                return
            except Exception as exc:
                log.error("Temp whitelist loop error: %s", exc, exc_info=True)

            await asyncio.sleep(60)

    # ═══════════════════════════════════════════════════════════
    #  Internal Helpers
    # ═══════════════════════════════════════════════════════════

    async def _log_event(
        self, description: str, *, title: str = "ServerWhitelist",
        colour: int = EMBED_COLOUR, fields: list[tuple[str, str, bool]] | None = None,
        thumbnail_url: str | None = None, footer: str | None = None,
    ) -> None:
        channel_id: Optional[int] = await self.config.log_channel()
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            em = discord.Embed(
                title=title, description=description, colour=colour,
                timestamp=datetime.now(timezone.utc),
            )
            if thumbnail_url:
                em.set_thumbnail(url=thumbnail_url)
            if fields:
                for name, value, inline in fields:
                    em.add_field(name=name, value=value, inline=inline)
            em.set_footer(text=footer or f"ServerWhitelist v{VERSION}")
            await channel.send(embed=em)
        except discord.HTTPException:
            pass

    async def _alert_owner(self, message: str) -> None:
        """DM the bot owner if owner alerts are enabled."""
        if not await self.config.owner_alerts():
            return
        owner_ids = self.bot.owner_ids or set()
        if self.bot.owner_id:
            owner_ids = owner_ids | {self.bot.owner_id}
        for oid in owner_ids:
            try:
                user = await self.bot.fetch_user(oid)
                em = discord.Embed(
                    title="🔔 ServerWhitelist Alert",
                    description=message,
                    colour=EMBED_COLOUR,
                    timestamp=datetime.now(timezone.utc),
                )
                await user.send(embed=em)
            except (discord.HTTPException, discord.NotFound):
                pass

    async def _notify_owner_of_request(
        self, *, guild_id: int, guild_name: str, requester: discord.User,
    ) -> None:
        """Send the bot owner a DM with approve/deny buttons for a whitelist request."""
        owner_ids = self.bot.owner_ids or set()
        if self.bot.owner_id:
            owner_ids = owner_ids | {self.bot.owner_id}

        em = discord.Embed(
            title="📩 Whitelist Request",
            description=(
                f"**{requester}** (`{requester.id}`) is requesting whitelist for:\n\n"
                f"**Server:** {guild_name}\n"
                f"**Server ID:** `{guild_id}`"
            ),
            colour=0x3498DB,
            timestamp=datetime.now(timezone.utc),
        )
        em.set_footer(text="Use the buttons below or [p]join requests to manage.")

        view = ApprovalView(cog=self, guild_id=guild_id)

        for oid in owner_ids:
            try:
                user = await self.bot.fetch_user(oid)
                await user.send(embed=em, view=view)
            except (discord.HTTPException, discord.NotFound):
                pass

    def _guild_detail_fields(self, guild: discord.Guild) -> list[tuple[str, str, bool]]:
        owner = guild.owner
        owner_str = f"{owner} (`{owner.id}`)" if owner else "Unknown"
        created = discord.utils.format_dt(guild.created_at, style="F")
        created_rel = discord.utils.format_dt(guild.created_at, style="R")
        joined = (
            discord.utils.format_dt(guild.me.joined_at, style="F")
            if guild.me and guild.me.joined_at else "Unknown"
        )
        joined_rel = (
            discord.utils.format_dt(guild.me.joined_at, style="R")
            if guild.me and guild.me.joined_at else ""
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
            fields.append(("Features", ", ".join(f"`{f}`" for f in sorted(guild.features)[:20]), False))
        return fields

    @staticmethod
    def _guild_line(guild: discord.Guild) -> str:
        owner = guild.owner or "Unknown"
        created = discord.utils.format_dt(guild.created_at, style="R")
        joined = discord.utils.format_dt(guild.me.joined_at, style="R") if guild.me and guild.me.joined_at else "?"
        return (
            f"👑 **Owner:** {owner}\n"
            f"👥 **Members:** {guild.member_count:,}\n"
            f"📅 **Created:** {created}\n"
            f"📥 **Joined:** {joined}"
        )

    def _paginate_guilds(self, guilds, *, title, colour=EMBED_COLOUR):
        pages, guild_pages = [], []
        for i in range(0, max(1, len(guilds)), PER_PAGE):
            chunk = list(guilds[i:i + PER_PAGE])
            em = discord.Embed(title=title, colour=colour)
            if not chunk:
                em.description = "No servers to display."
            for g in chunk:
                em.add_field(name=f"{g.name}  (`{g.id}`)", value=self._guild_line(g), inline=False)
            em.set_footer(text=f"Total: {len(guilds)} server(s)")
            pages.append(em)
            guild_pages.append(chunk)
        return pages, guild_pages

    def _paginate_ids(self, ids, *, title, colour=EMBED_COLOUR):
        pages = []
        for i in range(0, max(1, len(ids)), PER_PAGE):
            chunk = ids[i:i + PER_PAGE]
            em = discord.Embed(title=title, colour=colour)
            if not chunk:
                em.description = "List is empty."
            else:
                lines = []
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
        self, guild: discord.Guild, *, reason: str, extra: str | None = None,
        include_request_button: bool = False,
    ) -> bool:
        owner = guild.owner
        if owner is None:
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
        em.set_footer(text=f"ServerWhitelist v{VERSION}")
        if guild.icon:
            em.set_thumbnail(url=guild.icon.url)

        view = None
        if include_request_button:
            blacklist = await self.config.blacklist()
            if guild.id not in blacklist:
                view = WhitelistRequestView(cog=self, guild_id=guild.id, guild_name=guild.name)

        try:
            await owner.send(embed=em, view=view)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    # ── invite audit ──────────────────────────────────────────

    async def _audit_inviter(self, guild: discord.Guild) -> Optional[str]:
        """Try to find who invited the bot via the guild's audit log."""
        try:
            me = guild.me
            if me is None:
                return None
            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.bot_add, limit=10
            ):
                if entry.target and entry.target.id == me.id:
                    return f"{entry.user} (`{entry.user.id}`)" if entry.user else None
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    # ── attempt tracking ──────────────────────────────────────

    async def _record_attempt(self, guild: discord.Guild) -> tuple[int, bool]:
        max_attempts: int = await self.config.max_attempts()
        gid_str = str(guild.id)
        now_iso = datetime.now(timezone.utc).isoformat()

        async with self.config.join_attempts() as attempts:
            entry = attempts.get(gid_str, {
                "count": 0, "first_attempt": now_iso, "last_attempt": now_iso,
                "owner_id": guild.owner_id, "name": guild.name,
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
            async with self.config.blacklist() as bl:
                if guild.id not in bl:
                    bl.append(guild.id)
                    auto_banned = True
            async with self.config.whitelist() as wl:
                if guild.id in wl:
                    wl.remove(guild.id)
            if auto_banned:
                log.warning("AUTO-BANNED guild %s (%d) after %d attempts.", guild.name, guild.id, count)

        return count, auto_banned

    # ═══════════════════════════════════════════════════════════
    #  Listeners
    # ═══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        locked: bool = await self.config.locked()
        blacklist: list[int] = await self.config.blacklist()
        whitelist: list[int] = await self.config.whitelist()
        max_attempts: int = await self.config.max_attempts()
        min_members: int = await self.config.min_members()
        max_members: int = await self.config.max_members()
        trusted: list[int] = await self.config.trusted_inviters()

        icon_url = guild.icon.url if guild.icon else None
        owner = guild.owner
        owner_str = f"{owner} (`{owner.id}`)" if owner else "Unknown"

        # Audit who invited
        inviter_str = await self._audit_inviter(guild)

        log_fields: list[tuple[str, str, bool]] = [
            ("Server", f"**{guild.name}** (`{guild.id}`)", False),
            ("Owner", owner_str, True),
            ("Members", f"{guild.member_count:,}" if guild.member_count else "?", True),
            ("Created", discord.utils.format_dt(guild.created_at, style="R"), True),
        ]
        if inviter_str:
            log_fields.append(("Invited By", inviter_str, False))
        if guild.features:
            log_fields.append(("Features", ", ".join(f"`{f}`" for f in sorted(guild.features)[:10]), False))

        # ── Check if a trusted inviter added the bot ─────────
        if inviter_str and trusted:
            # Extract user ID from inviter_str
            try:
                inviter_id_match = re.search(r"\(`(\d+)`\)", inviter_str)
                if inviter_id_match:
                    inviter_id = int(inviter_id_match.group(1))
                    if inviter_id in trusted and guild.id not in whitelist:
                        # Auto-whitelist
                        async with self.config.whitelist() as wl:
                            wl.append(guild.id)
                        whitelist = await self.config.whitelist()  # refresh
                        await self._log_event(
                            title="🔑 Auto-Whitelisted (Trusted Inviter)",
                            description=(
                                f"**{guild.name}** auto-whitelisted because "
                                f"trusted inviter {inviter_str} added the bot."
                            ),
                            colour=0x2ECC71, fields=log_fields, thumbnail_url=icon_url,
                        )
                        await self._alert_owner(
                            f"🔑 **{guild.name}** (`{guild.id}`) was auto-whitelisted "
                            f"by trusted inviter {inviter_str}."
                        )
            except (ValueError, AttributeError):
                pass

        # ── Blacklisted ──────────────────────────────────────
        if guild.id in blacklist:
            count, _ = await self._record_attempt(guild)
            await self._dm_owner(guild, reason="This server is *permanently blacklisted*.",
                                 extra="⛔ This server has been *banned*. Continued attempts will be ignored.")
            await self._log_event(title="🚫 Blocked — Blacklisted", colour=0xE74C3C,
                                  description=f"Rejected **blacklisted** server **{guild.name}**.",
                                  fields=log_fields + [("Attempts", str(count), True)], thumbnail_url=icon_url)
            await self._alert_owner(f"🚫 Blacklisted server **{guild.name}** (`{guild.id}`) tried to add the bot (attempt {count}).")
            await guild.leave()
            return

        # ── Locked ───────────────────────────────────────────
        if locked:
            await self._dm_owner(guild, reason="The bot is currently in *lock mode*.")
            await self._log_event(title="🔒 Blocked — Locked", colour=0x95A5A6,
                                  description=f"Rejected **{guild.name}** — bot is locked.",
                                  fields=log_fields, thumbnail_url=icon_url)
            await self._alert_owner(f"🔒 **{guild.name}** (`{guild.id}`) tried to join while bot is locked.")
            await guild.leave()
            return

        # ── Member requirements ──────────────────────────────
        member_count = guild.member_count or 0
        if min_members > 0 and member_count < min_members and guild.id not in whitelist:
            await self._dm_owner(
                guild, reason=f"This server has {member_count:,} members, below the minimum of {min_members:,}.",
                include_request_button=True,
            )
            await self._log_event(
                title="📏 Blocked — Below Min Members",
                description=f"**{guild.name}** has {member_count:,} members (min: {min_members:,}).",
                colour=0xE67E22, fields=log_fields, thumbnail_url=icon_url,
            )
            await self._alert_owner(f"📏 **{guild.name}** (`{guild.id}`) rejected — {member_count:,} members (min {min_members:,}).")
            await guild.leave()
            return

        if max_members > 0 and member_count > max_members and guild.id not in whitelist:
            await self._dm_owner(
                guild, reason=f"This server has {member_count:,} members, above the maximum of {max_members:,}.",
                include_request_button=True,
            )
            await self._log_event(
                title="📏 Blocked — Above Max Members",
                description=f"**{guild.name}** has {member_count:,} members (max: {max_members:,}).",
                colour=0xE67E22, fields=log_fields, thumbnail_url=icon_url,
            )
            await self._alert_owner(f"📏 **{guild.name}** (`{guild.id}`) rejected — {member_count:,} members (max {max_members:,}).")
            await guild.leave()
            return

        # ── Not whitelisted ──────────────────────────────────
        if guild.id not in whitelist:
            count, auto_banned = await self._record_attempt(guild)
            remaining = max(0, max_attempts - count)

            if auto_banned:
                extra = (
                    f"🚨 *This server has been automatically banned after "
                    f"{count} unauthorized join attempt(s).* The bot will *never* "
                    f"join this server again. Contact the bot owner if you believe "
                    f"this is a mistake."
                )
                reason = f"Not whitelisted — *auto-banned* after {count}/{max_attempts} attempts."
                include_req = False
            elif remaining <= 2 and remaining > 0:
                extra = (
                    f"⚠️ *Warning:* This server has {count}/{max_attempts} attempts used. "
                    f"Only *{remaining}* attempt(s) remain before an automatic permanent ban!"
                )
                reason = f"Not whitelisted (attempt {count}/{max_attempts})."
                include_req = True
            else:
                extra = (
                    f"ℹ️ Attempt {count}/{max_attempts}. "
                    f"After {max_attempts} attempts the server will be *permanently banned*."
                ) if count > 1 else None
                reason = f"Not whitelisted (attempt {count}/{max_attempts})."
                include_req = True

            await self._dm_owner(guild, reason=reason, extra=extra, include_request_button=include_req)

            if auto_banned:
                log_colour, log_title = 0xE74C3C, "🚨 Auto-Banned — Max Attempts"
                log_desc = f"**{guild.name}** auto-blacklisted after **{count}** attempts."
            elif remaining <= 2:
                log_colour = 0xE67E22
                log_title = f"⚠️ Non-Whitelisted (Attempt {count}/{max_attempts})"
                log_desc = f"Rejected **{guild.name}** — **{remaining}** attempt(s) remain."
            else:
                log_colour = 0xF1C40F
                log_title = f"⛔ Non-Whitelisted (Attempt {count}/{max_attempts})"
                log_desc = f"Rejected **{guild.name}** — not on the whitelist."

            await self._log_event(
                title=log_title, description=log_desc, colour=log_colour,
                fields=log_fields + [
                    ("Attempts", f"{count}/{max_attempts}", True),
                    ("Remaining", str(remaining) if not auto_banned else "BANNED", True),
                ], thumbnail_url=icon_url,
            )
            await self._alert_owner(
                f"{'🚨 AUTO-BANNED' if auto_banned else '⛔ Rejected'}: **{guild.name}** "
                f"(`{guild.id}`) — attempt {count}/{max_attempts}."
            )
            await guild.leave()
            return

        # ── Allowed ──────────────────────────────────────────
        await self._log_event(
            title="✅ Joined Whitelisted Server",
            description=f"Joined **{guild.name}** (`{guild.id}`).",
            colour=0x2ECC71, fields=log_fields, thumbnail_url=icon_url,
        )
        await self._alert_owner(f"✅ Joined whitelisted server **{guild.name}** (`{guild.id}`).")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        icon_url = guild.icon.url if guild.icon else None
        owner = guild.owner
        owner_str = f"{owner} (`{owner.id}`)" if owner else "Unknown"
        await self._log_event(
            title="📤 Left / Removed",
            description=f"No longer in **{guild.name}** (`{guild.id}`).",
            colour=0x95A5A6,
            fields=[
                ("Server", f"**{guild.name}** (`{guild.id}`)", False),
                ("Owner", owner_str, True),
                ("Members", f"{guild.member_count:,}" if guild.member_count else "?", True),
            ],
            thumbnail_url=icon_url,
        )
        await self._alert_owner(f"📤 Left/removed from **{guild.name}** (`{guild.id}`).")

    # ═══════════════════════════════════════════════════════════
    #  Command Group
    # ═══════════════════════════════════════════════════════════

    @commands.group(name="join", invoke_without_command=True)
    @commands.is_owner()
    async def join_group(self, ctx: commands.Context, server_id: int) -> None:
        """Add a server to the whitelist."""
        blacklist = await self.config.blacklist()
        if server_id in blacklist:
            await ctx.send(f"⚠️ `{server_id}` is blacklisted. Use `{ctx.clean_prefix}join unblacklist {server_id}` first.")
            return
        async with self.config.whitelist() as wl:
            if server_id in wl:
                await ctx.send(f"✅ `{server_id}` is already whitelisted.")
                return
            wl.append(server_id)
        async with self.config.join_attempts() as att:
            att.pop(str(server_id), None)
        # Remove from requests if present
        async with self.config.whitelist_requests() as reqs:
            reqs.pop(str(server_id), None)
        await ctx.send(f"✅ `{server_id}` whitelisted. Attempts cleared.")
        await self._log_event(title="✅ Whitelisted", description=f"`{server_id}` whitelisted by **{ctx.author}**.", colour=0x2ECC71)

    # ── remove ────────────────────────────────────────────────

    @join_group.command(name="remove")
    @commands.is_owner()
    async def join_remove(self, ctx: commands.Context, server_id: int) -> None:
        """Un-whitelist a server (and leave if currently in it)."""
        async with self.config.whitelist() as wl:
            if server_id not in wl:
                await ctx.send(f"⚠️ `{server_id}` is not whitelisted.")
                return
            wl.remove(server_id)
        # Also remove temp entry
        async with self.config.temp_whitelist() as tw:
            tw.pop(str(server_id), None)
        await ctx.send(f"🗑️ `{server_id}` removed from whitelist.")
        await self._log_event(title="🗑️ Un-Whitelisted", description=f"`{server_id}` un-whitelisted by **{ctx.author}**.", colour=0xE67E22)
        guild = self.bot.get_guild(server_id)
        if guild:
            await guild.leave()
            await ctx.send(f"👋 Left **{guild.name}**.")

    # ── whitelist (view) ──────────────────────────────────────

    @join_group.command(name="whitelist", aliases=["list", "wl"])
    @commands.is_owner()
    async def join_whitelist(self, ctx: commands.Context) -> None:
        """View all whitelisted servers."""
        wl = await self.config.whitelist()
        notes = await self.config.server_notes()
        tags = await self.config.server_tags()
        temp = await self.config.temp_whitelist()

        pages = []
        ids = sorted(wl)
        for i in range(0, max(1, len(ids)), PER_PAGE):
            chunk = ids[i:i + PER_PAGE]
            em = discord.Embed(title="📋 Whitelisted Servers", colour=EMBED_COLOUR)
            if not chunk:
                em.description = "List is empty."
            else:
                lines = []
                for gid in chunk:
                    guild = self.bot.get_guild(gid)
                    name = guild.name if guild else "Unknown / Not Joined"
                    status = "🟢" if guild else "⚫"
                    members = f" • {guild.member_count:,} members" if guild else ""
                    line = f"{status} `{gid}` — **{name}**{members}"
                    # Add tags
                    gtags = tags.get(str(gid), [])
                    if gtags:
                        line += " " + " ".join(f"`{t}`" for t in gtags)
                    # Add temp indicator
                    if str(gid) in temp:
                        exp = temp[str(gid)].get("expires", "?")
                        line += f" ⏰ expires `{exp[:16]}`"
                    # Add note preview
                    note = notes.get(str(gid), "")
                    if note:
                        line += f"\n  📝 _{note[:60]}{'…' if len(note) > 60 else ''}_"
                    lines.append(line)
                em.description = "\n".join(lines)
            em.set_footer(text=f"Total: {len(ids)} server(s)")
            pages.append(em)

        view = PaginatedView(pages, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    # ── blacklist commands ────────────────────────────────────

    @join_group.command(name="blacklist", aliases=["bl", "block"])
    @commands.is_owner()
    async def join_blacklist(self, ctx: commands.Context, server_id: int) -> None:
        """Blacklist a server — leave and never rejoin."""
        async with self.config.blacklist() as bl:
            if server_id in bl:
                await ctx.send(f"⚠️ `{server_id}` is already blacklisted.")
                return
            bl.append(server_id)
        async with self.config.whitelist() as wl:
            if server_id in wl:
                wl.remove(server_id)
        async with self.config.temp_whitelist() as tw:
            tw.pop(str(server_id), None)
        await ctx.send(f"🚫 `{server_id}` blacklisted.")
        await self._log_event(title="🚫 Blacklisted", description=f"`{server_id}` blacklisted by **{ctx.author}**.", colour=0xE74C3C)
        guild = self.bot.get_guild(server_id)
        if guild:
            await guild.leave()
            await ctx.send(f"👋 Left **{guild.name}**.")

    @join_group.command(name="unblacklist", aliases=["unbl", "unblock"])
    @commands.is_owner()
    async def join_unblacklist(self, ctx: commands.Context, server_id: int) -> None:
        """Remove a server from the blacklist. Resets attempts."""
        async with self.config.blacklist() as bl:
            if server_id not in bl:
                await ctx.send(f"⚠️ `{server_id}` is not blacklisted.")
                return
            bl.remove(server_id)
        async with self.config.join_attempts() as att:
            att.pop(str(server_id), None)
        await ctx.send(f"✅ `{server_id}` un-blacklisted. Attempts reset.")
        await self._log_event(title="✅ Un-Blacklisted", description=f"`{server_id}` un-blacklisted by **{ctx.author}**.", colour=0x2ECC71)

    @join_group.command(name="blacklisted", aliases=["blist"])
    @commands.is_owner()
    async def join_blacklisted(self, ctx: commands.Context) -> None:
        """View all blacklisted servers."""
        bl = await self.config.blacklist()
        pages = self._paginate_ids(sorted(bl), title="🚫 Blacklisted Servers", colour=0xE74C3C)
        view = PaginatedView(pages, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    # ── servers browser ───────────────────────────────────────

    @join_group.command(name="servers", aliases=["all", "browse"])
    @commands.is_owner()
    async def join_servers(self, ctx: commands.Context) -> None:
        """Browse all servers with leave controls."""
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        if not guilds:
            await ctx.send("Not in any servers.")
            return
        pages, guild_pages = self._paginate_guilds(guilds, title="🌐 All Servers")
        view = ServerPageView(pages, guild_pages, cog=self, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    # ── info ──────────────────────────────────────────────────

    @join_group.command(name="info")
    @commands.is_owner()
    async def join_info(self, ctx: commands.Context, server_id: int) -> None:
        """Detailed info about a server (with notes, tags, attempts)."""
        guild = self.bot.get_guild(server_id)
        if guild is None:
            await ctx.send(f"⚠️ Not in `{server_id}`.")
            return

        whitelist = await self.config.whitelist()
        blacklist = await self.config.blacklist()
        join_attempts = await self.config.join_attempts()
        notes = await self.config.server_notes()
        tags = await self.config.server_tags()
        temp = await self.config.temp_whitelist()

        status_parts = []
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

        for name, value, inline in self._guild_detail_fields(guild):
            em.add_field(name=name, value=value, inline=inline)

        em.add_field(name="Status", value=" • ".join(status_parts), inline=False)

        # Tags
        gtags = tags.get(str(server_id), [])
        if gtags:
            em.add_field(name="🏷️ Tags", value=" ".join(f"`{t}`" for t in gtags), inline=False)

        # Note
        note = notes.get(str(server_id), "")
        if note:
            em.add_field(name="📝 Note", value=note, inline=False)

        # Temp whitelist
        temp_data = temp.get(str(server_id))
        if temp_data:
            em.add_field(
                name="⏰ Temp Whitelist",
                value=f"Expires: `{temp_data['expires'][:19]}`\nAdded by: `{temp_data.get('added_by', '?')}`",
                inline=False,
            )

        # Attempts
        att_data = join_attempts.get(str(server_id))
        if att_data:
            max_att = await self.config.max_attempts()
            em.add_field(
                name="Join Attempts",
                value=(
                    f"**{att_data['count']}** / {max_att}\n"
                    f"First: `{att_data.get('first_attempt', '?')[:19]}`\n"
                    f"Last: `{att_data.get('last_attempt', '?')[:19]}`"
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
        """Search servers by name."""
        q = query.lower()
        matches = sorted(
            [g for g in self.bot.guilds if q in g.name.lower()],
            key=lambda g: g.member_count or 0, reverse=True,
        )
        if not matches:
            await ctx.send(f"No servers matched `{query}`.")
            return
        pages, guild_pages = self._paginate_guilds(matches, title=f'🔍 "{query}" — {len(matches)} result(s)')
        view = ServerPageView(pages, guild_pages, cog=self, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    # ── leave ─────────────────────────────────────────────────

    @join_group.command(name="leave")
    @commands.is_owner()
    async def join_leave(self, ctx: commands.Context, server_id: int) -> None:
        """Leave a server by ID (doesn't un-whitelist)."""
        guild = self.bot.get_guild(server_id)
        if guild is None:
            await ctx.send(f"⚠️ Not in `{server_id}`.")
            return
        name = guild.name
        await guild.leave()
        await ctx.send(f"👋 Left **{name}** (`{server_id}`).")
        await self._log_event(title="👋 Left (Manual)", description=f"Left **{name}** by **{ctx.author}**.", colour=0xE67E22)

    # ── purge ─────────────────────────────────────────────────

    @join_group.command(name="purge")
    @commands.is_owner()
    async def join_purge(self, ctx: commands.Context) -> None:
        """Leave ALL non-whitelisted servers (with confirmation)."""
        whitelist = await self.config.whitelist()
        to_leave = [g for g in self.bot.guilds if g.id not in whitelist]
        if not to_leave:
            await ctx.send("✅ All servers are whitelisted.")
            return

        names = "\n".join(f"• **{g.name}** (`{g.id}`) — {g.member_count:,}" for g in to_leave[:20])
        extra = f"\n…and {len(to_leave) - 20} more" if len(to_leave) > 20 else ""
        em = discord.Embed(title="⚠️ Confirm Purge", description=f"Leave **{len(to_leave)}** server(s)?\n\n{names}{extra}", colour=0xE74C3C)

        view = ConfirmView(author_id=ctx.author.id)
        msg = await ctx.send(embed=em, view=view)
        await view.wait()

        if view.result:
            left = []
            for g in to_leave:
                try:
                    await g.leave()
                    left.append(g.name)
                except discord.HTTPException:
                    pass
            await msg.edit(embed=discord.Embed(title="🗑️ Purge Complete", description=f"Left **{len(left)}** server(s).", colour=0x2ECC71), view=None)
            await self._log_event(title="🗑️ Purge", description=f"**{ctx.author}** purged {len(left)} server(s).", colour=0xE74C3C)
        else:
            await msg.edit(embed=discord.Embed(title="Cancelled", colour=EMBED_COLOUR), view=None)

    # ── lock / unlock ─────────────────────────────────────────

    @join_group.command(name="lock")
    @commands.is_owner()
    async def join_lock(self, ctx: commands.Context) -> None:
        """Lock — reject ALL new joins."""
        if await self.config.locked():
            await ctx.send("🔒 Already locked.")
            return
        await self.config.locked.set(True)
        await ctx.send("🔒 **Locked** — no new joins accepted.")
        await self._log_event(title="🔒 Locked", description=f"Locked by **{ctx.author}**.", colour=0x95A5A6)

    @join_group.command(name="unlock")
    @commands.is_owner()
    async def join_unlock(self, ctx: commands.Context) -> None:
        """Unlock — resume whitelist rules."""
        if not await self.config.locked():
            await ctx.send("🔓 Already unlocked.")
            return
        await self.config.locked.set(False)
        await ctx.send("🔓 **Unlocked** — whitelist rules active.")
        await self._log_event(title="🔓 Unlocked", description=f"Unlocked by **{ctx.author}**.", colour=0x2ECC71)

    # ── log channel ───────────────────────────────────────────

    @join_group.command(name="log")
    @commands.is_owner()
    async def join_log(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """Set event log channel. No argument = disable."""
        if channel is None:
            await self.config.log_channel.set(None)
            await ctx.send("📝 Logging **disabled**.")
            return
        await self.config.log_channel.set(channel.id)
        await ctx.send(f"📝 Logging to {channel.mention}.")

    # ── stats ─────────────────────────────────────────────────

    @join_group.command(name="stats")
    @commands.is_owner()
    async def join_stats(self, ctx: commands.Context) -> None:
        """High-level server overview."""
        whitelist = await self.config.whitelist()
        blacklist = await self.config.blacklist()
        locked = await self.config.locked()
        log_channel = await self.config.log_channel()
        max_attempts = await self.config.max_attempts()
        join_attempts = await self.config.join_attempts()
        trusted = await self.config.trusted_inviters()
        temp = await self.config.temp_whitelist()
        alerts = await self.config.owner_alerts()
        min_mem = await self.config.min_members()
        max_mem = await self.config.max_members()
        requests = await self.config.whitelist_requests()

        total = len(self.bot.guilds)
        members = sum(g.member_count or 0 for g in self.bot.guilds)
        largest = max(self.bot.guilds, key=lambda g: g.member_count or 0) if self.bot.guilds else None
        att_servers = len(join_attempts)
        att_total = sum(e.get("count", 0) for e in join_attempts.values())
        auto_banned = sum(1 for e in join_attempts.values() if e.get("count", 0) >= max_attempts)
        log_ch = self.bot.get_channel(log_channel) if log_channel else None

        em = discord.Embed(title="📊 Server Stats", colour=EMBED_COLOUR)
        em.add_field(name="Servers", value=f"{total:,}", inline=True)
        em.add_field(name="Total Members", value=f"{members:,}", inline=True)
        em.add_field(name="Whitelisted", value=str(len(whitelist)), inline=True)
        em.add_field(name="Blacklisted", value=str(len(blacklist)), inline=True)
        em.add_field(name="Temp Whitelisted", value=str(len(temp)), inline=True)
        em.add_field(name="Pending Requests", value=str(len(requests)), inline=True)
        em.add_field(name="Lock", value="🔒 Locked" if locked else "🔓 Open", inline=True)
        em.add_field(name="Alerts", value="🔔 On" if alerts else "🔕 Off", inline=True)
        em.add_field(name="Trusted Inviters", value=str(len(trusted)), inline=True)
        if largest:
            em.add_field(name="Largest", value=f"**{largest.name}** ({largest.member_count:,})", inline=False)
        em.add_field(name="Log Channel", value=log_ch.mention if log_ch else "Disabled", inline=True)
        em.add_field(name="Max Attempts", value=str(max_attempts), inline=True)
        em.add_field(name="Member Limits", value=f"Min: {min_mem or '—'} · Max: {max_mem or '—'}", inline=True)
        em.add_field(name="Attempt Tracking", value=f"**{att_servers}** tracked · **{att_total}** attempts · **{auto_banned}** auto-banned", inline=False)
        await ctx.send(embed=em)

    # ── settings ──────────────────────────────────────────────

    @join_group.command(name="settings", aliases=["config"])
    @commands.is_owner()
    async def join_settings(self, ctx: commands.Context) -> None:
        """Display full configuration."""
        whitelist = await self.config.whitelist()
        blacklist = await self.config.blacklist()
        locked = await self.config.locked()
        log_channel = await self.config.log_channel()
        max_attempts = await self.config.max_attempts()
        leave_message = await self.config.leave_message()
        join_attempts = await self.config.join_attempts()
        trusted = await self.config.trusted_inviters()
        alerts = await self.config.owner_alerts()
        min_mem = await self.config.min_members()
        max_mem = await self.config.max_members()
        temp = await self.config.temp_whitelist()
        requests = await self.config.whitelist_requests()

        log_ch = self.bot.get_channel(log_channel) if log_channel else None
        msg_text = leave_message or DEFAULT_LEAVE_MESSAGE
        msg_preview = msg_text[:120] + "…" if len(msg_text) > 120 else msg_text

        em = discord.Embed(title=f"⚙️ ServerWhitelist v{VERSION} Settings", colour=EMBED_COLOUR)
        em.add_field(name="Whitelisted", value=str(len(whitelist)), inline=True)
        em.add_field(name="Blacklisted", value=str(len(blacklist)), inline=True)
        em.add_field(name="Current Servers", value=str(len(self.bot.guilds)), inline=True)
        em.add_field(name="Lock", value="🔒 ON" if locked else "🔓 OFF", inline=True)
        em.add_field(name="Log Channel", value=log_ch.mention if log_ch else "Not set", inline=True)
        em.add_field(name="Max Attempts", value=str(max_attempts), inline=True)
        em.add_field(name="Member Limits", value=f"Min: {min_mem or 'None'} · Max: {max_mem or 'None'}", inline=False)
        em.add_field(name="Trusted Inviters", value=str(len(trusted)), inline=True)
        em.add_field(name="Owner Alerts", value="🔔 On" if alerts else "🔕 Off", inline=True)
        em.add_field(name="Temp Whitelisted", value=str(len(temp)), inline=True)
        em.add_field(name="Pending Requests", value=str(len(requests)), inline=True)
        em.add_field(name="Tracked Attempts", value=str(len(join_attempts)), inline=True)
        em.add_field(name="Leave DM", value=f"```{msg_preview}```", inline=False)
        em.add_field(
            name="Commands",
            value=(
                f"`{ctx.clean_prefix}join <id>` — whitelist\n"
                f"`{ctx.clean_prefix}join remove/blacklist/unblacklist <id>`\n"
                f"`{ctx.clean_prefix}join temp <id> <duration>` — temp whitelist\n"
                f"`{ctx.clean_prefix}join servers/info/search/stats`\n"
                f"`{ctx.clean_prefix}join purge/leave/lock/unlock`\n"
                f"`{ctx.clean_prefix}join trust/untrust/trusted`\n"
                f"`{ctx.clean_prefix}join note/tag/untag/tags`\n"
                f"`{ctx.clean_prefix}join attempts/maxattempts/requests`\n"
                f"`{ctx.clean_prefix}join alerts/minmembers/maxmembers`\n"
                f"`{ctx.clean_prefix}join setmessage/resetmessage`\n"
                f"`{ctx.clean_prefix}join backup/restore/export`"
            ),
            inline=False,
        )
        await ctx.send(embed=em)

    # ── export ────────────────────────────────────────────────

    @join_group.command(name="export")
    @commands.is_owner()
    async def join_export(self, ctx: commands.Context) -> None:
        """Export server list as .txt."""
        whitelist = await self.config.whitelist()
        blacklist = await self.config.blacklist()
        join_attempts = await self.config.join_attempts()
        notes = await self.config.server_notes()
        tags = await self.config.server_tags()
        temp = await self.config.temp_whitelist()

        lines = [
            f"{'ID':<22} {'Members':>8}  {'Status':<14} {'Att':>4}  {'Tags':<20} {'Joined':<26} {'Owner':<30} Name",
            "─" * 160,
        ]
        for g in sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True):
            sp = []
            if g.id in whitelist: sp.append("WL")
            if g.id in blacklist: sp.append("BL")
            if str(g.id) in temp: sp.append("TEMP")
            status = ",".join(sp) or "—"
            joined = g.me.joined_at.strftime("%Y-%m-%d %H:%M UTC") if g.me and g.me.joined_at else "?"
            owner = str(g.owner) if g.owner else "?"
            att = join_attempts.get(str(g.id), {}).get("count", 0)
            gtags = ",".join(tags.get(str(g.id), [])) or "—"
            lines.append(f"{g.id:<22} {g.member_count or 0:>8,}  {status:<14} {att:>4}  {gtags:<20} {joined:<26} {owner:<30} {g.name}")
            note = notes.get(str(g.id), "")
            if note:
                lines.append(f"{'':>22} 📝 {note[:100]}")

        # Non-joined tracked servers
        tracked = set(int(k) for k in join_attempts.keys())
        current = set(g.id for g in self.bot.guilds)
        non_joined = tracked - current
        if non_joined:
            lines += ["", "── Tracked (Not Joined) ──", f"{'ID':<22} {'Att':>4}  {'Last Attempt':<26} {'Owner ID':<22} Name", "─" * 100]
            for gid in sorted(non_joined):
                e = join_attempts[str(gid)]
                lines.append(f"{gid:<22} {e.get('count',0):>4}  {e.get('last_attempt','?'):<26} {str(e.get('owner_id','?')):<22} {e.get('name','?')}")

        buf = io.BytesIO("\n".join(lines).encode())
        await ctx.send("📄 Server export:", file=discord.File(buf, filename="server_export.txt"))

    # ═══════════════════════════════════════════════════════════
    #  Attempt Tracking
    # ═══════════════════════════════════════════════════════════

    @join_group.group(name="attempts", aliases=["att"], invoke_without_command=True)
    @commands.is_owner()
    async def join_attempts_group(self, ctx: commands.Context) -> None:
        """View join attempt tracker."""
        join_attempts = await self.config.join_attempts()
        max_attempts = await self.config.max_attempts()
        blacklist = await self.config.blacklist()

        if not join_attempts:
            await ctx.send("📊 No attempts recorded.")
            return

        sorted_entries = sorted(join_attempts.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)
        pages = []
        for i in range(0, len(sorted_entries), PER_PAGE):
            chunk = sorted_entries[i:i + PER_PAGE]
            em = discord.Embed(title="📊 Join Attempt Tracker", colour=EMBED_COLOUR)
            for gid_str, entry in chunk:
                gid = int(gid_str)
                count = entry.get("count", 0)
                is_banned = gid in blacklist
                status = "🚫 BANNED" if is_banned else (f"⚠️ {count}/{max_attempts}" if count >= max_attempts - 2 else f"📋 {count}/{max_attempts}")
                em.add_field(
                    name=f"{entry.get('name', '?')}  (`{gid}`)",
                    value=f"**Status:** {status}\n**Attempts:** {count}\n**Owner:** `{entry.get('owner_id', '?')}`\n**First:** `{str(entry.get('first_attempt','?'))[:19]}`\n**Last:** `{str(entry.get('last_attempt','?'))[:19]}`",
                    inline=False,
                )
            em.set_footer(text=f"Total: {len(sorted_entries)} • Max: {max_attempts}")
            pages.append(em)

        view = PaginatedView(pages, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    @join_attempts_group.command(name="reset")
    @commands.is_owner()
    async def join_attempts_reset(self, ctx: commands.Context, server_id: int) -> None:
        """Reset attempts for one server."""
        async with self.config.join_attempts() as att:
            if str(server_id) not in att:
                await ctx.send(f"⚠️ No attempts for `{server_id}`.")
                return
            old = att.pop(str(server_id))
        await ctx.send(f"✅ Reset `{server_id}` (was **{old.get('count', 0)}**).")

    @join_attempts_group.command(name="resetall")
    @commands.is_owner()
    async def join_attempts_resetall(self, ctx: commands.Context) -> None:
        """Reset ALL attempt counters."""
        att = await self.config.join_attempts()
        count = len(att)
        await self.config.join_attempts.set({})
        await ctx.send(f"✅ Cleared **{count}** server(s).")

    @join_group.command(name="maxattempts", aliases=["setmax", "limit"])
    @commands.is_owner()
    async def join_maxattempts(self, ctx: commands.Context, count: int) -> None:
        """Set max attempts before auto-ban (min 1)."""
        if count < 1:
            await ctx.send("⚠️ Must be ≥ 1.")
            return
        old = await self.config.max_attempts()
        await self.config.max_attempts.set(count)
        await ctx.send(f"✅ Max attempts: **{old}** → **{count}**.")

    # ═══════════════════════════════════════════════════════════
    #  Custom Leave DM
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="setmessage", aliases=["setmsg"])
    @commands.is_owner()
    async def join_setmessage(self, ctx: commands.Context, *, text: str) -> None:
        """Set custom leave DM text."""
        if len(text) > 1500:
            await ctx.send("⚠️ Max 1,500 chars.")
            return
        await self.config.leave_message.set(text)
        await ctx.send(f"✅ Updated!\n\n>>> {text[:500]}")

    @join_group.command(name="resetmessage", aliases=["resetmsg"])
    @commands.is_owner()
    async def join_resetmessage(self, ctx: commands.Context) -> None:
        """Reset leave DM to default."""
        await self.config.leave_message.set(None)
        await ctx.send(f"✅ Reset to default:\n\n>>> {DEFAULT_LEAVE_MESSAGE}")

    # ═══════════════════════════════════════════════════════════
    #  Whitelist Requests (NEW v4)
    # ═══════════════════════════════════════════════════════════

    @join_group.group(name="requests", aliases=["req"], invoke_without_command=True)
    @commands.is_owner()
    async def join_requests(self, ctx: commands.Context) -> None:
        """View pending whitelist requests."""
        requests = await self.config.whitelist_requests()
        if not requests:
            await ctx.send("📭 No pending requests.")
            return

        pages = []
        items = sorted(requests.items(), key=lambda kv: kv[1].get("requested_at", ""))
        for i in range(0, len(items), PER_PAGE):
            chunk = items[i:i + PER_PAGE]
            em = discord.Embed(title="📩 Pending Whitelist Requests", colour=0x3498DB)
            for gid_str, data in chunk:
                em.add_field(
                    name=f"{data.get('name', '?')}  (`{gid_str}`)",
                    value=(
                        f"**Requester:** {data.get('requester_name', '?')} (`{data.get('requester_id', '?')}`)\n"
                        f"**Requested:** `{str(data.get('requested_at', '?'))[:19]}`"
                    ),
                    inline=False,
                )
            em.set_footer(text=f"Use [p]join requests approve/deny <id> | Total: {len(items)}")
            pages.append(em)

        view = PaginatedView(pages, author_id=ctx.author.id)
        await ctx.send(embed=pages[0], view=view)

    @join_requests.command(name="approve")
    @commands.is_owner()
    async def join_requests_approve(self, ctx: commands.Context, server_id: int) -> None:
        """Approve a whitelist request."""
        gid_str = str(server_id)
        request_data = None
        async with self.config.whitelist_requests() as reqs:
            request_data = reqs.pop(gid_str, None)
        if not request_data:
            await ctx.send(f"⚠️ No pending request for `{server_id}`.")
            return
        async with self.config.whitelist() as wl:
            if server_id not in wl:
                wl.append(server_id)
        async with self.config.join_attempts() as att:
            att.pop(gid_str, None)
        # Notify requester
        try:
            user = await self.bot.fetch_user(request_data["requester_id"])
            em = discord.Embed(title="✅ Request Approved!", description=f"**{request_data['name']}** (`{server_id}`) is now whitelisted!", colour=0x2ECC71)
            await user.send(embed=em)
        except (discord.HTTPException, discord.NotFound):
            pass
        await ctx.send(f"✅ `{server_id}` approved and whitelisted!")
        await self._log_event(title="✅ Request Approved", description=f"`{server_id}` approved by **{ctx.author}**.", colour=0x2ECC71)

    @join_requests.command(name="deny")
    @commands.is_owner()
    async def join_requests_deny(self, ctx: commands.Context, server_id: int) -> None:
        """Deny a whitelist request."""
        gid_str = str(server_id)
        request_data = None
        async with self.config.whitelist_requests() as reqs:
            request_data = reqs.pop(gid_str, None)
        if not request_data:
            await ctx.send(f"⚠️ No pending request for `{server_id}`.")
            return
        try:
            user = await self.bot.fetch_user(request_data["requester_id"])
            em = discord.Embed(title="❌ Request Denied", description=f"**{request_data['name']}** (`{server_id}`) was denied.", colour=0xE74C3C)
            await user.send(embed=em)
        except (discord.HTTPException, discord.NotFound):
            pass
        await ctx.send(f"❌ `{server_id}` denied.")
        await self._log_event(title="❌ Request Denied", description=f"`{server_id}` denied by **{ctx.author}**.", colour=0xE74C3C)

    # ═══════════════════════════════════════════════════════════
    #  Server Notes & Tags (NEW v4)
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="note")
    @commands.is_owner()
    async def join_note(self, ctx: commands.Context, server_id: int, *, text: Optional[str] = None) -> None:
        """Set or view a note for a server. No text = view."""
        gid_str = str(server_id)
        if text is None:
            notes = await self.config.server_notes()
            note = notes.get(gid_str, "")
            if note:
                await ctx.send(f"📝 **Note for `{server_id}`:**\n{note}")
            else:
                await ctx.send(f"No note for `{server_id}`. Use `{ctx.clean_prefix}join note {server_id} <text>` to add one.")
            return
        if text.lower() == "clear":
            async with self.config.server_notes() as notes:
                notes.pop(gid_str, None)
            await ctx.send(f"✅ Note cleared for `{server_id}`.")
            return
        async with self.config.server_notes() as notes:
            notes[gid_str] = text[:500]
        await ctx.send(f"✅ Note saved for `{server_id}`:\n📝 {text[:500]}")

    @join_group.command(name="tag")
    @commands.is_owner()
    async def join_tag(self, ctx: commands.Context, server_id: int, *, tag: str) -> None:
        """Add a tag to a server (e.g. partner, testing, personal)."""
        tag = tag.lower().strip().replace(" ", "-")[:30]
        gid_str = str(server_id)
        async with self.config.server_tags() as tags:
            gtags = tags.get(gid_str, [])
            if tag in gtags:
                await ctx.send(f"⚠️ `{server_id}` already has tag `{tag}`.")
                return
            gtags.append(tag)
            tags[gid_str] = gtags
        await ctx.send(f"🏷️ Tag `{tag}` added to `{server_id}`.")

    @join_group.command(name="untag")
    @commands.is_owner()
    async def join_untag(self, ctx: commands.Context, server_id: int, *, tag: str) -> None:
        """Remove a tag from a server."""
        tag = tag.lower().strip().replace(" ", "-")[:30]
        gid_str = str(server_id)
        async with self.config.server_tags() as tags:
            gtags = tags.get(gid_str, [])
            if tag not in gtags:
                await ctx.send(f"⚠️ `{server_id}` doesn't have tag `{tag}`.")
                return
            gtags.remove(tag)
            tags[gid_str] = gtags
        await ctx.send(f"🏷️ Tag `{tag}` removed from `{server_id}`.")

    @join_group.command(name="tags")
    @commands.is_owner()
    async def join_tags(self, ctx: commands.Context) -> None:
        """View all tags and which servers have them."""
        all_tags = await self.config.server_tags()
        if not all_tags:
            await ctx.send("No tags set.")
            return

        # Group by tag
        tag_map: dict[str, list[str]] = {}
        for gid_str, gtags in all_tags.items():
            for t in gtags:
                tag_map.setdefault(t, []).append(gid_str)

        em = discord.Embed(title="🏷️ Server Tags", colour=EMBED_COLOUR)
        for tag, gids in sorted(tag_map.items()):
            names = []
            for gid_str in gids:
                guild = self.bot.get_guild(int(gid_str))
                name = guild.name if guild else gid_str
                names.append(f"**{name}** (`{gid_str}`)")
            em.add_field(name=f"`{tag}` ({len(gids)})", value="\n".join(names[:10]), inline=False)
        await ctx.send(embed=em)

    # ═══════════════════════════════════════════════════════════
    #  Temporary Whitelist (NEW v4)
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="temp")
    @commands.is_owner()
    async def join_temp(self, ctx: commands.Context, server_id: int, *, duration: str) -> None:
        """Temporarily whitelist a server.

        Duration examples: ``7d``, ``12h``, ``2d 6h 30m``
        """
        delta = parse_duration(duration)
        if delta is None:
            await ctx.send("⚠️ Invalid duration. Examples: `7d`, `12h`, `2d 6h 30m`.")
            return

        blacklist = await self.config.blacklist()
        if server_id in blacklist:
            await ctx.send(f"⚠️ `{server_id}` is blacklisted. Unblacklist first.")
            return

        expires = datetime.now(timezone.utc) + delta
        gid_str = str(server_id)

        async with self.config.whitelist() as wl:
            if server_id not in wl:
                wl.append(server_id)

        async with self.config.temp_whitelist() as tw:
            tw[gid_str] = {
                "expires": expires.isoformat(),
                "added_by": str(ctx.author),
                "name": "",
            }

        # Reset attempts
        async with self.config.join_attempts() as att:
            att.pop(gid_str, None)

        await ctx.send(
            f"⏰ `{server_id}` temporarily whitelisted until "
            f"**{discord.utils.format_dt(expires, style='F')}** ({discord.utils.format_dt(expires, style='R')})."
        )
        await self._log_event(
            title="⏰ Temp Whitelisted",
            description=f"`{server_id}` temp-whitelisted by **{ctx.author}** until {expires.isoformat()[:19]}.",
            colour=0x3498DB,
        )

    # ═══════════════════════════════════════════════════════════
    #  Server Requirements (NEW v4)
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="minmembers")
    @commands.is_owner()
    async def join_minmembers(self, ctx: commands.Context, count: int) -> None:
        """Set minimum member count to join (0 = no minimum)."""
        if count < 0:
            await ctx.send("⚠️ Must be ≥ 0.")
            return
        await self.config.min_members.set(count)
        await ctx.send(f"✅ Min members: **{count}** {'(disabled)' if count == 0 else ''}.")

    @join_group.command(name="maxmembers")
    @commands.is_owner()
    async def join_maxmembers(self, ctx: commands.Context, count: int) -> None:
        """Set maximum member count to join (0 = no maximum)."""
        if count < 0:
            await ctx.send("⚠️ Must be ≥ 0.")
            return
        await self.config.max_members.set(count)
        await ctx.send(f"✅ Max members: **{count}** {'(disabled)' if count == 0 else ''}.")

    # ═══════════════════════════════════════════════════════════
    #  Trusted Inviters (NEW v4)
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="trust")
    @commands.is_owner()
    async def join_trust(self, ctx: commands.Context, user_id: int) -> None:
        """Trust a user — any server they add the bot to is auto-whitelisted."""
        async with self.config.trusted_inviters() as ti:
            if user_id in ti:
                await ctx.send(f"⚠️ `{user_id}` is already trusted.")
                return
            ti.append(user_id)
        try:
            user = await self.bot.fetch_user(user_id)
            name = str(user)
        except (discord.HTTPException, discord.NotFound):
            name = str(user_id)
        await ctx.send(f"🔑 **{name}** (`{user_id}`) is now a trusted inviter.")
        await self._log_event(title="🔑 Trusted Inviter Added", description=f"**{name}** added by **{ctx.author}**.", colour=0x2ECC71)

    @join_group.command(name="untrust")
    @commands.is_owner()
    async def join_untrust(self, ctx: commands.Context, user_id: int) -> None:
        """Remove a trusted inviter."""
        async with self.config.trusted_inviters() as ti:
            if user_id not in ti:
                await ctx.send(f"⚠️ `{user_id}` is not trusted.")
                return
            ti.remove(user_id)
        await ctx.send(f"✅ `{user_id}` removed from trusted inviters.")

    @join_group.command(name="trusted")
    @commands.is_owner()
    async def join_trusted(self, ctx: commands.Context) -> None:
        """View all trusted inviters."""
        trusted = await self.config.trusted_inviters()
        if not trusted:
            await ctx.send("No trusted inviters.")
            return
        lines = []
        for uid in trusted:
            try:
                user = await self.bot.fetch_user(uid)
                lines.append(f"🔑 **{user}** (`{uid}`)")
            except (discord.HTTPException, discord.NotFound):
                lines.append(f"🔑 `{uid}` (unknown user)")
        em = discord.Embed(title="🔑 Trusted Inviters", description="\n".join(lines), colour=EMBED_COLOUR)
        await ctx.send(embed=em)

    # ═══════════════════════════════════════════════════════════
    #  Owner Alerts (NEW v4)
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="alerts")
    @commands.is_owner()
    async def join_alerts(self, ctx: commands.Context, state: str) -> None:
        """Toggle owner DM alerts. Usage: ``[p]join alerts on`` or ``off``."""
        if state.lower() in ("on", "true", "yes", "enable", "1"):
            await self.config.owner_alerts.set(True)
            await ctx.send("🔔 Owner alerts **enabled** — you'll get DMs for join/leave/block events.")
        elif state.lower() in ("off", "false", "no", "disable", "0"):
            await self.config.owner_alerts.set(False)
            await ctx.send("🔕 Owner alerts **disabled**.")
        else:
            await ctx.send("Usage: `[p]join alerts on` or `[p]join alerts off`.")

    # ═══════════════════════════════════════════════════════════
    #  Backup & Restore (NEW v4)
    # ═══════════════════════════════════════════════════════════

    @join_group.command(name="backup")
    @commands.is_owner()
    async def join_backup(self, ctx: commands.Context) -> None:
        """Export the full ServerWhitelist config as a JSON file."""
        data = {
            "version": VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "whitelist": await self.config.whitelist(),
            "blacklist": await self.config.blacklist(),
            "locked": await self.config.locked(),
            "log_channel": await self.config.log_channel(),
            "max_attempts": await self.config.max_attempts(),
            "leave_message": await self.config.leave_message(),
            "join_attempts": await self.config.join_attempts(),
            "min_members": await self.config.min_members(),
            "max_members": await self.config.max_members(),
            "trusted_inviters": await self.config.trusted_inviters(),
            "owner_alerts": await self.config.owner_alerts(),
            "temp_whitelist": await self.config.temp_whitelist(),
            "server_notes": await self.config.server_notes(),
            "server_tags": await self.config.server_tags(),
            "whitelist_requests": await self.config.whitelist_requests(),
        }
        buf = io.BytesIO(json.dumps(data, indent=2).encode())
        await ctx.send(
            "💾 Here's your full config backup:",
            file=discord.File(buf, filename=f"serverwhitelist_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"),
        )

    @join_group.command(name="restore")
    @commands.is_owner()
    async def join_restore(self, ctx: commands.Context) -> None:
        """Restore config from an attached JSON file."""
        if not ctx.message.attachments:
            await ctx.send("⚠️ Attach a `.json` backup file to the message.")
            return

        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith(".json"):
            await ctx.send("⚠️ File must be `.json`.")
            return

        try:
            raw = await attachment.read()
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            await ctx.send("⚠️ Invalid JSON file.")
            return

        # Confirm
        keys_found = [k for k in data.keys() if k not in ("version", "exported_at")]
        em = discord.Embed(
            title="⚠️ Confirm Restore",
            description=(
                f"This will **overwrite** your current config with the backup.\n\n"
                f"**Backup version:** {data.get('version', '?')}\n"
                f"**Exported:** {data.get('exported_at', '?')}\n"
                f"**Keys:** {', '.join(keys_found)}"
            ),
            colour=0xE74C3C,
        )
        view = ConfirmView(author_id=ctx.author.id)
        msg = await ctx.send(embed=em, view=view)
        await view.wait()

        if not view.result:
            await msg.edit(embed=discord.Embed(title="Cancelled", colour=EMBED_COLOUR), view=None)
            return

        # Apply
        field_map = {
            "whitelist": self.config.whitelist,
            "blacklist": self.config.blacklist,
            "locked": self.config.locked,
            "log_channel": self.config.log_channel,
            "max_attempts": self.config.max_attempts,
            "leave_message": self.config.leave_message,
            "join_attempts": self.config.join_attempts,
            "min_members": self.config.min_members,
            "max_members": self.config.max_members,
            "trusted_inviters": self.config.trusted_inviters,
            "owner_alerts": self.config.owner_alerts,
            "temp_whitelist": self.config.temp_whitelist,
            "server_notes": self.config.server_notes,
            "server_tags": self.config.server_tags,
            "whitelist_requests": self.config.whitelist_requests,
        }
        restored = 0
        for key, setter in field_map.items():
            if key in data:
                await setter.set(data[key])
                restored += 1

        await msg.edit(
            embed=discord.Embed(
                title="✅ Restore Complete",
                description=f"Restored **{restored}** config key(s) from backup.",
                colour=0x2ECC71,
            ),
            view=None,
        )
        await self._log_event(title="💾 Config Restored", description=f"Config restored by **{ctx.author}** ({restored} keys).", colour=0x3498DB)
