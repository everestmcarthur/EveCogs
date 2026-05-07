"""
Components V2 Help Formatter for Red-DiscordBot.

Replaces the default embed-based help with a fully Components V2
layout featuring containers, sections, buttons, and select menus.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import discord
from discord import ui
from redbot.core import commands
from redbot.core.commands import Command, Group
from redbot.core.utils.chat_formatting import humanize_list, pagify


# ──────────────────────────── constants ────────────────────────────

MAX_FIELDS_PER_PAGE = 12
MAX_COMPONENTS = 38  # Leave room for nav action row + safety margin


# ──────────────────────────── layout builders ────────────────────────────


def _make_header_container(
    title: str,
    description: str = "",
    *,
    accent_color: int = 0x5865F2,
    thumbnail_url: Optional[str] = None,
    bot_name: str = "Bot",
) -> ui.Container:
    """Build the top header container for a help page."""
    container = ui.Container(accent_colour=discord.Colour(accent_color))

    header_md = f"## {title}"
    if description:
        header_md += f"\n{description}"

    if thumbnail_url:
        section = ui.Section(accessory=ui.Thumbnail(thumbnail_url))
        section.add_item(ui.TextDisplay(header_md))
        container.add_item(section)
    else:
        container.add_item(ui.TextDisplay(header_md))

    return container


def _make_category_container(
    category_name: str,
    commands_list: List[Tuple[str, str]],
    *,
    accent_color: int = 0x5865F2,
    emoji: str = "📂",
) -> ui.Container:
    """Build a container for a category with its command listing."""
    container = ui.Container(accent_colour=discord.Colour(accent_color))
    container.add_item(
        ui.TextDisplay(f"### {emoji}  {category_name}")
    )
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    lines: List[str] = []
    for cmd_name, cmd_short in commands_list:
        short = cmd_short[:80] if cmd_short else "No description"
        lines.append(f"`{cmd_name}` — {short}")

    text = "\n".join(lines)
    for chunk in pagify(text, delims=["\n"], page_length=3900):
        container.add_item(ui.TextDisplay(chunk))

    return container


def _make_command_container(
    cmd: commands.Command,
    prefix: str,
    *,
    accent_color: int = 0x5865F2,
) -> ui.Container:
    """Build a detailed container for a single command."""
    container = ui.Container(accent_colour=discord.Colour(accent_color))

    if isinstance(cmd, commands.Group):
        container.add_item(ui.TextDisplay(f"## 📁 {prefix}{cmd.qualified_name}"))
    else:
        container.add_item(ui.TextDisplay(f"## 🔹 {prefix}{cmd.qualified_name}"))

    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    # Usage
    sig = cmd.signature or ""
    usage_line = f"**Usage:** `{prefix}{cmd.qualified_name} {sig}`".strip()
    container.add_item(ui.TextDisplay(usage_line))

    # Description
    help_text = cmd.help or cmd.brief or cmd.short_doc or "No description provided."
    container.add_item(ui.TextDisplay(help_text[:3900]))

    # Aliases
    if cmd.aliases:
        aliases = ", ".join(f"`{a}`" for a in cmd.aliases)
        container.add_item(ui.TextDisplay(f"**Aliases:** {aliases}"))

    # Cooldown
    if cmd.cooldown:
        cd = cmd.cooldown
        container.add_item(
            ui.TextDisplay(
                f"**Cooldown:** {cd.rate} uses per {cd.per:.0f}s ({cd.type.name})"
            )
        )

    # Subcommands for groups
    if isinstance(cmd, commands.Group) and cmd.commands:
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.TextDisplay("### Subcommands"))
        sub_lines = []
        for sub in sorted(cmd.commands, key=lambda c: c.name):
            short = sub.short_doc or "No description"
            sub_lines.append(f"`{prefix}{sub.qualified_name}` — {short[:60]}")
        sub_text = "\n".join(sub_lines)
        for chunk in pagify(sub_text, delims=["\n"], page_length=3900):
            container.add_item(ui.TextDisplay(chunk))

    return container


# ──────────────────────────── paginator view ────────────────────────────


class HelpPaginatorView(ui.LayoutView):
    """A LayoutView that supports paginated help with button navigation."""

    def __init__(
        self,
        pages: List[List[Any]],
        *,
        author_id: int,
        timeout: float = 180.0,
        category_options: Optional[List[discord.SelectOption]] = None,
    ):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
        self.author_id = author_id
        self.category_options = category_options
        self.message: Optional[discord.Message] = None
        self._build_page()

    def _build_page(self):
        """Populate the view with the current page's components."""
        self.clear_items()

        for component in self.pages[self.current_page]:
            self.add_item(component)

        if len(self.pages) > 1:
            self.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

            nav_row = ui.ActionRow()

            nav_row.add_item(ui.Button(
                emoji="⏮️",
                style=discord.ButtonStyle.secondary,
                custom_id="help_first",
                disabled=self.current_page == 0,
            ))
            nav_row.add_item(ui.Button(
                emoji="◀️",
                style=discord.ButtonStyle.primary,
                custom_id="help_prev",
                disabled=self.current_page == 0,
            ))
            nav_row.add_item(ui.Button(
                label=f"{self.current_page + 1}/{len(self.pages)}",
                style=discord.ButtonStyle.secondary,
                custom_id="help_page_indicator",
                disabled=True,
            ))
            nav_row.add_item(ui.Button(
                emoji="▶️",
                style=discord.ButtonStyle.primary,
                custom_id="help_next",
                disabled=self.current_page >= len(self.pages) - 1,
            ))
            nav_row.add_item(ui.Button(
                emoji="⏭️",
                style=discord.ButtonStyle.secondary,
                custom_id="help_last",
                disabled=self.current_page >= len(self.pages) - 1,
            ))
            self.add_item(nav_row)

            close_row = ui.ActionRow()
            close_row.add_item(ui.Button(
                label="Close",
                emoji="🗑️",
                style=discord.ButtonStyle.danger,
                custom_id="help_close",
            ))

            if self.category_options and len(self.category_options) > 1:
                close_row.add_item(ui.Select(
                    placeholder="Jump to category...",
                    options=self.category_options[:25],
                    custom_id="help_category_select",
                ))
            self.add_item(close_row)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This help menu isn't yours!", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                self.clear_items()
                for component in self.pages[self.current_page]:
                    self.add_item(component)
                self.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
                self.add_item(ui.TextDisplay("-# Help menu timed out. Run the help command again."))
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def _handle_nav(self, interaction: discord.Interaction, page: int):
        self.current_page = max(0, min(page, len(self.pages) - 1))
        self._build_page()
        await interaction.response.edit_message(view=self)

    async def handle_interaction(self, interaction: discord.Interaction):
        """Route interactions to the correct handler."""
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""

        if custom_id == "help_first":
            await self._handle_nav(interaction, 0)
        elif custom_id == "help_prev":
            await self._handle_nav(interaction, self.current_page - 1)
        elif custom_id == "help_next":
            await self._handle_nav(interaction, self.current_page + 1)
        elif custom_id == "help_last":
            await self._handle_nav(interaction, len(self.pages) - 1)
        elif custom_id == "help_close":
            self.stop()
            if self.message:
                try:
                    await self.message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
        elif custom_id == "help_category_select":
            values = interaction.data.get("values", []) if interaction.data else []
            if values:
                try:
                    page_idx = int(values[0])
                    await self._handle_nav(interaction, page_idx)
                except (ValueError, IndexError):
                    pass


# ──────────────────────────── menu paginator ────────────────────────────


class CV2MenuPaginator(ui.LayoutView):
    """General-purpose Components V2 paginator to replace Red's menu system."""

    def __init__(
        self,
        pages: List[Any],
        *,
        author_id: int,
        timeout: float = 120.0,
        accent_color: int = 0x5865F2,
    ):
        super().__init__(timeout=timeout)
        self.raw_pages = pages
        self.current_page = 0
        self.author_id = author_id
        self.accent_color = accent_color
        self.message: Optional[discord.Message] = None
        self._build_page()

    def _convert_page(self, page: Any) -> List[Any]:
        """Convert a raw page into components."""
        from .converter import embed_to_container

        if isinstance(page, discord.Embed):
            return [embed_to_container(page, accent_color=self.accent_color)]
        elif isinstance(page, str):
            container = ui.Container(accent_colour=discord.Colour(self.accent_color))
            for chunk in pagify(page, page_length=3900):
                container.add_item(ui.TextDisplay(chunk))
            return [container]
        elif isinstance(page, (ui.Container, ui.TextDisplay)):
            return [page]
        elif isinstance(page, list):
            return page
        else:
            return [ui.TextDisplay(str(page)[:3900])]

    def _build_page(self):
        self.clear_items()

        components = self._convert_page(self.raw_pages[self.current_page])
        for comp in components:
            self.add_item(comp)

        if len(self.raw_pages) > 1:
            self.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            nav_row = ui.ActionRow()

            nav_row.add_item(ui.Button(
                emoji="◀️",
                style=discord.ButtonStyle.primary,
                custom_id="cv2menu_prev",
                disabled=self.current_page == 0,
            ))
            nav_row.add_item(ui.Button(
                label=f"{self.current_page + 1}/{len(self.raw_pages)}",
                style=discord.ButtonStyle.secondary,
                custom_id="cv2menu_indicator",
                disabled=True,
            ))
            nav_row.add_item(ui.Button(
                emoji="▶️",
                style=discord.ButtonStyle.primary,
                custom_id="cv2menu_next",
                disabled=self.current_page >= len(self.raw_pages) - 1,
            ))
            nav_row.add_item(ui.Button(
                label="Close",
                emoji="🗑️",
                style=discord.ButtonStyle.danger,
                custom_id="cv2menu_close",
            ))
            self.add_item(nav_row)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This menu isn't yours!", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                self.clear_items()
                components = self._convert_page(self.raw_pages[self.current_page])
                for comp in components:
                    self.add_item(comp)
                self.add_item(ui.TextDisplay("-# Menu timed out."))
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def handle_interaction(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if custom_id == "cv2menu_prev":
            self.current_page = max(0, self.current_page - 1)
            self._build_page()
            await interaction.response.edit_message(view=self)
        elif custom_id == "cv2menu_next":
            self.current_page = min(len(self.raw_pages) - 1, self.current_page + 1)
            self._build_page()
            await interaction.response.edit_message(view=self)
        elif custom_id == "cv2menu_close":
            self.stop()
            if self.message:
                try:
                    await self.message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass


# ──────────────────────────── help builder ────────────────────────────


async def build_bot_help_pages(
    ctx: commands.Context,
    bot: commands.Bot,
    *,
    categories: Dict[str, List[str]],
    category_emojis: Dict[str, str],
    accent_color: int,
    show_hidden: bool = False,
    blacklisted_cogs: List[str] = None,
    blacklisted_commands: List[str] = None,
) -> Tuple[List[List[Any]], List[discord.SelectOption]]:
    """Build paginated help pages for the full bot.

    Returns (pages, category_select_options).
    """
    blacklisted_cogs = blacklisted_cogs or []
    blacklisted_commands = blacklisted_commands or []

    prefix = ctx.clean_prefix

    # Gather all visible cogs and their commands
    cog_commands: Dict[str, List[commands.Command]] = defaultdict(list)

    for cmd in sorted(bot.commands, key=lambda c: c.qualified_name):
        if cmd.hidden and not show_hidden:
            continue
        if cmd.qualified_name in blacklisted_commands:
            continue
        try:
            if not await cmd.can_run(ctx):
                continue
        except Exception:
            continue

        cog_name = cmd.cog_name or "No Category"
        if cog_name in blacklisted_cogs:
            continue
        cog_commands[cog_name].append(cmd)

    # Build category mappings
    cog_to_category: Dict[str, str] = {}
    for cat_name, cog_list in categories.items():
        for cog_name in cog_list:
            cog_to_category[cog_name] = cat_name

    # Group by category
    category_data: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for cog_name, cmds in cog_commands.items():
        cat = cog_to_category.get(cog_name, cog_name)
        for cmd in cmds:
            short = cmd.short_doc or cmd.brief or "No description"
            category_data[cat].append((f"{prefix}{cmd.qualified_name}", short))

    sorted_cats = sorted(category_data.keys())

    # ── Build pages ──
    pages: List[List[Any]] = []
    select_options: List[discord.SelectOption] = []

    # Page 0: Overview
    bot_user = bot.user
    bot_name = bot_user.display_name if bot_user else "Bot"
    bot_avatar = bot_user.display_avatar.url if bot_user else None

    overview_components: List[Any] = []

    header = _make_header_container(
        f"{bot_name} — Help",
        f"Use `{prefix}help <command>` for details on a command.\nUse `{prefix}help <category>` for a category overview.\n\n**{len(sorted_cats)} categories · {sum(len(v) for v in category_data.values())} commands**",
        accent_color=accent_color,
        thumbnail_url=bot_avatar,
        bot_name=bot_name,
    )
    overview_components.append(header)

    summary_lines: List[str] = []
    for i, cat in enumerate(sorted_cats):
        emoji = category_emojis.get(cat, "📂")
        cmd_count = len(category_data[cat])
        summary_lines.append(f"{emoji} **{cat}** — {cmd_count} command{'s' if cmd_count != 1 else ''}")
        select_options.append(
            discord.SelectOption(
                label=cat[:100],
                value=str(i + 1),
                emoji=emoji if len(emoji) <= 2 else None,
                description=f"{cmd_count} commands",
            )
        )

    summary_container = ui.Container(accent_colour=discord.Colour(accent_color))
    summary_container.add_item(ui.TextDisplay("### 📚 Categories"))
    summary_container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    summary_text = "\n".join(summary_lines)
    for chunk in pagify(summary_text, delims=["\n"], page_length=3900):
        summary_container.add_item(ui.TextDisplay(chunk))
    overview_components.append(summary_container)

    pages.append(overview_components)

    # Category pages
    for cat in sorted_cats:
        cmds = category_data[cat]
        emoji = category_emojis.get(cat, "📂")

        for chunk_start in range(0, len(cmds), MAX_FIELDS_PER_PAGE):
            chunk = cmds[chunk_start: chunk_start + MAX_FIELDS_PER_PAGE]
            page_components: List[Any] = []
            container = _make_category_container(
                cat, chunk, accent_color=accent_color, emoji=emoji
            )
            page_components.append(container)
            pages.append(page_components)

    return pages, select_options


async def build_command_help_page(
    ctx: commands.Context,
    cmd: commands.Command,
    *,
    accent_color: int,
) -> List[Any]:
    """Build a single-page help view for a specific command."""
    prefix = ctx.clean_prefix
    return [_make_command_container(cmd, prefix, accent_color=accent_color)]


async def build_cog_help_page(
    ctx: commands.Context,
    cog: commands.Cog,
    *,
    accent_color: int,
    show_hidden: bool = False,
) -> List[Any]:
    """Build a help page for a specific cog."""
    prefix = ctx.clean_prefix
    components: List[Any] = []

    cog_name = cog.qualified_name
    cog_doc = cog.help or cog.__doc__ or "No description."

    cmds: List[Tuple[str, str]] = []
    for cmd in sorted(cog.get_commands(), key=lambda c: c.qualified_name):
        if cmd.hidden and not show_hidden:
            continue
        try:
            if not await cmd.can_run(ctx):
                continue
        except Exception:
            continue
        short = cmd.short_doc or "No description"
        cmds.append((f"{prefix}{cmd.qualified_name}", short))

    header = ui.Container(accent_colour=discord.Colour(accent_color))
    header.add_item(ui.TextDisplay(f"## 📂 {cog_name}"))
    header.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    header.add_item(ui.TextDisplay(cog_doc[:3900]))
    components.append(header)

    if cmds:
        cmd_container = _make_category_container(
            "Commands", cmds, accent_color=accent_color, emoji="🔹"
        )
        components.append(cmd_container)

    return components
