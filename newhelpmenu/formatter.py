"""
Help Formatter for NewHelpMenu — Red-DiscordBot.

Two rendering modes:
  1. Embed mode (default) — rich embeds with a discord.ui.View for buttons/selects
  2. CV2 mode (when toggled) — Components V2 LayoutView with containers

Both share the same data-gathering logic, only rendering differs.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import discord
from discord import ui
from discord.ext import commands as dpy_commands
from redbot.core import commands
from redbot.core.commands import Command, Group
from redbot.core.utils.chat_formatting import humanize_list, pagify

log = logging.getLogger("red.evecogs.newhelpmenu.formatter")

MAX_FIELDS_PER_PAGE = 8
EMBED_CHAR_LIMIT = 5800  # Leave margin under 6000


# ══════════════════════════════════════════════════════════════════
#  DATA GATHERING (shared by both embed and CV2 modes)
# ══════════════════════════════════════════════════════════════════


async def gather_bot_help_data(
    ctx: commands.Context,
    bot,
    *,
    categories: Dict[str, List[str]],
    category_emojis: Dict[str, str],
    show_hidden: bool = False,
    blacklisted_cogs: Optional[List[str]] = None,
    blacklisted_commands: Optional[List[str]] = None,
) -> Tuple[List[Tuple[str, str, List[Tuple[str, str]]]], int]:
    """Gather help data for all bot commands.

    Returns:
        (category_list, total_commands)
        category_list: [(category_name, emoji, [(cmd_name, short_doc), ...]), ...]
    """
    blacklisted_cogs = blacklisted_cogs or []
    blacklisted_commands = blacklisted_commands or []
    prefix = ctx.clean_prefix

    # Gather all visible commands grouped by cog
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

    # Map cogs → categories
    cog_to_category: Dict[str, str] = {}
    for cat_name, cog_list in categories.items():
        for cog_name in cog_list:
            cog_to_category[cog_name] = cat_name

    # Group by category
    category_data: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    total = 0
    for cog_name, cmds in cog_commands.items():
        cat = cog_to_category.get(cog_name, cog_name)
        for cmd in cmds:
            short = cmd.format_shortdoc_for_context(ctx) if hasattr(cmd, 'format_shortdoc_for_context') else (cmd.short_doc or "No description")
            category_data[cat].append((f"{prefix}{cmd.qualified_name}", short))
            total += 1

    sorted_cats = sorted(category_data.keys())
    result = []
    for cat in sorted_cats:
        emoji = category_emojis.get(cat, "📂")
        result.append((cat, emoji, category_data[cat]))

    return result, total


async def gather_cog_help_data(
    ctx: commands.Context,
    cog: commands.Cog,
    *,
    show_hidden: bool = False,
) -> Tuple[str, str, List[Tuple[str, str, str]]]:
    """Gather help data for a cog.

    Returns:
        (cog_name, cog_doc, [(qualified_name, signature, short_doc), ...])
    """
    prefix = ctx.clean_prefix
    cog_name = cog.qualified_name
    cog_doc = ""
    if hasattr(cog, 'format_help_for_context'):
        cog_doc = cog.format_help_for_context(ctx)
    if not cog_doc:
        cog_doc = cog.help or cog.__doc__ or "No description."

    cmds = []
    for cmd in sorted(cog.get_commands(), key=lambda c: c.qualified_name):
        if cmd.hidden and not show_hidden:
            continue
        try:
            if not await cmd.can_run(ctx):
                continue
        except Exception:
            continue
        sig = cmd.signature or ""
        short = cmd.format_shortdoc_for_context(ctx) if hasattr(cmd, 'format_shortdoc_for_context') else (cmd.short_doc or "No description")
        cmds.append((f"{prefix}{cmd.qualified_name}", sig, short))

    return cog_name, cog_doc, cmds


async def gather_command_help_data(
    ctx: commands.Context,
    cmd: commands.Command,
) -> Dict[str, Any]:
    """Gather help data for a single command.

    Returns dict with: name, signature, description, aliases, subcommands, cooldown
    """
    prefix = ctx.clean_prefix
    parent_sig = ""
    parent = cmd.parent
    entries = []
    while parent is not None:
        if not parent.signature or parent.invoke_without_command:
            entries.append(parent.name)
        else:
            entries.append(parent.name + " " + parent.signature)
        parent = parent.parent
    if entries:
        parent_sig = " ".join(reversed(entries)) + " "

    signature = f"{prefix}{parent_sig}{cmd.name} {cmd.signature}".strip()

    help_text = ""
    if hasattr(cmd, 'format_help_for_context'):
        help_text = cmd.format_help_for_context(ctx)
    if not help_text:
        help_text = cmd.help or cmd.description or cmd.short_doc or "No description provided."

    data = {
        "name": cmd.qualified_name,
        "signature": signature,
        "description": help_text,
        "aliases": [],
        "subcommands": [],
        "cooldown": None,
        "is_group": isinstance(cmd, commands.Group),
    }

    if cmd.aliases:
        data["aliases"] = sorted(cmd.aliases, key=len)

    if isinstance(cmd, commands.Group) and cmd.commands:
        for sub in sorted(cmd.commands, key=lambda c: c.name):
            if sub.hidden:
                continue
            sub_short = sub.format_shortdoc_for_context(ctx) if hasattr(sub, 'format_shortdoc_for_context') else (sub.short_doc or "No description")
            data["subcommands"].append((f"{prefix}{sub.qualified_name}", sub_short))

    if cmd.cooldown:
        cd = cmd.cooldown
        data["cooldown"] = f"{cd.rate} use{'s' if cd.rate > 1 else ''} per {cd.per:.0f}s ({cd.type.name})"

    return data


# ══════════════════════════════════════════════════════════════════
#  EMBED MODE — Rich embeds with discord.ui.View buttons/selects
# ══════════════════════════════════════════════════════════════════


class EmbedHelpView(discord.ui.View):
    """An interactive embed-based help menu with buttons and category select."""

    def __init__(
        self,
        pages: List[discord.Embed],
        *,
        author_id: int,
        timeout: float = 180.0,
        category_options: Optional[List[discord.SelectOption]] = None,
    ):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
        self.author_id = author_id
        self.message: Optional[discord.Message] = None

        # Add category select if we have categories
        if category_options and len(category_options) > 1:
            select = discord.ui.Select(
                placeholder="Jump to category…",
                options=category_options[:25],
                custom_id="help_cat_select",
                row=0,
            )
            select.callback = self._select_callback
            self.add_item(select)

        # Navigation buttons
        self.first_btn = discord.ui.Button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=1)
        self.first_btn.callback = self._first
        self.add_item(self.first_btn)

        self.prev_btn = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.primary, row=1)
        self.prev_btn.callback = self._prev
        self.add_item(self.prev_btn)

        self.indicator = discord.ui.Button(
            label=f"1/{len(pages)}", style=discord.ButtonStyle.secondary, disabled=True, row=1
        )
        self.add_item(self.indicator)

        self.next_btn = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.primary, row=1)
        self.next_btn.callback = self._next
        self.add_item(self.next_btn)

        self.last_btn = discord.ui.Button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=1)
        self.last_btn.callback = self._last
        self.add_item(self.last_btn)

        self.close_btn = discord.ui.Button(
            label="Close", emoji="🗑️", style=discord.ButtonStyle.danger, row=2
        )
        self.close_btn.callback = self._close
        self.add_item(self.close_btn)

        self._update_buttons()

    def _update_buttons(self):
        at_start = self.current_page == 0
        at_end = self.current_page >= len(self.pages) - 1
        self.first_btn.disabled = at_start
        self.prev_btn.disabled = at_start
        self.next_btn.disabled = at_end
        self.last_btn.disabled = at_end
        self.indicator.label = f"{self.current_page + 1}/{len(self.pages)}"

    async def _go_to(self, interaction: discord.Interaction, page: int):
        self.current_page = max(0, min(page, len(self.pages) - 1))
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def _first(self, interaction: discord.Interaction):
        await self._go_to(interaction, 0)

    async def _prev(self, interaction: discord.Interaction):
        await self._go_to(interaction, self.current_page - 1)

    async def _next(self, interaction: discord.Interaction):
        await self._go_to(interaction, self.current_page + 1)

    async def _last(self, interaction: discord.Interaction):
        await self._go_to(interaction, len(self.pages) - 1)

    async def _close(self, interaction: discord.Interaction):
        self.stop()
        if self.message:
            try:
                await self.message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

    async def _select_callback(self, interaction: discord.Interaction):
        values = interaction.data.get("values", []) if interaction.data else []
        if values:
            try:
                page_idx = int(values[0])
                await self._go_to(interaction, page_idx)
            except (ValueError, IndexError):
                await interaction.response.defer()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help menu isn't yours!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


def build_bot_help_embeds(
    ctx,
    bot,
    category_data: List[Tuple[str, str, List[Tuple[str, str]]]],
    total_commands: int,
    *,
    accent_color: int,
) -> Tuple[List[discord.Embed], List[discord.SelectOption]]:
    """Build embed pages for the full bot help.

    Returns (embeds, select_options).
    """
    prefix = ctx.clean_prefix
    bot_name = bot.user.display_name if bot.user else "Bot"
    bot_avatar = bot.user.display_avatar.url if bot.user else None
    color = discord.Colour(accent_color)

    pages: List[discord.Embed] = []
    select_options: List[discord.SelectOption] = []

    # Page 0: Overview
    overview = discord.Embed(
        title=f"{bot_name} — Help",
        description=(
            f"Use `{prefix}help <command>` for details on a command.\n"
            f"Use `{prefix}help <category>` for a category overview.\n\n"
            f"**{len(category_data)} categories · {total_commands} commands**"
        ),
        color=color,
    )
    if bot_avatar:
        overview.set_thumbnail(url=bot_avatar)

    for i, (cat_name, emoji, cmds) in enumerate(category_data):
        if i >= 20:  # Discord max 25 fields; leave room
            overview.add_field(
                name="…and more",
                value=f"Use the category select or `{prefix}help <category>` to see all.",
                inline=False,
            )
            break
        cmd_names = ", ".join(f"`{name.split()[-1]}`" for name, _ in cmds[:12])
        if len(cmds) > 12:
            cmd_names += f" *+{len(cmds) - 12} more*"
        overview.add_field(
            name=f"{emoji} {cat_name} ({len(cmds)})",
            value=cmd_names or "No commands",
            inline=False,
        )

    overview.set_footer(text=f"Type {prefix}help <command> for more info on a command.")
    pages.append(overview)

    # Category pages
    for idx, (cat_name, emoji, cmds) in enumerate(category_data):
        select_options.append(discord.SelectOption(
            label=cat_name[:100],
            value=str(idx + 1),
            emoji=emoji if len(emoji) <= 2 else None,
            description=f"{len(cmds)} commands",
        ))

        # Split into multiple pages if many commands
        for chunk_start in range(0, len(cmds), MAX_FIELDS_PER_PAGE):
            chunk = cmds[chunk_start:chunk_start + MAX_FIELDS_PER_PAGE]
            embed = discord.Embed(
                title=f"{emoji} {cat_name}",
                color=color,
            )
            if bot_avatar:
                embed.set_thumbnail(url=bot_avatar)

            for cmd_name, short in chunk:
                # Use inline=False for readability
                embed.add_field(
                    name=cmd_name,
                    value=short[:100] if short else "No description",
                    inline=True,
                )

            embed.set_footer(text=f"Type {prefix}help <command> for more details.")
            pages.append(embed)

    return pages, select_options


def build_command_help_embed(
    ctx,
    data: Dict[str, Any],
    *,
    accent_color: int,
) -> discord.Embed:
    """Build an embed for a single command."""
    prefix = ctx.clean_prefix
    bot_avatar = ctx.bot.user.display_avatar.url if ctx.bot.user else None
    color = discord.Colour(accent_color)

    title = f"{'📁' if data['is_group'] else '🔹'} {data['name']}"
    embed = discord.Embed(title=title, color=color)
    if bot_avatar:
        embed.set_thumbnail(url=bot_avatar)

    # Syntax
    embed.add_field(name="Syntax", value=f"```\n{data['signature']}\n```", inline=False)

    # Description
    desc = data["description"]
    if len(desc) > 1024:
        desc = desc[:1021] + "..."
    embed.add_field(name="Description", value=desc, inline=False)

    # Aliases
    if data["aliases"]:
        alias_text = ", ".join(f"`{prefix}{data['name'].rsplit(' ', 1)[0] + ' ' if ' ' in data['name'] else ''}{a}`" for a in data["aliases"][:10])
        embed.add_field(name="Aliases", value=alias_text, inline=False)

    # Cooldown
    if data["cooldown"]:
        embed.add_field(name="Cooldown", value=data["cooldown"], inline=True)

    # Subcommands
    if data["subcommands"]:
        sub_text = "\n".join(f"`{name}` — {short[:60]}" for name, short in data["subcommands"])
        if len(sub_text) > 1024:
            sub_text = sub_text[:1021] + "..."
        embed.add_field(name="Subcommands", value=sub_text, inline=False)

    embed.set_footer(text=f"Type {prefix}help <command> for more details.")
    return embed


def build_cog_help_embed(
    ctx,
    cog_name: str,
    cog_doc: str,
    cmds: List[Tuple[str, str, str]],
    *,
    accent_color: int,
) -> discord.Embed:
    """Build an embed for a cog's help page."""
    prefix = ctx.clean_prefix
    bot_avatar = ctx.bot.user.display_avatar.url if ctx.bot.user else None
    color = discord.Colour(accent_color)

    embed = discord.Embed(title=f"📂 {cog_name}", description=cog_doc[:2048], color=color)
    if bot_avatar:
        embed.set_thumbnail(url=bot_avatar)

    if cmds:
        cmd_lines = []
        for qname, sig, short in cmds:
            cmd_lines.append(f"`{qname}` — {short[:80]}")
        cmd_text = "\n".join(cmd_lines)
        for i, chunk in enumerate(pagify(cmd_text, delims=["\n"], page_length=1024)):
            name = "Commands" if i == 0 else "Commands (continued)"
            embed.add_field(name=name, value=chunk, inline=False)

    embed.set_footer(text=f"Type {prefix}help <command> for more details.")
    return embed


# ══════════════════════════════════════════════════════════════════
#  CV2 MODE — Components V2 LayoutView with containers
# ══════════════════════════════════════════════════════════════════


def _make_category_container(
    category_name: str,
    commands_list: List[Tuple[str, str]],
    *,
    accent_color: int = 0x5865F2,
    emoji: str = "📂",
) -> ui.Container:
    """Build a CV2 container for a category."""
    container = ui.Container(accent_colour=discord.Colour(accent_color))
    container.add_item(ui.TextDisplay(f"### {emoji}  {category_name}"))
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    lines = []
    for cmd_name, cmd_short in commands_list:
        short = cmd_short[:80] if cmd_short else "No description"
        lines.append(f"`{cmd_name}` — {short}")

    text = "\n".join(lines)
    for chunk in pagify(text, delims=["\n"], page_length=3900):
        container.add_item(ui.TextDisplay(chunk))

    return container


class HelpPaginatorView(ui.LayoutView):
    """CV2 LayoutView paginator for help."""

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
        self.clear_items()
        for component in self.pages[self.current_page]:
            self.add_item(component)

        if len(self.pages) > 1:
            self.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            nav_row = ui.ActionRow()
            nav_row.add_item(ui.Button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="help_first", disabled=self.current_page == 0))
            nav_row.add_item(ui.Button(emoji="◀️", style=discord.ButtonStyle.primary, custom_id="help_prev", disabled=self.current_page == 0))
            nav_row.add_item(ui.Button(label=f"{self.current_page + 1}/{len(self.pages)}", style=discord.ButtonStyle.secondary, custom_id="help_page_ind", disabled=True))
            nav_row.add_item(ui.Button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="help_next", disabled=self.current_page >= len(self.pages) - 1))
            nav_row.add_item(ui.Button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="help_last", disabled=self.current_page >= len(self.pages) - 1))
            self.add_item(nav_row)

            close_row = ui.ActionRow()
            close_row.add_item(ui.Button(label="Close", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="help_close"))
            self.add_item(close_row)

            if self.category_options and len(self.category_options) > 1:
                select_row = ui.ActionRow()
                select_row.add_item(ui.Select(placeholder="Jump to category…", options=self.category_options[:25], custom_id="help_category_select"))
                self.add_item(select_row)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This help menu isn't yours!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                self.clear_items()
                for component in self.pages[self.current_page]:
                    self.add_item(component)
                self.add_item(ui.TextDisplay("-# Help menu timed out."))
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def handle_interaction(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if custom_id == "help_first":
            page = 0
        elif custom_id == "help_prev":
            page = self.current_page - 1
        elif custom_id == "help_next":
            page = self.current_page + 1
        elif custom_id == "help_last":
            page = len(self.pages) - 1
        elif custom_id == "help_close":
            self.stop()
            if self.message:
                try:
                    await self.message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
            return
        elif custom_id == "help_category_select":
            values = interaction.data.get("values", []) if interaction.data else []
            if values:
                try:
                    page = int(values[0])
                except (ValueError, IndexError):
                    return
            else:
                return
        else:
            return

        self.current_page = max(0, min(page, len(self.pages) - 1))
        self._build_page()
        await interaction.response.edit_message(view=self)


def build_cv2_bot_help_pages(
    ctx,
    bot,
    category_data: List[Tuple[str, str, List[Tuple[str, str]]]],
    total_commands: int,
    *,
    accent_color: int,
) -> Tuple[List[List[Any]], List[discord.SelectOption]]:
    """Build CV2 pages for the full bot help."""
    prefix = ctx.clean_prefix
    bot_name = bot.user.display_name if bot.user else "Bot"
    bot_avatar = bot.user.display_avatar.url if bot.user else None
    color = discord.Colour(accent_color)

    pages: List[List[Any]] = []
    select_options: List[discord.SelectOption] = []

    # Overview page
    overview_components: List[Any] = []
    header = ui.Container(accent_colour=color)
    header_md = f"## {bot_name} — Help\nUse `{prefix}help <command>` for details.\n\n**{len(category_data)} categories · {total_commands} commands**"
    if bot_avatar:
        section = ui.Section(accessory=ui.Thumbnail(bot_avatar))
        section.add_item(ui.TextDisplay(header_md))
        header.add_item(section)
    else:
        header.add_item(ui.TextDisplay(header_md))
    overview_components.append(header)

    summary = ui.Container(accent_colour=color)
    summary.add_item(ui.TextDisplay("### 📚 Categories"))
    summary.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    summary_lines = []
    for i, (cat_name, emoji, cmds) in enumerate(category_data):
        summary_lines.append(f"{emoji} **{cat_name}** — {len(cmds)} command{'s' if len(cmds) != 1 else ''}")
        select_options.append(discord.SelectOption(
            label=cat_name[:100], value=str(i + 1),
            emoji=emoji if len(emoji) <= 2 else None,
            description=f"{len(cmds)} commands",
        ))
    summary.add_item(ui.TextDisplay("\n".join(summary_lines)))
    overview_components.append(summary)
    pages.append(overview_components)

    # Category pages
    for cat_name, emoji, cmds in category_data:
        for chunk_start in range(0, len(cmds), MAX_FIELDS_PER_PAGE):
            chunk = cmds[chunk_start:chunk_start + MAX_FIELDS_PER_PAGE]
            page_components: List[Any] = [_make_category_container(cat_name, chunk, accent_color=accent_color, emoji=emoji)]
            pages.append(page_components)

    return pages, select_options


def build_cv2_command_help(
    ctx,
    data: Dict[str, Any],
    *,
    accent_color: int,
) -> List[Any]:
    """Build CV2 components for a command."""
    prefix = ctx.clean_prefix
    color = discord.Colour(accent_color)
    container = ui.Container(accent_colour=color)

    icon = "📁" if data["is_group"] else "🔹"
    container.add_item(ui.TextDisplay(f"## {icon} {data['name']}"))
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    container.add_item(ui.TextDisplay(f"**Syntax:** `{data['signature']}`"))
    container.add_item(ui.TextDisplay(data["description"][:3900]))

    if data["aliases"]:
        aliases = ", ".join(f"`{a}`" for a in data["aliases"][:10])
        container.add_item(ui.TextDisplay(f"**Aliases:** {aliases}"))

    if data["cooldown"]:
        container.add_item(ui.TextDisplay(f"**Cooldown:** {data['cooldown']}"))

    if data["subcommands"]:
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.TextDisplay("### Subcommands"))
        sub_lines = [f"`{name}` — {short[:60]}" for name, short in data["subcommands"]]
        container.add_item(ui.TextDisplay("\n".join(sub_lines)))

    return [container]


def build_cv2_cog_help(
    ctx,
    cog_name: str,
    cog_doc: str,
    cmds: List[Tuple[str, str, str]],
    *,
    accent_color: int,
) -> List[Any]:
    """Build CV2 components for a cog."""
    color = discord.Colour(accent_color)

    header = ui.Container(accent_colour=color)
    header.add_item(ui.TextDisplay(f"## 📂 {cog_name}"))
    header.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    header.add_item(ui.TextDisplay(cog_doc[:3900]))
    components: List[Any] = [header]

    if cmds:
        cmd_list = [(qname, short) for qname, _, short in cmds]
        components.append(_make_category_container("Commands", cmd_list, accent_color=accent_color, emoji="🔹"))

    return components


# ══════════════════════════════════════════════════════════════════
#  CV2 MENU PAGINATOR (general purpose)
# ══════════════════════════════════════════════════════════════════


class CV2MenuPaginator(ui.LayoutView):
    """General-purpose CV2 paginator to replace Red's menu system."""

    def __init__(self, pages: List[Any], *, author_id: int, timeout: float = 120.0, accent_color: int = 0x5865F2):
        super().__init__(timeout=timeout)
        self.raw_pages = pages
        self.current_page = 0
        self.author_id = author_id
        self.accent_color = accent_color
        self.message: Optional[discord.Message] = None
        self._build_page()

    def _convert_page(self, page: Any) -> List[Any]:
        from .converter import embed_to_container
        if isinstance(page, discord.Embed):
            return [embed_to_container(page, accent_color=self.accent_color)]
        elif isinstance(page, str):
            container = ui.Container(accent_colour=discord.Colour(self.accent_color))
            container.add_item(ui.TextDisplay(page[:3900]))
            return [container]
        elif isinstance(page, list):
            return page
        return [ui.TextDisplay(str(page)[:3900])]

    def _build_page(self):
        self.clear_items()
        for comp in self._convert_page(self.raw_pages[self.current_page]):
            self.add_item(comp)
        if len(self.raw_pages) > 1:
            self.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            nav_row = ui.ActionRow()
            nav_row.add_item(ui.Button(emoji="◀️", style=discord.ButtonStyle.primary, custom_id="cv2menu_prev", disabled=self.current_page == 0))
            nav_row.add_item(ui.Button(label=f"{self.current_page + 1}/{len(self.raw_pages)}", style=discord.ButtonStyle.secondary, custom_id="cv2menu_ind", disabled=True))
            nav_row.add_item(ui.Button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="cv2menu_next", disabled=self.current_page >= len(self.raw_pages) - 1))
            nav_row.add_item(ui.Button(label="Close", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="cv2menu_close"))
            self.add_item(nav_row)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This menu isn't yours!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                self.clear_items()
                for comp in self._convert_page(self.raw_pages[self.current_page]):
                    self.add_item(comp)
                self.add_item(ui.TextDisplay("-# Menu timed out."))
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def handle_interaction(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if custom_id == "cv2menu_prev":
            self.current_page = max(0, self.current_page - 1)
        elif custom_id == "cv2menu_next":
            self.current_page = min(len(self.raw_pages) - 1, self.current_page + 1)
        elif custom_id == "cv2menu_close":
            self.stop()
            if self.message:
                try:
                    await self.message.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
            return
        else:
            return
        self._build_page()
        await interaction.response.edit_message(view=self)
