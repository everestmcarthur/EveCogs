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
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import discord
from discord import ui
from discord.ext import commands as dpy_commands
from redbot.core import commands
from redbot.core.commands import Command, Group
from redbot.core.utils.chat_formatting import humanize_list, pagify

log = logging.getLogger("red.evecogs.newhelpmenu.formatter")

MAX_FIELDS_PER_PAGE = 6  # Keep pages clean, not cramped
EMBED_CHAR_LIMIT = 5800


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

    cog_to_category: Dict[str, str] = {}
    for cat_name, cog_list in categories.items():
        for cog_name in cog_list:
            cog_to_category[cog_name] = cat_name

    category_data: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    total = 0
    for cog_name, cmds in cog_commands.items():
        cat = cog_to_category.get(cog_name, cog_name)
        for cmd in cmds:
            short = cmd.format_shortdoc_for_context(ctx) if hasattr(cmd, "format_shortdoc_for_context") else (cmd.short_doc or "No description")
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
    if hasattr(cog, "format_help_for_context"):
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
        short = cmd.format_shortdoc_for_context(ctx) if hasattr(cmd, "format_shortdoc_for_context") else (cmd.short_doc or "No description")
        cmds.append((f"{prefix}{cmd.qualified_name}", sig, short))

    return cog_name, cog_doc, cmds


async def gather_command_help_data(
    ctx: commands.Context,
    cmd: commands.Command,
) -> Dict[str, Any]:
    """Gather help data for a single command."""
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
    if hasattr(cmd, "format_help_for_context"):
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
            sub_short = sub.format_shortdoc_for_context(ctx) if hasattr(sub, "format_shortdoc_for_context") else (sub.short_doc or "No description")
            data["subcommands"].append((f"{prefix}{sub.qualified_name}", sub_short))

    if cmd.cooldown:
        cd = cmd.cooldown
        data["cooldown"] = f"{cd.rate} use{'s' if cd.rate > 1 else ''} per {cd.per:.0f}s ({cd.type.name})"

    return data


# ══════════════════════════════════════════════════════════════════
#  EMBED MODE — Polished embeds with discord.ui.View
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

        # Category select (row 0)
        if category_options and len(category_options) > 1:
            select = discord.ui.Select(
                placeholder="⏩ Jump to category…",
                options=category_options[:25],
                custom_id="help_cat_select",
                row=0,
            )
            select.callback = self._select_callback
            self.add_item(select)

        # Navigation buttons (row 1)
        self.first_btn = discord.ui.Button(emoji="⏮", style=discord.ButtonStyle.secondary, row=1, disabled=True)
        self.first_btn.callback = self._first
        self.add_item(self.first_btn)

        self.prev_btn = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.primary, row=1, disabled=True)
        self.prev_btn.callback = self._prev
        self.add_item(self.prev_btn)

        self.indicator = discord.ui.Button(
            label=f"Page 1 of {len(pages)}", style=discord.ButtonStyle.secondary, disabled=True, row=1
        )
        self.add_item(self.indicator)

        self.next_btn = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.primary, row=1)
        self.next_btn.callback = self._next
        self.add_item(self.next_btn)

        self.last_btn = discord.ui.Button(emoji="⏭", style=discord.ButtonStyle.secondary, row=1)
        self.last_btn.callback = self._last
        self.add_item(self.last_btn)

        # Close button (row 2)
        self.close_btn = discord.ui.Button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
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
        self.indicator.label = f"Page {self.current_page + 1} of {len(self.pages)}"

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


# ─── Embed builders ───────────────────────────────────────────────


def _cmd_table(cmds: List[Tuple[str, str]], *, prefix: str = "") -> str:
    """Format commands as a clean aligned table inside a description."""
    lines = []
    for cmd_name, short in cmds:
        # Strip prefix from display name for cleaner look
        display = cmd_name
        if prefix and display.startswith(prefix):
            display = display[len(prefix):]
        desc = short[:50] if short else "No description"
        lines.append(f"` {display} ` · {desc}")
    return "\n".join(lines)


def build_bot_help_embeds(
    ctx,
    bot,
    category_data: List[Tuple[str, str, List[Tuple[str, str]]]],
    total_commands: int,
    *,
    accent_color: int,
) -> Tuple[List[discord.Embed], List[discord.SelectOption]]:
    """Build polished embed pages for the full bot help."""
    prefix = ctx.clean_prefix
    bot_name = bot.user.display_name if bot.user else "Bot"
    bot_avatar = bot.user.display_avatar.url if bot.user else None
    color = discord.Colour(accent_color)
    total_pages_estimate = 1 + sum(max(1, math.ceil(len(cmds) / MAX_FIELDS_PER_PAGE)) for _, _, cmds in category_data)

    pages: List[discord.Embed] = []
    select_options: List[discord.SelectOption] = []

    # ── Page 0: Overview ─────────────────────────────────
    overview = discord.Embed(color=color)
    overview.set_author(name=f"{bot_name} · Help Menu", icon_url=bot_avatar)

    desc_lines = [
        f"Welcome! I have **{total_commands}** commands across **{len(category_data)}** categories.",
        "",
        f"▸ `{prefix}help <command>` — details on a command",
        f"▸ `{prefix}help <category>` — browse a category",
        "",
        "**╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍**",
    ]
    overview.description = "\n".join(desc_lines)

    if bot_avatar:
        overview.set_thumbnail(url=bot_avatar)

    # Show categories as compact inline fields
    for i, (cat_name, emoji, cmds) in enumerate(category_data):
        if i >= 18:  # Stay well under 25
            overview.add_field(
                name=f"… +{len(category_data) - 18} more",
                value=f"Use the dropdown to browse.",
                inline=False,
            )
            break
        cmd_preview = ", ".join(f"`{n.split()[-1]}`" for n, _ in cmds[:6])
        if len(cmds) > 6:
            cmd_preview += f" +{len(cmds) - 6}"
        overview.add_field(
            name=f"{emoji}  {cat_name}  ·  {len(cmds)}",
            value=cmd_preview or "*No commands*",
            inline=True,
        )

    # Pad with empty inline field if odd number for cleaner grid
    field_count = min(len(category_data), 18)
    if field_count % 2 == 1:
        overview.add_field(name="\u200b", value="\u200b", inline=True)

    overview.set_footer(text=f"Page 1 of {total_pages_estimate}  ·  Use the buttons below to navigate")
    pages.append(overview)

    # ── Category pages ───────────────────────────────────
    page_idx = 1
    for cat_i, (cat_name, emoji, cmds) in enumerate(category_data):
        select_options.append(discord.SelectOption(
            label=cat_name[:100],
            value=str(page_idx),
            emoji=emoji if len(emoji) <= 2 else None,
            description=f"{len(cmds)} command{'s' if len(cmds) != 1 else ''}",
        ))

        chunks = [cmds[i:i + MAX_FIELDS_PER_PAGE] for i in range(0, len(cmds), MAX_FIELDS_PER_PAGE)]
        for chunk_i, chunk in enumerate(chunks):
            embed = discord.Embed(color=color)

            title_suffix = f"  ({chunk_i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
            embed.set_author(name=f"{emoji}  {cat_name}{title_suffix}", icon_url=bot_avatar)

            # Build clean command list
            cmd_lines = []
            for cmd_name, short in chunk:
                display = cmd_name
                if prefix and display.startswith(prefix):
                    display = display[len(prefix):]
                desc = short[:70] if short else "No description"
                cmd_lines.append(f"**`{display}`**\n╰ {desc}")

            embed.description = "\n\n".join(cmd_lines)

            embed.set_footer(text=f"Page {page_idx + 1} of {total_pages_estimate}  ·  {prefix}help <command> for details")
            pages.append(embed)
            page_idx += 1

    # Fix page counts now that we know the real total
    real_total = len(pages)
    for i, page in enumerate(pages):
        if page.footer and page.footer.text:
            old_footer = page.footer.text
            # Replace estimated page count with real one
            import re
            new_footer = re.sub(r"of \d+", f"of {real_total}", old_footer)
            new_footer = re.sub(r"Page \d+", f"Page {i + 1}", new_footer)
            page.set_footer(text=new_footer)

    return pages, select_options


def build_command_help_embed(
    ctx,
    data: Dict[str, Any],
    *,
    accent_color: int,
) -> discord.Embed:
    """Build a polished embed for a single command."""
    prefix = ctx.clean_prefix
    bot_avatar = ctx.bot.user.display_avatar.url if ctx.bot.user else None
    color = discord.Colour(accent_color)

    icon = "📁" if data["is_group"] else "🔹"
    embed = discord.Embed(color=color)
    embed.set_author(name=f"{icon}  {prefix}{data['name']}", icon_url=bot_avatar)

    # Syntax block
    embed.description = f"```yaml\n{data['signature']}\n```"

    # Description
    desc = data["description"]
    if len(desc) > 1024:
        desc = desc[:1021] + "…"
    embed.add_field(name="📝 Description", value=desc, inline=False)

    # Aliases
    if data["aliases"]:
        alias_parts = []
        for a in data["aliases"][:10]:
            # Build proper alias with parent chain
            name_parts = data["name"].split()
            if len(name_parts) > 1:
                alias_parts.append(f"`{prefix}{' '.join(name_parts[:-1])} {a}`")
            else:
                alias_parts.append(f"`{prefix}{a}`")
        embed.add_field(name="🔀 Aliases", value=" ".join(alias_parts), inline=True)

    # Cooldown
    if data["cooldown"]:
        embed.add_field(name="⏱️ Cooldown", value=data["cooldown"], inline=True)

    # Subcommands
    if data["subcommands"]:
        sub_lines = []
        for name, short in data["subcommands"]:
            display = name
            if prefix and display.startswith(prefix):
                display = display[len(prefix):]
            sub_lines.append(f"**`{display}`** · {short[:50]}")
        sub_text = "\n".join(sub_lines)
        if len(sub_text) > 1024:
            sub_text = sub_text[:1021] + "…"
        embed.add_field(name=f"📁 Subcommands ({len(data['subcommands'])})", value=sub_text, inline=False)

    embed.set_footer(text=f"<required>  [optional]  ·  {prefix}help for main menu")
    return embed


def build_cog_help_embed(
    ctx,
    cog_name: str,
    cog_doc: str,
    cmds: List[Tuple[str, str, str]],
    *,
    accent_color: int,
) -> discord.Embed:
    """Build a polished embed for a cog's help page."""
    prefix = ctx.clean_prefix
    bot_avatar = ctx.bot.user.display_avatar.url if ctx.bot.user else None
    color = discord.Colour(accent_color)

    embed = discord.Embed(color=color)
    embed.set_author(name=f"📂  {cog_name}", icon_url=bot_avatar)

    if cog_doc:
        embed.description = cog_doc[:2048]

    if cmds:
        cmd_lines = []
        for qname, sig, short in cmds:
            display = qname
            if prefix and display.startswith(prefix):
                display = display[len(prefix):]
            cmd_lines.append(f"**`{display}`** · {short[:60]}")
        cmd_text = "\n".join(cmd_lines)
        for i, chunk in enumerate(pagify(cmd_text, delims=["\n"], page_length=1024)):
            name = f"🔹 Commands ({len(cmds)})" if i == 0 else "ㅤ"
            embed.add_field(name=name, value=chunk, inline=False)

    embed.set_footer(text=f"{prefix}help <command> for details  ·  {prefix}help for main menu")
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
    prefix: str = "",
) -> ui.Container:
    """Build a polished CV2 container for a category."""
    container = ui.Container(accent_colour=discord.Colour(accent_color))
    container.add_item(ui.TextDisplay(f"### {emoji}  {category_name}"))
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    lines = []
    for cmd_name, cmd_short in commands_list:
        display = cmd_name
        if prefix and display.startswith(prefix):
            display = display[len(prefix):]
        short = cmd_short[:70] if cmd_short else "No description"
        lines.append(f"**`{display}`**\n╰ {short}")

    text = "\n\n".join(lines)
    for chunk in pagify(text, delims=["\n\n", "\n"], page_length=3900):
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
            nav_row.add_item(ui.Button(emoji="⏮", style=discord.ButtonStyle.secondary, custom_id="help_first", disabled=self.current_page == 0))
            nav_row.add_item(ui.Button(emoji="◀️", style=discord.ButtonStyle.primary, custom_id="help_prev", disabled=self.current_page == 0))
            nav_row.add_item(ui.Button(label=f"Page {self.current_page + 1} of {len(self.pages)}", style=discord.ButtonStyle.secondary, custom_id="help_page_ind", disabled=True))
            nav_row.add_item(ui.Button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="help_next", disabled=self.current_page >= len(self.pages) - 1))
            nav_row.add_item(ui.Button(emoji="⏭", style=discord.ButtonStyle.secondary, custom_id="help_last", disabled=self.current_page >= len(self.pages) - 1))
            self.add_item(nav_row)

            # Close in its own row
            close_row = ui.ActionRow()
            close_row.add_item(ui.Button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger, custom_id="help_close"))
            self.add_item(close_row)

            # Select in its own row (ActionRow can't mix buttons + selects)
            if self.category_options and len(self.category_options) > 1:
                select_row = ui.ActionRow()
                select_row.add_item(ui.Select(placeholder="⏩ Jump to category…", options=self.category_options[:25], custom_id="help_category_select"))
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
    """Build polished CV2 pages for the full bot help."""
    prefix = ctx.clean_prefix
    bot_name = bot.user.display_name if bot.user else "Bot"
    bot_avatar = bot.user.display_avatar.url if bot.user else None
    color = discord.Colour(accent_color)

    pages: List[List[Any]] = []
    select_options: List[discord.SelectOption] = []

    # ── Overview page ─────────────────────────────
    overview: List[Any] = []

    header = ui.Container(accent_colour=color)
    header_md = (
        f"## {bot_name} · Help Menu\n"
        f"**{total_commands}** commands across **{len(category_data)}** categories\n\n"
        f"▸ `{prefix}help <command>` — details on a command\n"
        f"▸ `{prefix}help <category>` — browse a category"
    )
    if bot_avatar:
        section = ui.Section(accessory=ui.Thumbnail(bot_avatar))
        section.add_item(ui.TextDisplay(header_md))
        header.add_item(section)
    else:
        header.add_item(ui.TextDisplay(header_md))
    overview.append(header)

    # Categories summary — cap how many to avoid component limits
    cats_to_show = category_data[:20]
    summary = ui.Container(accent_colour=color)
    summary.add_item(ui.TextDisplay("### 📚  Categories"))
    summary.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    summary_lines = []
    for i, (cat_name, emoji, cmds) in enumerate(cats_to_show):
        summary_lines.append(f"{emoji}  **{cat_name}** — {len(cmds)} command{'s' if len(cmds) != 1 else ''}")
        select_options.append(discord.SelectOption(
            label=cat_name[:100], value=str(i + 1),
            emoji=emoji if len(emoji) <= 2 else None,
            description=f"{len(cmds)} commands",
        ))
    if len(category_data) > 20:
        summary_lines.append(f"… *+{len(category_data) - 20} more categories*")
    summary.add_item(ui.TextDisplay("\n".join(summary_lines)))
    overview.append(summary)
    pages.append(overview)

    # ── Category pages ────────────────────────────
    for cat_name, emoji, cmds in category_data:
        chunks = [cmds[i:i + MAX_FIELDS_PER_PAGE] for i in range(0, len(cmds), MAX_FIELDS_PER_PAGE)]
        for chunk in chunks:
            pages.append([_make_category_container(cat_name, chunk, accent_color=accent_color, emoji=emoji, prefix=prefix)])

    return pages, select_options


def build_cv2_command_help(
    ctx,
    data: Dict[str, Any],
    *,
    accent_color: int,
) -> List[Any]:
    """Build polished CV2 components for a command."""
    prefix = ctx.clean_prefix
    color = discord.Colour(accent_color)
    container = ui.Container(accent_colour=color)

    icon = "📁" if data["is_group"] else "🔹"
    container.add_item(ui.TextDisplay(f"## {icon}  {prefix}{data['name']}"))
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    # Syntax
    container.add_item(ui.TextDisplay(f"```yaml\n{data['signature']}\n```"))

    # Description
    container.add_item(ui.TextDisplay(f"📝 **Description**\n{data['description'][:3800]}"))

    # Aliases
    if data["aliases"]:
        name_parts = data["name"].split()
        alias_parts = []
        for a in data["aliases"][:10]:
            if len(name_parts) > 1:
                alias_parts.append(f"`{prefix}{' '.join(name_parts[:-1])} {a}`")
            else:
                alias_parts.append(f"`{prefix}{a}`")
        container.add_item(ui.TextDisplay(f"🔀 **Aliases:** {' '.join(alias_parts)}"))

    # Cooldown
    if data["cooldown"]:
        container.add_item(ui.TextDisplay(f"⏱️ **Cooldown:** {data['cooldown']}"))

    # Subcommands
    if data["subcommands"]:
        container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        sub_lines = []
        for name, short in data["subcommands"]:
            display = name
            if prefix and display.startswith(prefix):
                display = display[len(prefix):]
            sub_lines.append(f"**`{display}`** · {short[:50]}")
        container.add_item(ui.TextDisplay(f"### 📁  Subcommands ({len(data['subcommands'])})\n\n" + "\n".join(sub_lines)))

    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    container.add_item(ui.TextDisplay(f"-# <required>  [optional]  ·  {prefix}help for main menu"))

    return [container]


def build_cv2_cog_help(
    ctx,
    cog_name: str,
    cog_doc: str,
    cmds: List[Tuple[str, str, str]],
    *,
    accent_color: int,
) -> List[Any]:
    """Build polished CV2 components for a cog."""
    prefix = ctx.clean_prefix
    color = discord.Colour(accent_color)

    header = ui.Container(accent_colour=color)
    header.add_item(ui.TextDisplay(f"## 📂  {cog_name}"))
    header.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
    if cog_doc:
        header.add_item(ui.TextDisplay(cog_doc[:3900]))
    components: List[Any] = [header]

    if cmds:
        cmd_list = [(qname, short) for qname, _, short in cmds]
        components.append(_make_category_container("Commands", cmd_list, accent_color=accent_color, emoji="🔹", prefix=prefix))

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
            nav_row.add_item(ui.Button(label=f"Page {self.current_page + 1} of {len(self.raw_pages)}", style=discord.ButtonStyle.secondary, custom_id="cv2menu_ind", disabled=True))
            nav_row.add_item(ui.Button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="cv2menu_next", disabled=self.current_page >= len(self.raw_pages) - 1))
            nav_row.add_item(ui.Button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger, custom_id="cv2menu_close"))
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
