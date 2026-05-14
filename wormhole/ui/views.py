"""Persistent and ephemeral views for Wormhole messages."""

from __future__ import annotations

import discord


def reply_jump_view(url: str) -> discord.ui.View:
    """Create a View with a single URL button pointing to the replied message."""
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link,
        label="Jump to replied message",
        url=url,
    ))
    return view
