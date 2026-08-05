"""Persistent and ephemeral views for Wormhole messages."""

from __future__ import annotations

import discord
from typing import Optional


def reply_jump_view(url: str) -> discord.ui.View:
    """Create a View with a single URL button pointing to the replied message."""
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link,
        label="Jump to replied message",
        url=url,
    ))
    return view


class _ResolveButton(discord.ui.Button):
    def __init__(self, cog, net_name: str, report_id: int):
        super().__init__(style=discord.ButtonStyle.primary, label="Resolve")
        self.cog = cog
        self.net_name = net_name
        self.report_id = report_id

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        await self.cog._report_resolve_via_interaction(interaction, self.net_name, self.report_id)


class _DismissButton(discord.ui.Button):
    def __init__(self, cog, net_name: str, report_id: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="Dismiss")
        self.cog = cog
        self.net_name = net_name
        self.report_id = report_id

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        await self.cog._report_dismiss_via_interaction(interaction, self.net_name, self.report_id)


class ReportActionView(discord.ui.View):
    """View attached to report notifications with action buttons.

    The view delegates actual action handling back to the Wormhole cog so the
    existing permission and state logic is reused.
    """

    def __init__(self, cog, net_name: str, report_id: int, jump_url: Optional[str] = None, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.net_name = net_name
        self.report_id = report_id
        if jump_url:
            self.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="Jump to message", url=jump_url))
        # Action buttons
        self.add_item(_ResolveButton(cog, net_name, report_id))
        self.add_item(_DismissButton(cog, net_name, report_id))
