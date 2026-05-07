"""NexusCore — shared utilities, embed builders, paginators, config helpers."""

from __future__ import annotations

import asyncio
import datetime
import math
import random
import string
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Union

import discord
from redbot.core import commands


# ── Colour palette ─────────────────────────────────────────────────────────
class Clr:
    TICKET = discord.Colour(0x5865F2)   # blurple
    APP = discord.Colour(0x57F287)      # green
    SUGGEST = discord.Colour(0xFEE75C)  # yellow
    ROLES = discord.Colour(0xEB459E)    # fuchsia
    GIVE = discord.Colour(0xED4245)     # red
    LOG = discord.Colour(0x99AAB5)      # grey
    MOD = discord.Colour(0xE67E22)      # orange
    ECO = discord.Colour(0xF1C40F)      # gold
    SUCCESS = discord.Colour(0x2ECC71)
    ERROR = discord.Colour(0xE74C3C)
    INFO = discord.Colour(0x3498DB)


# ── Quick embeds ───────────────────────────────────────────────────────────
def ok_embed(desc: str, *, title: str | None = None) -> discord.Embed:
    e = discord.Embed(description=f"✅ {desc}", colour=Clr.SUCCESS)
    if title:
        e.title = title
    return e


def err_embed(desc: str, *, title: str | None = None) -> discord.Embed:
    e = discord.Embed(description=f"❌ {desc}", colour=Clr.ERROR)
    if title:
        e.title = title
    return e


def info_embed(desc: str, *, title: str | None = None, colour: discord.Colour | None = None) -> discord.Embed:
    e = discord.Embed(description=desc, colour=colour or Clr.INFO)
    if title:
        e.title = title
    return e


# ── ID generator ───────────────────────────────────────────────────────────
def short_id(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


# ── Timestamp helpers ──────────────────────────────────────────────────────
def ts_now() -> int:
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


def ts_relative(ts: int, style: str = "R") -> str:
    return f"<t:{ts}:{style}>"


def ts_full(ts: int) -> str:
    return f"<t:{ts}:F>"


def duration_str(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"{d}d {h}h"


# ── Time parser — "1d2h30m" → seconds ─────────────────────────────────────
def parse_duration(text: str) -> int | None:
    import re
    total = 0
    matches = re.findall(r"(\d+)\s*([smhdw])", text.lower())
    if not matches:
        return None
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    for val, unit in matches:
        total += int(val) * multipliers[unit]
    return total if total > 0 else None


# ── Paginator view ─────────────────────────────────────────────────────────
class Paginator(discord.ui.View):
    """A generic embed paginator with first/prev/next/last + page counter."""

    def __init__(
        self,
        pages: list[discord.Embed],
        *,
        author_id: int | None = None,
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current = 0
        self.author_id = author_id
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self):
        self.first_btn.disabled = self.current == 0
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        self.last_btn.disabled = self.current >= len(self.pages) - 1
        self.page_btn.label = f"{self.current + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return False
        return True

    async def _update(self, interaction: discord.Interaction):
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(emoji="⏮", style=discord.ButtonStyle.secondary)
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = 0
        await self._update(interaction)

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.primary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        await self._update(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        await self._update(interaction)

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary)
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = len(self.pages) - 1
        await self._update(interaction)

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def send(self, dest, **kwargs):
        self.message = await dest.send(embed=self.pages[0], view=self, **kwargs)
        return self.message


# ── Confirmation view ──────────────────────────────────────────────────────
class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your confirmation.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.edit_message(view=None)


# ── Chunk helper ───────────────────────────────────────────────────────────
def chunk_list(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


# ── Permission helper ─────────────────────────────────────────────────────
def has_perms(member: discord.Member, channel: discord.abc.GuildChannel, *perms: str) -> bool:
    p = channel.permissions_for(member)
    return all(getattr(p, perm, False) for perm in perms)


# ── Safe send ──────────────────────────────────────────────────────────────
async def safe_send(dest, content=None, **kwargs) -> discord.Message | None:
    try:
        return await dest.send(content, **kwargs)
    except (discord.HTTPException, discord.Forbidden):
        return None


async def safe_dm(user: discord.User, content=None, **kwargs) -> discord.Message | None:
    try:
        return await user.send(content, **kwargs)
    except (discord.HTTPException, discord.Forbidden):
        return None
