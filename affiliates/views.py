"""
Interactive components for the Affiliates cog: the "add" modal (and the
button that opens it, since modals can only be opened in response to a
component interaction, never a bare prefix command), and the
select-then-confirm flow used to remove an entry.
"""

from __future__ import annotations

from typing import List

import discord
from discord import ui

COLOUR_OK = discord.Colour.green()
COLOUR_INFO = discord.Colour.blurple()
COLOUR_ERR = discord.Colour.red()


def ok_embed(text: str) -> discord.Embed:
    return discord.Embed(description=text, colour=COLOUR_OK)


def info_embed(text: str) -> discord.Embed:
    return discord.Embed(description=text, colour=COLOUR_INFO)


def err_embed(text: str) -> discord.Embed:
    return discord.Embed(description=text, colour=COLOUR_ERR)


class AffiliateModal(ui.Modal):
    # Capped tightly (not just for tidiness): the board renders 10 entries per
    # plain-text message, and Discord caps message content at 2000 characters.
    # These max_lengths keep a worst-case 10-entry page under that cap with
    # margin to spare — see the render_pages()/`_sync_aff_message` docstring.
    server_name = ui.TextInput(
        label="Server Name",
        placeholder="e.g. Ruby's Hangout",
        max_length=60,
        style=discord.TextStyle.short,
    )
    server_invite = ui.TextInput(
        label="Server Invite",
        placeholder="e.g. https://discord.gg/abc123",
        max_length=100,
        style=discord.TextStyle.short,
    )

    def __init__(self, cog, guild_id: int, list_kind: str):
        super().__init__(title="➕ Add Affiliate" if list_kind == "aff" else "➕ Add DM Affiliate")
        self.cog = cog
        self.guild_id = guild_id
        self.list_kind = list_kind  # "aff" or "dm"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = str(self.server_name).strip()
        invite = str(self.server_invite).strip()
        if not name or not invite:
            return await interaction.response.send_message(
                embed=err_embed("Both fields are required."), ephemeral=True
            )

        position = await self.cog.add_entry(self.guild_id, self.list_kind, name, invite, interaction.user.id)
        if position is None:
            return await interaction.response.send_message(
                embed=err_embed("That list is full — it already holds the maximum of 100 entries."),
                ephemeral=True,
            )

        label = "Affiliate" if self.list_kind == "aff" else "DM Affiliate"
        await interaction.response.send_message(
            embed=ok_embed(f"✅ **{name}** added as {label} **#{position}**."), ephemeral=True
        )


class AddAffiliateButtonView(ui.View):
    """Sent in response to `aff add`/`aff dm add` — clicking it is the component
    interaction needed to actually open the modal."""

    def __init__(self, cog, guild_id: int, list_kind: str, author_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.list_kind = list_kind
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Not your prompt — run the command yourself.", ephemeral=True
            )
            return False
        return True

    @ui.button(label="Add Affiliate", style=discord.ButtonStyle.success, emoji="➕")
    async def add_btn(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await interaction.response.send_modal(AffiliateModal(self.cog, self.guild_id, self.list_kind))


class RemoveConfirmView(ui.View):
    def __init__(self, cog, guild_id: int, list_kind: str, author_id: int, entry_id: int, entry_name: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.list_kind = list_kind
        self.author_id = author_id
        self.entry_id = entry_id
        self.entry_name = entry_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your confirmation.", ephemeral=True)
            return False
        return True

    @ui.button(label="Remove", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button) -> None:
        removed = await self.cog.remove_entry(self.guild_id, self.list_kind, self.entry_id)
        if removed:
            await interaction.response.edit_message(
                embed=ok_embed(f"✅ Removed **{self.entry_name}**."), view=None
            )
        else:
            await interaction.response.edit_message(
                embed=err_embed("That entry was already removed."), view=None
            )
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button) -> None:
        await interaction.response.edit_message(embed=info_embed("Cancelled — nothing was removed."), view=None)
        self.stop()


class RemoveSelectView(ui.View):
    """Sent in response to `aff remove`/`aff dm remove` — populates a Select
    from the current entries; picking one swaps this message to a confirm step."""

    def __init__(
        self, cog, guild_id: int, list_kind: str, author_id: int, entries: List[dict], page: int = 1
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id
        self.list_kind = list_kind
        self.author_id = author_id

        # Discord select menus cap at 25 options, but the list can hold up to
        # 100 — slice per page while keeping each label's true global position
        # (not just its position within this page).
        start = (page - 1) * 25
        page_entries = entries[start:start + 25]
        options = [
            discord.SelectOption(label=f"#{start + i + 1} — {e['name'][:80]}", value=str(e["id"]))
            for i, e in enumerate(page_entries)
        ]
        placeholder = "Choose an entry to remove..."
        total_pages = (len(entries) + 24) // 25
        if total_pages > 1:
            placeholder = f"Choose an entry to remove... (page {page}/{total_pages})"
        self.select = ui.Select(placeholder=placeholder, options=options)
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Not your prompt — run the command yourself.", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        entry_id = int(self.select.values[0])
        entry = await self.cog.get_entry(self.guild_id, self.list_kind, entry_id)
        if entry is None:
            await interaction.response.edit_message(
                embed=err_embed("That entry no longer exists — it may have already been removed."),
                view=None,
            )
            return

        confirm_view = RemoveConfirmView(
            self.cog, self.guild_id, self.list_kind, self.author_id, entry_id, entry["name"]
        )
        await interaction.response.edit_message(
            embed=info_embed(f"Remove **{entry['name']}**? This can't be undone."),
            view=confirm_view,
        )

