"""
Embed → Components V2 converter.

Translates discord.Embed objects into discord.ui LayoutView trees
using Containers, Sections, TextDisplays, Thumbnails, MediaGalleries,
Separators, and ActionRows.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

import discord
from discord import ui


# ──────────────────────────── helpers ────────────────────────────

def _truncate(text: str, limit: int = 4000) -> str:
    """Truncate to Discord's TextDisplay limit."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _field_to_md(field: Any) -> str:
    """Convert an embed field to markdown."""
    name = getattr(field, "name", "") or ""
    value = getattr(field, "value", "") or ""
    if name:
        return f"**{name}**\n{value}"
    return value


# ──────────────────────────── core ────────────────────────────


def embed_to_container(
    embed: discord.Embed,
    *,
    accent_color: Optional[int] = None,
    show_thumbnail: bool = True,
    show_footer: bool = True,
    compact: bool = False,
) -> ui.Container:
    """Convert a ``discord.Embed`` into a ``discord.ui.Container``.

    Parameters
    ----------
    embed:
        The embed to convert.
    accent_color:
        Override accent colour. Falls back to embed colour, then None.
    show_thumbnail:
        Whether to render the thumbnail as a Thumbnail accessory.
    show_footer:
        Whether to render the footer line.
    compact:
        If True, merges fields into fewer TextDisplays.
    """
    # Resolve colour
    color = accent_color
    if color is None and embed.color and embed.color.value:
        color = embed.color.value
    if color is None:
        color = discord.Color.blurple().value

    container = ui.Container(accent_colour=discord.Colour(color))

    # ── Author line ──
    author_text = ""
    if embed.author and embed.author.name:
        author_name = embed.author.name
        if embed.author.url:
            author_text = f"[{author_name}]({embed.author.url})"
        else:
            author_text = author_name

    # ── Title + URL ──
    title_text = ""
    if embed.title:
        title = embed.title
        if embed.url:
            title_text = f"### [{title}]({embed.url})"
        else:
            title_text = f"### {title}"

    # ── Description ──
    desc_text = embed.description or ""

    # Build the header block — combine author, title, description
    header_parts = []
    if author_text:
        header_parts.append(author_text)
    if title_text:
        header_parts.append(title_text)
    if desc_text:
        header_parts.append(desc_text)

    header_md = "\n".join(header_parts)

    # ── Thumbnail? → use Section with accessory ──
    thumbnail_url = None
    if show_thumbnail and embed.thumbnail and embed.thumbnail.url:
        thumbnail_url = embed.thumbnail.url

    if header_md:
        if thumbnail_url:
            # Section: header text + thumbnail accessory
            section = ui.Section(
                accessory=ui.Thumbnail(thumbnail_url),
            )
            section.add_item(ui.TextDisplay(_truncate(header_md)))
            container.add_item(section)
        else:
            container.add_item(ui.TextDisplay(_truncate(header_md)))

    # ── Fields ──
    if embed.fields:
        if header_md:
            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

        if compact:
            # Merge all fields into one or two text displays
            inline_row: List[str] = []
            blocks: List[str] = []
            for field in embed.fields:
                md = _field_to_md(field)
                if getattr(field, "inline", False):
                    inline_row.append(md)
                    if len(inline_row) >= 3:
                        blocks.append(" · ".join(inline_row))
                        inline_row = []
                else:
                    if inline_row:
                        blocks.append(" · ".join(inline_row))
                        inline_row = []
                    blocks.append(md)
            if inline_row:
                blocks.append(" · ".join(inline_row))
            combined = "\n\n".join(blocks)
            container.add_item(ui.TextDisplay(_truncate(combined)))
        else:
            # Group inline fields, render non-inline as standalone
            inline_buffer: List[str] = []
            for field in embed.fields:
                md = _field_to_md(field)
                if getattr(field, "inline", False):
                    inline_buffer.append(md)
                    if len(inline_buffer) >= 3:
                        joined = " · ".join(inline_buffer)
                        container.add_item(ui.TextDisplay(_truncate(joined)))
                        inline_buffer = []
                else:
                    if inline_buffer:
                        joined = " · ".join(inline_buffer)
                        container.add_item(ui.TextDisplay(_truncate(joined)))
                        inline_buffer = []
                    container.add_item(ui.TextDisplay(_truncate(md)))
            if inline_buffer:
                joined = " · ".join(inline_buffer)
                container.add_item(ui.TextDisplay(_truncate(joined)))

    # ── Image ──
    if embed.image and embed.image.url:
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(
            ui.MediaGallery(
                ui.MediaGalleryItem(embed.image.url)
            )
        )

    # ── Footer + timestamp ──
    if show_footer:
        footer_parts: List[str] = []
        if embed.footer and embed.footer.text:
            footer_parts.append(embed.footer.text)
        if embed.timestamp:
            footer_parts.append(
                f"<t:{int(embed.timestamp.timestamp())}:R>"
            )
        if footer_parts:
            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            footer_md = "-# " + " · ".join(footer_parts)
            container.add_item(ui.TextDisplay(_truncate(footer_md, 4000)))

    return container


def embeds_to_layout(
    embeds: List[discord.Embed],
    content: Optional[str] = None,
    *,
    accent_color: Optional[int] = None,
    show_thumbnail: bool = True,
    show_footer: bool = True,
    compact: bool = False,
    existing_action_rows: Optional[List[ui.ActionRow]] = None,
) -> ui.LayoutView:
    """Convert a list of embeds (and optional content) to a full LayoutView.

    Parameters
    ----------
    embeds:
        List of embeds to convert.
    content:
        Optional text content to add before embeds.
    accent_color:
        Global accent colour override.
    show_thumbnail:
        Whether to render thumbnails.
    show_footer:
        Whether to render footers.
    compact:
        Compact field rendering.
    existing_action_rows:
        Pre-built action rows (buttons/selects) to append.
    """
    layout = ui.LayoutView()

    # Optional leading text
    if content:
        layout.add_item(ui.TextDisplay(_truncate(content)))

    # Convert each embed to a container
    for i, embed in enumerate(embeds):
        if i > 0:
            layout.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        container = embed_to_container(
            embed,
            accent_color=accent_color,
            show_thumbnail=show_thumbnail,
            show_footer=show_footer,
            compact=compact,
        )
        layout.add_item(container)

    # Append any action rows (buttons, selects)
    if existing_action_rows:
        for row in existing_action_rows:
            layout.add_item(row)

    return layout


def view_items_to_action_rows(view: ui.View) -> List[ui.ActionRow]:
    """Extract action rows from a regular View for re-use in LayoutView."""
    rows: List[ui.ActionRow] = []
    for child in view.children:
        if isinstance(child, ui.ActionRow):
            rows.append(child)
        elif isinstance(child, (ui.Button, ui.Select)):
            row = ui.ActionRow()
            row.add_item(child)
            rows.append(row)
    return rows
