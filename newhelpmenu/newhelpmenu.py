"""
New Help Menu v1.0.0 — The ultimate customisable help system for Red-DiscordBot.

Replaces the default help formatter with an interactive, button/select-menu
driven experience that server admins can fully tailor: layouts, custom
categories, per-category icons/colours/descriptions, button styles/labels,
embed themes, role-gated visibility, pagination, favourites, search, and more.

Every. Single. Aspect. Is. Customisable.
"""

from __future__ import annotations

import asyncio
import datetime
import math
from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import ButtonStyle, Interaction, SelectOption
from discord.ui import Button, Modal, Select, TextInput, View, button, select
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator
from redbot.core.utils.chat_formatting import humanize_list, pagify

_ = Translator("NewHelpMenu", __file__)

# ━━━━━━━━━━━━━━━━━━━━━━ DEFAULTS ━━━━━━━━━━━━━━━━━━━━━━

_GUILD_DEFAULTS: Dict[str, Any] = {
    # ── Global ──
    "enabled": True,
    "theme": "default",  # default | minimal | compact | dark | custom
    "accent_colour": None,
    "thumbnail": None,
    "footer_text": "Use the buttons below to navigate • {prefix}help <command> for details",
    "footer_icon": None,
    "title_text": "📖 {bot_name} Help",
    "description": "Welcome! Browse commands by category or search below.",
    "show_hidden": False,
    "show_aliases": True,
    "show_cooldown": True,
    "show_permissions": True,
    "show_signature": True,
    "dm_help": False,
    "ephemeral": False,
    "delete_after": 0,
    "timeout": 180,
    "max_commands_per_page": 8,
    "sort_commands": True,
    "sort_categories": True,
    "timestamp": True,
    # ── Layout ──
    "layout": "default",  # default | compact | two_column | list | minimal | detailed
    "home_layout": "list",  # list | grid | minimal
    "category_layout": "fields",  # fields | description | inline | numbered | table
    "command_separator": "\n",  # separator between commands in description layout
    "show_command_count": True,
    "category_columns": 1,  # 1 = full-width fields, 2 = inline fields (two_column), 3 = triple
    "show_category_banner": True,
    "compact_delimiter": " • ",
    # ── Navigation ──
    "use_select_menu": True,
    "use_buttons": True,
    "button_style": "primary",
    "page_button_style": "secondary",
    "nav_style": "full",  # full | compact | arrows_only | select_only
    "show_home_button": True,
    "show_close_button": True,
    "show_page_counter": True,
    # ── Button labels ──
    "btn_home_label": "Home",
    "btn_home_emoji": "🏠",
    "btn_prev_emoji": "◀️",
    "btn_next_emoji": "▶️",
    "btn_search_label": "Search",
    "btn_search_emoji": "🔍",
    "btn_fav_label": "Favourites",
    "btn_fav_emoji": "⭐",
    "btn_close_emoji": "✖️",
    # ── Home page ──
    "home_fields": [],
    "home_image": None,
    "tagline": "",
    # ── Categories ──
    "categories": {},
    "uncategorised_label": "🔧 Other",
    "uncategorised_description": "Commands not assigned to a category.",
    "uncategorised_emoji": "🔧",
    "hide_uncategorised": False,
    # ── Blacklists ──
    "hidden_cogs": [],
    "hidden_commands": [],
    # ── Favourites ──
    "allow_favourites": True,
    # ── Quick links ──
    "quick_links": [],
    # ── Search ──
    "search_enabled": True,
    "search_placeholder": "Type a command name or keyword…",
    # ── Embed author ──
    "show_author": False,
    "author_name": "{bot_name}",
    "author_icon": None,
    # ── Command detail ──
    "detail_show_parent": True,
    "detail_show_cog": True,
    "detail_show_full_help": True,
    # ── Reactions (legacy navigation) ──
    "reaction_nav": False,
}

_MEMBER_DEFAULTS: Dict[str, Any] = {
    "favourites": [],
}

_BSTYLE = {
    "primary": ButtonStyle.primary,
    "secondary": ButtonStyle.secondary,
    "success": ButtonStyle.success,
    "danger": ButtonStyle.danger,
    "blurple": ButtonStyle.primary,
    "grey": ButtonStyle.secondary,
    "gray": ButtonStyle.secondary,
    "green": ButtonStyle.success,
    "red": ButtonStyle.danger,
}

_THEMES: Dict[str, Dict[str, Any]] = {
    "default": {},
    "minimal": {
        "thumbnail": "",
        "footer_text": "{prefix}help <command>",
        "timestamp": False,
        "use_select_menu": False,
        "button_style": "secondary",
        "description": "",
        "layout": "minimal",
        "home_layout": "minimal",
        "category_layout": "description",
        "nav_style": "arrows_only",
        "show_author": False,
        "show_category_banner": False,
    },
    "compact": {
        "max_commands_per_page": 15,
        "show_signature": False,
        "show_cooldown": False,
        "show_permissions": False,
        "use_select_menu": False,
        "description": "",
        "layout": "compact",
        "category_layout": "table",
        "compact_delimiter": " · ",
        "nav_style": "compact",
    },
    "dark": {
        "accent_colour": 0x2F3136,
        "button_style": "secondary",
        "page_button_style": "secondary",
        "layout": "default",
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━ HELPERS ━━━━━━━━━━━━━━━━━━━━━━

def _style(name: str) -> ButtonStyle:
    return _BSTYLE.get(name, ButtonStyle.primary)


def _colour(val, ctx: commands.Context) -> discord.Colour:
    if val is not None:
        return discord.Colour(int(val))
    return ctx.me.colour if ctx.guild else discord.Colour.blurple()


def _fmt(template: str, ctx: commands.Context) -> str:
    if not template:
        return ""
    prefix = ctx.clean_prefix
    bot_name = ctx.me.display_name if ctx.guild else ctx.bot.user.display_name
    return template.format(prefix=prefix, bot_name=bot_name)


def _sig(cmd: commands.Command, show: bool) -> str:
    if not show:
        return f"`{cmd.qualified_name}`"
    sig = cmd.signature.strip()
    if sig:
        return f"`{cmd.qualified_name} {sig}`"
    return f"`{cmd.qualified_name}`"


def _trunc(text: str, n: int = 100) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


async def _visible_cmds(
    cmds, ctx: commands.Context, show_hidden: bool,
    hidden_commands: list, sort: bool,
) -> list:
    out = []
    for cmd in cmds:
        if cmd.qualified_name in hidden_commands:
            continue
        if cmd.hidden and not show_hidden:
            continue
        try:
            ok = await cmd.can_run(ctx)
        except Exception:
            ok = False
        if ok:
            out.append(cmd)
    if sort:
        out.sort(key=lambda c: c.qualified_name)
    return out


# ━━━━━━━━━━━━━━━━━━━━━━ EMBED LAYOUTS ━━━━━━━━━━━━━━━━━━━━━━

def _layout_fields(
    embed: discord.Embed, cmds: list, conf: dict, favourites: list, columns: int = 1
) -> discord.Embed:
    """Standard embed fields layout — one field per command."""
    inline = columns >= 2
    for cmd in cmds:
        name = _sig(cmd, conf.get("show_signature", True))
        parts = []
        brief = cmd.short_doc or "No description."
        parts.append(brief)
        if conf.get("show_aliases") and cmd.aliases:
            parts.append(f"**Aliases:** {humanize_list([f'`{a}`' for a in cmd.aliases])}")
        if conf.get("show_cooldown") and cmd.cooldown:
            parts.append(f"**Cooldown:** {cmd.cooldown.rate}/{cmd.cooldown.per:.0f}s")
        if conf.get("show_permissions") and hasattr(cmd, "requires") and cmd.requires.privilege_level:
            pl = cmd.requires.privilege_level
            if pl.name != "NONE":
                parts.append(f"**Requires:** {pl.name.replace('_', ' ').title()}")
        if isinstance(cmd, commands.Group):
            parts.append(f"*{len(cmd.commands)} subcommand(s)*")
        if cmd.qualified_name in favourites:
            parts.insert(0, "⭐")
        embed.add_field(name=name, value="\n".join(parts), inline=inline)
    # Pad for alignment when using columns
    if inline and len(cmds) % columns != 0:
        for _ in range(columns - (len(cmds) % columns)):
            embed.add_field(name="​", value="​", inline=True)
    return embed


def _layout_description(
    embed: discord.Embed, cmds: list, conf: dict, favourites: list
) -> discord.Embed:
    """All commands listed in the embed description."""
    sep = conf.get("command_separator", "\n")
    lines = []
    for cmd in cmds:
        fav = "⭐ " if cmd.qualified_name in favourites else ""
        sig = _sig(cmd, conf.get("show_signature", True))
        brief = cmd.short_doc or "No description."
        lines.append(f"{fav}{sig} — {brief}")
    desc = embed.description or ""
    embed.description = desc + "\n" + sep.join(lines)
    return embed


def _layout_inline(
    embed: discord.Embed, cmds: list, conf: dict, favourites: list
) -> discord.Embed:
    """Two-column: name | description."""
    for cmd in cmds:
        fav = "⭐ " if cmd.qualified_name in favourites else ""
        embed.add_field(
            name=f"{fav}`{cmd.qualified_name}`",
            value=cmd.short_doc or "No description.",
            inline=True,
        )
    if len(cmds) % 2 != 0:
        embed.add_field(name="​", value="​", inline=True)
    return embed


def _layout_numbered(
    embed: discord.Embed, cmds: list, conf: dict, favourites: list
) -> discord.Embed:
    """Numbered list in description."""
    lines = []
    for i, cmd in enumerate(cmds, 1):
        fav = "⭐ " if cmd.qualified_name in favourites else ""
        sig = _sig(cmd, conf.get("show_signature", True))
        brief = cmd.short_doc or "No description."
        lines.append(f"**{i}.** {fav}{sig}\n{brief}")
    desc = embed.description or ""
    embed.description = desc + "\n" + "\n".join(lines)
    return embed


def _layout_table(
    embed: discord.Embed, cmds: list, conf: dict, favourites: list
) -> discord.Embed:
    """Compact code-block table."""
    rows = []
    max_name = max((len(cmd.qualified_name) for cmd in cmds), default=10)
    max_name = min(max_name, 20)
    for cmd in cmds:
        name = cmd.qualified_name.ljust(max_name)[:max_name]
        brief = _trunc(cmd.short_doc or "No description.", 40)
        rows.append(f"{name}  {brief}")
    desc = embed.description or ""
    table = "```\n" + "\n".join(rows) + "\n```"
    embed.description = desc + "\n" + table
    return embed


_CATEGORY_LAYOUTS = {
    "fields": _layout_fields,
    "description": _layout_description,
    "inline": _layout_inline,
    "numbered": _layout_numbered,
    "table": _layout_table,
}


# ━━━━━━━━━━━━━━━━━━━━━━ VIEWS ━━━━━━━━━━━━━━━━━━━━━━

class HelpView(View):
    """Main interactive help view."""

    def __init__(
        self, cog: "NewHelpMenu", ctx: commands.Context,
        conf: dict, categories: dict, all_cmds: dict,
        *, favourites: list,
    ):
        super().__init__(timeout=conf.get("timeout", 180))
        self.cog = cog
        self.ctx = ctx
        self.conf = conf
        self.categories = categories
        self.all_cmds = all_cmds
        self.favourites = favourites
        self.page: str = "__home__"
        self.idx: int = 0
        self.message: Optional[discord.Message] = None
        self._build()

    @property
    def _pages(self) -> int:
        if self.page in ("__home__", "__favourites__", "__search__"):
            return 1
        per = self.conf.get("max_commands_per_page", 8)
        return max(1, math.ceil(len(self.all_cmds.get(self.page, [])) / per))

    # ── Build UI ──

    def _build(self):
        self.clear_items()
        c = self.conf
        nav = c.get("nav_style", "full")

        # Row 0: Select menu
        if c.get("use_select_menu") and nav not in ("arrows_only",) and self.categories:
            opts = [SelectOption(label="🏠 Home", value="__home__", default=self.page == "__home__")]
            for cn, cd in self.categories.items():
                lbl = cd.get("label", cn)[:25]
                desc = _trunc(cd.get("description", ""), 50) or None
                o = SelectOption(label=lbl, value=cn, description=desc, default=self.page == cn)
                if cd.get("emoji"):
                    try:
                        o.emoji = cd["emoji"]
                    except Exception:
                        pass
                opts.append(o)
            if c.get("allow_favourites") and self.favourites:
                opts.append(SelectOption(label="⭐ Favourites", value="__favourites__", default=self.page == "__favourites__"))
            self.add_item(_CatSelect(opts[:25]))

        # Row 1: Category buttons (when no select)
        if c.get("use_buttons") and not c.get("use_select_menu"):
            style = _style(c.get("button_style", "primary"))
            if c.get("show_home_button", True):
                b = Button(style=ButtonStyle.secondary, label=c.get("btn_home_label", "Home"),
                           emoji=c.get("btn_home_emoji", "🏠"), custom_id="nhm_home", row=0)
                b.callback = self._go_home
                self.add_item(b)
            for i, (cn, cd) in enumerate(self.categories.items()):
                if i >= 4:
                    break
                b = Button(style=style, label=cd.get("label", cn)[:20],
                           emoji=cd.get("emoji") or None, custom_id=f"nhm_c_{cn}", row=0)
                b.callback = self._mk_cat(cn)
                self.add_item(b)

        # Row 2: Pagination
        ps = _style(c.get("page_button_style", "secondary"))
        total = self._pages

        if nav != "select_only":
            pb = Button(style=ps, emoji=c.get("btn_prev_emoji", "◀️"),
                        custom_id="nhm_prev", disabled=self.idx <= 0, row=2)
            pb.callback = self._prev
            self.add_item(pb)

            if c.get("show_page_counter", True):
                self.add_item(Button(style=ButtonStyle.secondary, label=f"{self.idx+1}/{total}",
                                     custom_id="nhm_pg", disabled=True, row=2))

            nb = Button(style=ps, emoji=c.get("btn_next_emoji", "▶️"),
                        custom_id="nhm_next", disabled=self.idx >= total - 1, row=2)
            nb.callback = self._next
            self.add_item(nb)

        # Row 3: Utilities
        if c.get("search_enabled"):
            sb = Button(style=ButtonStyle.secondary, emoji=c.get("btn_search_emoji", "🔍"),
                        label=c.get("btn_search_label", "Search"), custom_id="nhm_srch", row=3)
            sb.callback = self._search
            self.add_item(sb)
        if c.get("allow_favourites"):
            fb = Button(style=ButtonStyle.secondary, emoji=c.get("btn_fav_emoji", "⭐"),
                        label=c.get("btn_fav_label", "Favourites"), custom_id="nhm_fav", row=3)
            fb.callback = self._favs
            self.add_item(fb)
        if c.get("show_close_button", True):
            cb = Button(style=ButtonStyle.danger, emoji=c.get("btn_close_emoji", "✖️"),
                        custom_id="nhm_cls", row=3)
            cb.callback = self._close
            self.add_item(cb)

        # Row 4: Quick links
        for ql in (c.get("quick_links") or [])[:3]:
            self.add_item(Button(style=ButtonStyle.link, label=ql.get("label", "Link")[:40],
                                 url=ql.get("url", "https://discord.com"),
                                 emoji=ql.get("emoji") or None, row=4))

    # ── Embeds ──

    def _base(self, *, title=None, colour=None) -> discord.Embed:
        c = self.conf
        col = colour if colour is not None else _colour(c.get("accent_colour"), self.ctx).value
        e = discord.Embed(colour=discord.Colour(col))
        if title:
            e.title = title
        if c.get("timestamp"):
            e.timestamp = datetime.datetime.now(datetime.timezone.utc)
        ft = _fmt(c.get("footer_text", ""), self.ctx)
        fi = c.get("footer_icon")
        if ft:
            e.set_footer(text=ft, icon_url=fi or discord.Embed.Empty)
        if c.get("show_author"):
            an = _fmt(c.get("author_name", "{bot_name}"), self.ctx)
            ai = c.get("author_icon") or (self.ctx.me.display_avatar.url if self.ctx.me.display_avatar else None)
            e.set_author(name=an, icon_url=ai or discord.Embed.Empty)
        return e

    def _home_embed(self) -> discord.Embed:
        c = self.conf
        e = self._base(title=_fmt(c.get("title_text", "Help"), self.ctx))
        parts = []
        if c.get("tagline"):
            parts.append(f"*{c['tagline']}*\n")
        if c.get("description"):
            parts.append(_fmt(c["description"], self.ctx))

        hl = c.get("home_layout", "list")
        parts.append("")
        for cn, cd in self.categories.items():
            emoji = cd.get("emoji", "📁")
            label = cd.get("label", cn)
            desc = cd.get("description", "")
            count = len(self.all_cmds.get(cn, []))
            cnt = f" `({count})`" if c.get("show_command_count", True) else ""

            if hl == "grid":
                parts.append(f"{emoji} **{label}**{cnt}")
            elif hl == "minimal":
                parts.append(f"`{label}`{cnt}")
            else:  # list
                if desc:
                    parts.append(f"{emoji} **{label}** — {desc}{cnt}")
                else:
                    parts.append(f"{emoji} **{label}**{cnt}")

        e.description = "\n".join(parts)

        thumb = c.get("thumbnail")
        if thumb:
            e.set_thumbnail(url=thumb)
        elif thumb is None and self.ctx.me.display_avatar:
            e.set_thumbnail(url=self.ctx.me.display_avatar.url)

        if c.get("home_image"):
            e.set_image(url=c["home_image"])

        for f in c.get("home_fields", []):
            e.add_field(name=f.get("name", "​"), value=f.get("value", "​"), inline=f.get("inline", False))
        return e

    def _cat_embed(self, cat: str) -> discord.Embed:
        cd = self.categories.get(cat, {})
        c = self.conf
        col = cd.get("colour") or c.get("accent_colour")
        emoji = cd.get("emoji", "📁")
        label = cd.get("label", cat)
        e = self._base(title=f"{emoji} {label}" if c.get("show_category_banner", True) else label,
                       colour=_colour(col, self.ctx).value)
        if cd.get("description"):
            e.description = cd["description"] + "\n"
        else:
            e.description = ""
        if cd.get("thumbnail"):
            e.set_thumbnail(url=cd["thumbnail"])
        if cd.get("image"):
            e.set_image(url=cd["image"])

        cmds = self.all_cmds.get(cat, [])
        per = c.get("max_commands_per_page", 8)
        page_cmds = cmds[self.idx * per: (self.idx + 1) * per]

        layout_name = c.get("category_layout", "fields")
        layout_fn = _CATEGORY_LAYOUTS.get(layout_name, _layout_fields)
        if layout_fn == _layout_fields:
            cols = c.get("category_columns", 1)
            _layout_fields(e, page_cmds, c, self.favourites, cols)
        else:
            layout_fn(e, page_cmds, c, self.favourites)

        total = self._pages
        if total > 1:
            e.description = (e.description or "") + f"\n*Page {self.idx + 1}/{total}*"
        return e

    def _favs_embed(self) -> discord.Embed:
        e = self._base(title="⭐ Your Favourite Commands")
        if not self.favourites:
            e.description = "No favourites yet! Use ⭐ on a command to add one."
            return e
        lines = []
        for qn in self.favourites:
            cmd = self.ctx.bot.get_command(qn)
            if cmd:
                lines.append(f"{_sig(cmd, self.conf.get('show_signature', True))} — {cmd.short_doc or 'No description.'}")
            else:
                lines.append(f"`{qn}` — *not found*")
        e.description = "\n\n".join(lines[:20])
        return e

    def _search_embed(self, query: str, results: list) -> discord.Embed:
        e = self._base(title=f"🔍 Search: \"{query}\"")
        if not results:
            e.description = "No commands found."
            return e
        lines = []
        for cmd in results[:15]:
            cat = next((cn for cn, cl in self.all_cmds.items() if cmd in cl), "Other")
            lines.append(f"{_sig(cmd, self.conf.get('show_signature', True))} — *{cat}*\n{cmd.short_doc or 'No description.'}")
        e.description = "\n\n".join(lines)
        e.set_footer(text=f"{len(results)} result(s)")
        return e

    def embed(self) -> discord.Embed:
        if self.page == "__home__":
            return self._home_embed()
        elif self.page == "__favourites__":
            return self._favs_embed()
        else:
            return self._cat_embed(self.page)

    def detail_embed(self, cmd: commands.Command) -> discord.Embed:
        c = self.conf
        e = self._base(title=f"📄 {cmd.qualified_name}")
        parts = [f"```\n{self.ctx.clean_prefix}{cmd.qualified_name} {cmd.signature}\n```"]
        if c.get("detail_show_full_help"):
            parts.append(cmd.help or cmd.short_doc or "No description.")
        else:
            parts.append(cmd.short_doc or "No description.")
        if c.get("show_aliases") and cmd.aliases:
            parts.append(f"\n**Aliases:** {humanize_list([f'`{a}`' for a in cmd.aliases])}")
        if c.get("show_cooldown") and cmd.cooldown:
            parts.append(f"**Cooldown:** {cmd.cooldown.rate}/{cmd.cooldown.per:.0f}s ({cmd.cooldown.type.name})")
        if c.get("show_permissions") and hasattr(cmd, "requires") and cmd.requires.privilege_level:
            pl = cmd.requires.privilege_level
            if pl.name != "NONE":
                parts.append(f"**Required Level:** {pl.name.replace('_', ' ').title()}")
        if isinstance(cmd, commands.Group):
            subs = sorted(cmd.commands, key=lambda x: x.name)
            sub_lines = [f"`{s.qualified_name}` — {s.short_doc or 'No description.'}" for s in subs[:20]]
            parts.append(f"\n**Subcommands ({len(cmd.commands)}):**\n" + "\n".join(sub_lines))
        if c.get("detail_show_parent") and cmd.parent:
            parts.append(f"\n**Parent:** `{cmd.parent.qualified_name}`")
        if c.get("detail_show_cog") and cmd.cog:
            parts.append(f"**Cog:** {cmd.cog.qualified_name}")
        if cmd.qualified_name in self.favourites:
            parts.append("\n⭐ *In your favourites*")
        e.description = "\n".join(parts)
        return e

    # ── Callbacks ──

    async def _go_home(self, i: Interaction):
        self.page, self.idx = "__home__", 0
        self._build()
        await i.response.edit_message(embed=self.embed(), view=self)

    def _mk_cat(self, name):
        async def cb(i: Interaction):
            self.page, self.idx = name, 0
            self._build()
            await i.response.edit_message(embed=self.embed(), view=self)
        return cb

    async def _prev(self, i: Interaction):
        if self.idx > 0:
            self.idx -= 1
        self._build()
        await i.response.edit_message(embed=self.embed(), view=self)

    async def _next(self, i: Interaction):
        if self.idx < self._pages - 1:
            self.idx += 1
        self._build()
        await i.response.edit_message(embed=self.embed(), view=self)

    async def _search(self, i: Interaction):
        await i.response.send_modal(_SearchModal(self))

    async def _favs(self, i: Interaction):
        self.page, self.idx = "__favourites__", 0
        self._build()
        await i.response.edit_message(embed=self.embed(), view=self)

    async def _close(self, i: Interaction):
        await i.response.edit_message(view=None)
        self.stop()

    async def interaction_check(self, i: Interaction) -> bool:
        if i.user.id != self.ctx.author.id:
            await i.response.send_message("Run the help command yourself!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass


class _CatSelect(Select):
    def __init__(self, opts):
        super().__init__(placeholder="Select a category…", options=opts, custom_id="nhm_sel", row=1)

    async def callback(self, i: Interaction):
        v: HelpView = self.view
        val = self.values[0]
        v.page = val if val != "__home__" else "__home__"
        if val == "__favourites__":
            v.page = "__favourites__"
        v.idx = 0
        v._build()
        await i.response.edit_message(embed=v.embed(), view=v)


class _SearchModal(Modal):
    query = TextInput(label="Search commands", placeholder="Type a command name or keyword…", max_length=100)

    def __init__(self, hv: HelpView):
        super().__init__(title="🔍 Search Commands")
        self.hv = hv
        self.query.placeholder = hv.conf.get("search_placeholder", "Type a command name or keyword…")

    async def on_submit(self, i: Interaction):
        q = self.query.value.lower().strip()
        seen, results = set(), []
        for cl in self.hv.all_cmds.values():
            for cmd in cl:
                if cmd.qualified_name in seen:
                    continue
                if (q in cmd.qualified_name.lower() or q in (cmd.short_doc or "").lower()
                        or q in (cmd.help or "").lower() or any(q in a.lower() for a in cmd.aliases)):
                    seen.add(cmd.qualified_name)
                    results.append(cmd)
        self.hv.page = "__search__"
        self.hv._build()
        await i.response.edit_message(embed=self.hv._search_embed(self.query.value, results), view=self.hv)


class _DetailView(View):
    def __init__(self, hv: HelpView, cmd: commands.Command):
        super().__init__(timeout=120)
        self.hv, self.cmd = hv, cmd
        self._build()

    def _build(self):
        self.clear_items()
        b = Button(style=ButtonStyle.secondary, label="← Back", emoji="🏠", custom_id="d_back", row=0)
        b.callback = self._back
        self.add_item(b)

        is_fav = self.cmd.qualified_name in self.hv.favourites
        f = Button(style=ButtonStyle.success if is_fav else ButtonStyle.secondary,
                   label="Unfavourite" if is_fav else "Favourite", emoji="⭐", custom_id="d_fav", row=0)
        f.callback = self._fav
        self.add_item(f)

        if isinstance(self.cmd, commands.Group) and self.cmd.commands:
            s = Button(style=ButtonStyle.primary, label=f"Subcommands ({len(self.cmd.commands)})",
                       emoji="📂", custom_id="d_sub", row=0)
            s.callback = self._subs
            self.add_item(s)

    async def _back(self, i: Interaction):
        self.hv._build()
        await i.response.edit_message(embed=self.hv.embed(), view=self.hv)
        self.stop()

    async def _fav(self, i: Interaction):
        qn = self.cmd.qualified_name
        if qn in self.hv.favourites:
            self.hv.favourites.remove(qn)
        else:
            self.hv.favourites.append(qn)
        if i.guild:
            async with self.hv.cog.config.member_from_ids(i.guild.id, i.user.id).favourites() as fv:
                fv.clear()
                fv.extend(self.hv.favourites)
        self._build()
        await i.response.edit_message(embed=self.hv.detail_embed(self.cmd), view=self)

    async def _subs(self, i: Interaction):
        e = self.hv._base(title=f"📂 {self.cmd.qualified_name} — Subcommands")
        subs = sorted(self.cmd.commands, key=lambda c: c.name)
        e.description = "\n\n".join(
            f"{_sig(c, True)}\n{c.short_doc or 'No description.'}" for c in subs[:20]
        ) or "None."
        await i.response.edit_message(embed=e, view=self)

    async def interaction_check(self, i: Interaction) -> bool:
        if i.user.id != self.hv.ctx.author.id:
            await i.response.send_message("Not your help menu!", ephemeral=True)
            return False
        return True


# ━━━━━━━━━━━━━━━━━━━━━━ FORMATTER ━━━━━━━━━━━━━━━━━━━━━━

class _Formatter(commands.help.RedHelpFormatter):
    def __init__(self, cog: "NewHelpMenu"):
        self.cog = cog

    async def format_bot_help(self, ctx, mapping, **kw):
        await self.cog._send_help(ctx)

    async def format_cog_help(self, ctx, obj, **kw):
        await self.cog._send_help(ctx, focus_cog=obj.qualified_name)

    async def format_command_help(self, ctx, obj, **kw):
        await self.cog._send_cmd_help(ctx, obj)


# ━━━━━━━━━━━━━━━━━━━━━━━ COG ━━━━━━━━━━━━━━━━━━━━━━━━

class NewHelpMenu(commands.Cog):
    """Fully customisable interactive help menu with categories, buttons, select menus,
    layouts, themes, search, favourites, and total configurability over every visual element."""

    __version__ = "1.0.0"
    __author__ = "everestmcarthur"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1_987_654_321, force_registration=True)
        self.config.register_guild(**_GUILD_DEFAULTS)
        self.config.register_member(**_MEMBER_DEFAULTS)
        self._old_fmt = None

    async def cog_load(self):
        self._old_fmt = self.bot._help_formatter
        self.bot._help_formatter = _Formatter(self)

    async def cog_unload(self):
        if self._old_fmt:
            self.bot._help_formatter = self._old_fmt

    # ── Config helpers ──

    async def _conf(self, guild) -> dict:
        if guild is None:
            return deepcopy(_GUILD_DEFAULTS)
        raw = await self.config.guild(guild).all()
        theme = raw.get("theme", "default")
        if theme in _THEMES and theme != "custom":
            m = deepcopy(raw)
            for k, v in _THEMES[theme].items():
                if m.get(k) is None or m.get(k) == _GUILD_DEFAULTS.get(k):
                    m[k] = v
            return m
        return raw

    async def _cats(self, ctx, conf, *, focus_cog=None):
        custom = conf.get("categories", {})
        hcogs = conf.get("hidden_cogs", [])
        hcmds = conf.get("hidden_commands", [])
        sh = conf.get("show_hidden", False)
        sc = conf.get("sort_commands", True)
        scat = conf.get("sort_categories", True)

        cog2cat = {}
        for cn, cd in custom.items():
            for cg in cd.get("cogs", []):
                cog2cat[cg] = cn

        cats: Dict[str, dict] = {}
        all_c: Dict[str, list] = defaultdict(list)

        for cname, cobj in self.bot.cogs.items():
            if cname in hcogs or (focus_cog and cname != focus_cog):
                continue
            top = await _visible_cmds(list(cobj.get_commands()), ctx, sh, hcmds, sc)
            if not top:
                continue
            cat = cog2cat.get(cname)
            if cat and cat in custom:
                if cat not in cats:
                    cats[cat] = deepcopy(custom[cat])
                all_c[cat].extend(top)
            else:
                if cname not in cats:
                    doc = ((cobj.__doc__ or "").strip().split("\n")[0]) if cobj.__doc__ else ""
                    cats[cname] = {"label": cname, "emoji": None, "description": _trunc(doc, 80),
                                   "colour": None, "thumbnail": None, "image": None,
                                   "cogs": [cname], "order": 999, "hidden": False, "required_role": None}
                all_c[cname].extend(top)

        # no-cog commands
        nc = await _visible_cmds([c for c in self.bot.commands if c.cog is None], ctx, sh, hcmds, sc)
        if nc and not conf.get("hide_uncategorised"):
            lbl = conf.get("uncategorised_label", "🔧 Other")
            cats[lbl] = {"label": lbl, "emoji": conf.get("uncategorised_emoji", "🔧"),
                         "description": conf.get("uncategorised_description", ""),
                         "colour": None, "thumbnail": None, "image": None, "cogs": [],
                         "order": 9999, "hidden": False, "required_role": None}
            all_c[lbl] = nc

        # Role filter
        if ctx.guild and hasattr(ctx.author, "roles"):
            rids = {r.id for r in ctx.author.roles}
            rm = [cn for cn, cd in cats.items() if (cd.get("required_role") and cd["required_role"] not in rids) or cd.get("hidden")]
            for r in rm:
                cats.pop(r, None)
                all_c.pop(r, None)

        if scat:
            cats = dict(sorted(cats.items(), key=lambda kv: (kv[1].get("order", 999), kv[0])))
        return cats, dict(all_c)

    # ── Send ──

    async def _send_help(self, ctx, *, focus_cog=None):
        conf = await self._conf(ctx.guild)
        if not conf.get("enabled"):
            if self._old_fmt:
                return await self._old_fmt.format_bot_help(ctx, {})
            return
        cats, ac = await self._cats(ctx, conf, focus_cog=focus_cog)
        favs = (await self.config.member(ctx.author).favourites()) if ctx.guild and conf.get("allow_favourites") else []
        view = HelpView(self, ctx, conf, cats, ac, favourites=favs)
        kw = {"embed": view.embed(), "view": view}
        if conf.get("ephemeral") and ctx.interaction:
            kw["ephemeral"] = True
        if conf.get("dm_help") and ctx.guild:
            try:
                msg = await ctx.author.send(**kw)
                view.message = msg
                await ctx.send("📬 Help sent to your DMs!", delete_after=5)
            except discord.Forbidden:
                msg = await ctx.send(**kw)
                view.message = msg
        else:
            msg = await ctx.send(**kw)
            view.message = msg
        if conf.get("delete_after", 0) > 0:
            await asyncio.sleep(conf["delete_after"])
            try:
                await msg.delete()
            except Exception:
                pass

    async def _send_cmd_help(self, ctx, cmd):
        conf = await self._conf(ctx.guild)
        if not conf.get("enabled"):
            if self._old_fmt:
                return await self._old_fmt.format_command_help(ctx, cmd)
            return
        cats, ac = await self._cats(ctx, conf)
        favs = (await self.config.member(ctx.author).favourites()) if ctx.guild and conf.get("allow_favourites") else []
        hv = HelpView(self, ctx, conf, cats, ac, favourites=favs)
        dv = _DetailView(hv, cmd)
        kw = {"embed": hv.detail_embed(cmd), "view": dv}
        if conf.get("ephemeral") and ctx.interaction:
            kw["ephemeral"] = True
        msg = await ctx.send(**kw)
        hv.message = msg

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  ADMIN COMMANDS — helpmenu / hm
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @commands.group(name="helpmenu", aliases=["hm"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def helpmenu(self, ctx):
        """Configure the New Help Menu system."""

    @helpmenu.command(name="toggle")
    async def hm_toggle(self, ctx):
        """Enable or disable the custom help menu."""
        cur = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not cur)
        await ctx.send(f"✅ Custom help menu **{'enabled' if not cur else 'disabled'}**.")

    @helpmenu.command(name="theme")
    async def hm_theme(self, ctx, theme: str):
        """Set theme: `default`, `minimal`, `compact`, `dark`, `custom`."""
        t = theme.lower()
        if t not in ("default", "minimal", "compact", "dark", "custom"):
            return await ctx.send("Invalid. Choose: `default`, `minimal`, `compact`, `dark`, `custom`.")
        await self.config.guild(ctx.guild).theme.set(t)
        await ctx.send(f"✅ Theme → **{t}**.")

    @helpmenu.command(name="layout")
    async def hm_layout(self, ctx, layout: str):
        """Set overall layout: `default`, `compact`, `two_column`, `list`, `minimal`, `detailed`."""
        l = layout.lower()
        if l not in ("default", "compact", "two_column", "list", "minimal", "detailed"):
            return await ctx.send("Invalid. Choose: `default`, `compact`, `two_column`, `list`, `minimal`, `detailed`.")
        await self.config.guild(ctx.guild).layout.set(l)
        # Auto-adjust category layout
        mapping = {"two_column": "inline", "compact": "table", "minimal": "description", "detailed": "fields"}
        if l in mapping:
            await self.config.guild(ctx.guild).category_layout.set(mapping[l])
            if l == "two_column":
                await self.config.guild(ctx.guild).category_columns.set(2)
        await ctx.send(f"✅ Layout → **{l}**.")

    @helpmenu.command(name="catlayout")
    async def hm_catlayout(self, ctx, layout: str):
        """Set category page layout: `fields`, `description`, `inline`, `numbered`, `table`."""
        l = layout.lower()
        if l not in _CATEGORY_LAYOUTS:
            return await ctx.send(f"Invalid. Choose: {humanize_list(list(_CATEGORY_LAYOUTS.keys()))}")
        await self.config.guild(ctx.guild).category_layout.set(l)
        await ctx.send(f"✅ Category layout → **{l}**.")

    @helpmenu.command(name="homelayout")
    async def hm_homelayout(self, ctx, layout: str):
        """Set home page layout: `list`, `grid`, `minimal`."""
        l = layout.lower()
        if l not in ("list", "grid", "minimal"):
            return await ctx.send("Invalid. Choose: `list`, `grid`, `minimal`.")
        await self.config.guild(ctx.guild).home_layout.set(l)
        await ctx.send(f"✅ Home layout → **{l}**.")

    @helpmenu.command(name="columns")
    async def hm_columns(self, ctx, columns: int):
        """Set number of columns for field layout (1-3)."""
        if columns not in (1, 2, 3):
            return await ctx.send("Choose 1, 2, or 3.")
        await self.config.guild(ctx.guild).category_columns.set(columns)
        await ctx.send(f"✅ Columns → **{columns}**.")

    @helpmenu.command(name="navstyle")
    async def hm_navstyle(self, ctx, style: str):
        """Set navigation style: `full`, `compact`, `arrows_only`, `select_only`."""
        s = style.lower()
        if s not in ("full", "compact", "arrows_only", "select_only"):
            return await ctx.send("Invalid. Choose: `full`, `compact`, `arrows_only`, `select_only`.")
        await self.config.guild(ctx.guild).nav_style.set(s)
        await ctx.send(f"✅ Nav style → **{s}**.")

    @helpmenu.command(name="colour", aliases=["color"])
    async def hm_colour(self, ctx, colour: discord.Colour):
        """Set the accent colour."""
        await self.config.guild(ctx.guild).accent_colour.set(colour.value)
        await ctx.send(f"✅ Colour → **{colour}**.")

    @helpmenu.command(name="resetcolour", aliases=["resetcolor"])
    async def hm_resetcolour(self, ctx):
        """Reset accent colour."""
        await self.config.guild(ctx.guild).accent_colour.set(None)
        await ctx.send("✅ Colour reset.")

    @helpmenu.command(name="thumbnail", aliases=["thumb"])
    async def hm_thumb(self, ctx, url: Optional[str] = None):
        """Set/reset home thumbnail."""
        await self.config.guild(ctx.guild).thumbnail.set(url)
        await ctx.send(f"✅ Thumbnail {'set' if url else 'reset'}.")

    @helpmenu.command(name="title")
    async def hm_title(self, ctx, *, title: str):
        """Set title. Placeholders: `{bot_name}`, `{prefix}`."""
        await self.config.guild(ctx.guild).title_text.set(title)
        await ctx.send(f"✅ Title → {title}")

    @helpmenu.command(name="description", aliases=["desc"])
    async def hm_desc(self, ctx, *, text: str):
        """Set home description."""
        await self.config.guild(ctx.guild).description.set(text)
        await ctx.send("✅ Description updated.")

    @helpmenu.command(name="footer")
    async def hm_footer(self, ctx, *, text: str):
        """Set footer text."""
        await self.config.guild(ctx.guild).footer_text.set(text)
        await ctx.send("✅ Footer updated.")

    @helpmenu.command(name="footericon")
    async def hm_footericon(self, ctx, url: Optional[str] = None):
        """Set footer icon URL."""
        await self.config.guild(ctx.guild).footer_icon.set(url)
        await ctx.send(f"✅ Footer icon {'set' if url else 'reset'}.")

    @helpmenu.command(name="tagline")
    async def hm_tagline(self, ctx, *, text: str = ""):
        """Set/clear tagline above description."""
        await self.config.guild(ctx.guild).tagline.set(text)
        await ctx.send(f"✅ Tagline {'set' if text else 'cleared'}.")

    @helpmenu.command(name="homeimage")
    async def hm_homeimg(self, ctx, url: Optional[str] = None):
        """Set/reset home image."""
        await self.config.guild(ctx.guild).home_image.set(url)
        await ctx.send(f"✅ Home image {'set' if url else 'reset'}.")

    @helpmenu.command(name="author")
    async def hm_author(self, ctx, toggle: str):
        """Toggle embed author line: `on` / `off`."""
        on = toggle.lower() in ("on", "true", "yes", "1")
        await self.config.guild(ctx.guild).show_author.set(on)
        await ctx.send(f"✅ Author → **{'on' if on else 'off'}**.")

    @helpmenu.command(name="authorname")
    async def hm_authname(self, ctx, *, name: str):
        """Set author name. Placeholder: `{bot_name}`."""
        await self.config.guild(ctx.guild).author_name.set(name)
        await ctx.send(f"✅ Author name → {name}")

    @helpmenu.command(name="authoricon")
    async def hm_authicon(self, ctx, url: Optional[str] = None):
        """Set author icon URL."""
        await self.config.guild(ctx.guild).author_icon.set(url)
        await ctx.send(f"✅ Author icon {'set' if url else 'reset'}.")

    @helpmenu.command(name="separator")
    async def hm_sep(self, ctx, *, sep: str):
        """Set command separator for description layout. Use `\\n` for newline."""
        sep = sep.replace("\\n", "\n")
        await self.config.guild(ctx.guild).command_separator.set(sep)
        await ctx.send("✅ Separator set.")

    @helpmenu.command(name="searchplaceholder")
    async def hm_sph(self, ctx, *, text: str):
        """Set search modal placeholder text."""
        await self.config.guild(ctx.guild).search_placeholder.set(text)
        await ctx.send("✅ Placeholder set.")

    # ── Button customisation ──

    @helpmenu.group(name="button", aliases=["btn"])
    async def hm_btn(self, ctx):
        """Customise button labels, emojis, and styles."""

    @hm_btn.command(name="style")
    async def btn_style(self, ctx, style: str):
        """Set category button style: primary, secondary, success, danger."""
        s = style.lower()
        if s not in _BSTYLE:
            return await ctx.send(f"Invalid. Choose: {humanize_list(list(_BSTYLE.keys()))}")
        await self.config.guild(ctx.guild).button_style.set(s)
        await ctx.send(f"✅ Button style → **{s}**.")

    @hm_btn.command(name="pagestyle")
    async def btn_pagestyle(self, ctx, style: str):
        """Set pagination button style."""
        s = style.lower()
        if s not in _BSTYLE:
            return await ctx.send(f"Invalid. Choose: {humanize_list(list(_BSTYLE.keys()))}")
        await self.config.guild(ctx.guild).page_button_style.set(s)
        await ctx.send(f"✅ Page button style → **{s}**.")

    @hm_btn.command(name="homelabel")
    async def btn_hlabel(self, ctx, *, label: str):
        """Set home button label."""
        await self.config.guild(ctx.guild).btn_home_label.set(label)
        await ctx.send(f"✅ Home label → {label}")

    @hm_btn.command(name="homeemoji")
    async def btn_hemoji(self, ctx, emoji: str):
        """Set home button emoji."""
        await self.config.guild(ctx.guild).btn_home_emoji.set(emoji)
        await ctx.send(f"✅ Home emoji → {emoji}")

    @hm_btn.command(name="prevemoji")
    async def btn_pemoji(self, ctx, emoji: str):
        """Set previous page button emoji."""
        await self.config.guild(ctx.guild).btn_prev_emoji.set(emoji)
        await ctx.send(f"✅ Prev emoji → {emoji}")

    @hm_btn.command(name="nextemoji")
    async def btn_nemoji(self, ctx, emoji: str):
        """Set next page button emoji."""
        await self.config.guild(ctx.guild).btn_next_emoji.set(emoji)
        await ctx.send(f"✅ Next emoji → {emoji}")

    @hm_btn.command(name="searchlabel")
    async def btn_slabel(self, ctx, *, label: str):
        """Set search button label."""
        await self.config.guild(ctx.guild).btn_search_label.set(label)
        await ctx.send(f"✅ Search label → {label}")

    @hm_btn.command(name="searchemoji")
    async def btn_semoji(self, ctx, emoji: str):
        """Set search button emoji."""
        await self.config.guild(ctx.guild).btn_search_emoji.set(emoji)
        await ctx.send(f"✅ Search emoji → {emoji}")

    @hm_btn.command(name="favlabel")
    async def btn_flabel(self, ctx, *, label: str):
        """Set favourites button label."""
        await self.config.guild(ctx.guild).btn_fav_label.set(label)
        await ctx.send(f"✅ Fav label → {label}")

    @hm_btn.command(name="favemoji")
    async def btn_femoji(self, ctx, emoji: str):
        """Set favourites button emoji."""
        await self.config.guild(ctx.guild).btn_fav_emoji.set(emoji)
        await ctx.send(f"✅ Fav emoji → {emoji}")

    @hm_btn.command(name="closeemoji")
    async def btn_cemoji(self, ctx, emoji: str):
        """Set close button emoji."""
        await self.config.guild(ctx.guild).btn_close_emoji.set(emoji)
        await ctx.send(f"✅ Close emoji → {emoji}")

    # ── Toggle settings ──

    @helpmenu.command(name="set")
    async def hm_set(self, ctx, setting: str, value: str):
        """Toggle a setting on/off, or set a number.

        Toggles: `aliases`, `cooldown`, `permissions`, `signature`, `hidden`,
        `timestamp`, `selectmenu`, `buttons`, `dmhelp`, `ephemeral`,
        `favourites`, `search`, `sortcommands`, `sortcategories`,
        `commandcount`, `banner`, `homebutton`, `closebutton`, `pagecounter`,
        `detailparent`, `detailcog`, `detailfullhelp`, `reactionnav`

        Numbers: `timeout`, `deleteafter`, `maxperpage`
        """
        toggles = {
            "aliases": "show_aliases", "cooldown": "show_cooldown", "permissions": "show_permissions",
            "signature": "show_signature", "hidden": "show_hidden", "timestamp": "timestamp",
            "selectmenu": "use_select_menu", "buttons": "use_buttons", "dmhelp": "dm_help",
            "ephemeral": "ephemeral", "favourites": "allow_favourites", "favorites": "allow_favourites",
            "search": "search_enabled", "sortcommands": "sort_commands", "sortcategories": "sort_categories",
            "commandcount": "show_command_count", "banner": "show_category_banner",
            "homebutton": "show_home_button", "closebutton": "show_close_button",
            "pagecounter": "show_page_counter", "detailparent": "detail_show_parent",
            "detailcog": "detail_show_cog", "detailfullhelp": "detail_show_full_help",
            "reactionnav": "reaction_nav",
        }
        numbers = {"timeout": "timeout", "deleteafter": "delete_after", "maxperpage": "max_commands_per_page"}
        sl = setting.lower()
        if sl in toggles:
            on = value.lower() in ("on", "true", "yes", "1", "enable")
            await self.config.guild(ctx.guild).get_attr(toggles[sl]).set(on)
            await ctx.send(f"✅ **{setting}** → **{'on' if on else 'off'}**.")
        elif sl in numbers:
            try:
                n = int(value)
            except ValueError:
                return await ctx.send("Provide a number.")
            await self.config.guild(ctx.guild).get_attr(numbers[sl]).set(n)
            await ctx.send(f"✅ **{setting}** → **{n}**.")
        else:
            await ctx.send(f"Unknown setting. Valid: {humanize_list(list(toggles) + list(numbers))}")

    # ━━━━━━━━━━━━━━━━━ Categories ━━━━━━━━━━━━━━━━━

    @helpmenu.group(name="category", aliases=["cat"])
    async def hm_cat(self, ctx):
        """Manage custom categories."""

    @hm_cat.command(name="create", aliases=["add"])
    async def cat_create(self, ctx, name: str, emoji: Optional[str] = None, *, description: str = ""):
        """Create a custom category.

        `[p]hm cat create Moderation 🛡️ All mod commands`
        """
        async with self.config.guild(ctx.guild).categories() as cs:
            if name in cs:
                return await ctx.send(f"`{name}` already exists.")
            cs[name] = {"label": name, "emoji": emoji, "description": description,
                        "colour": None, "thumbnail": None, "image": None, "cogs": [],
                        "order": len(cs), "hidden": False, "required_role": None}
        await ctx.send(f"✅ Category **{name}** created.")

    @hm_cat.command(name="delete", aliases=["remove", "rm"])
    async def cat_delete(self, ctx, name: str):
        """Delete a category."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            del cs[name]
        await ctx.send(f"✅ **{name}** deleted.")

    @hm_cat.command(name="rename")
    async def cat_rename(self, ctx, old: str, *, new: str):
        """Rename a category."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if old not in cs:
                return await ctx.send("Not found.")
            d = cs.pop(old)
            d["label"] = new
            cs[new] = d
        await ctx.send(f"✅ **{old}** → **{new}**.")

    @hm_cat.command(name="label")
    async def cat_label(self, ctx, name: str, *, label: str):
        """Set the display label (can differ from the internal name)."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["label"] = label
        await ctx.send(f"✅ Label for **{name}** → {label}")

    @hm_cat.command(name="emoji")
    async def cat_emoji(self, ctx, name: str, emoji: Optional[str] = None):
        """Set/clear category emoji."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["emoji"] = emoji
        await ctx.send(f"✅ Emoji {'set' if emoji else 'cleared'}.")

    @hm_cat.command(name="description", aliases=["desc"])
    async def cat_desc(self, ctx, name: str, *, description: str = ""):
        """Set category description."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["description"] = description
        await ctx.send("✅ Description updated.")

    @hm_cat.command(name="colour", aliases=["color"])
    async def cat_colour(self, ctx, name: str, colour: discord.Colour):
        """Set category embed colour."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["colour"] = colour.value
        await ctx.send(f"✅ Colour set for **{name}**.")

    @hm_cat.command(name="thumbnail")
    async def cat_thumb(self, ctx, name: str, url: Optional[str] = None):
        """Set/reset category thumbnail."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["thumbnail"] = url
        await ctx.send(f"✅ Thumbnail {'set' if url else 'reset'}.")

    @hm_cat.command(name="image")
    async def cat_img(self, ctx, name: str, url: Optional[str] = None):
        """Set/reset category large image."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["image"] = url
        await ctx.send(f"✅ Image {'set' if url else 'reset'}.")

    @hm_cat.command(name="order")
    async def cat_order(self, ctx, name: str, order: int):
        """Set display order (lower = first)."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["order"] = order
        await ctx.send(f"✅ Order → **{order}**.")

    @hm_cat.command(name="hide")
    async def cat_hide(self, ctx, name: str):
        """Hide a category."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["hidden"] = True
        await ctx.send(f"✅ **{name}** hidden.")

    @hm_cat.command(name="unhide", aliases=["show"])
    async def cat_unhide(self, ctx, name: str):
        """Unhide a category."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["hidden"] = False
        await ctx.send(f"✅ **{name}** visible.")

    @hm_cat.command(name="requirerole", aliases=["role"])
    async def cat_role(self, ctx, name: str, role: Optional[discord.Role] = None):
        """Require a role to see this category."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            cs[name]["required_role"] = role.id if role else None
        await ctx.send(f"✅ Role requirement {'set' if role else 'cleared'}.")

    @hm_cat.command(name="addcog")
    async def cat_addcog(self, ctx, name: str, *, cog_name: str):
        """Add a cog to a category."""
        if cog_name not in self.bot.cogs:
            return await ctx.send(f"Cog `{cog_name}` not found (case-sensitive).")
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            if cog_name not in cs[name]["cogs"]:
                cs[name]["cogs"].append(cog_name)
        await ctx.send(f"✅ **{cog_name}** → **{name}**.")

    @hm_cat.command(name="removecog", aliases=["rmcog"])
    async def cat_rmcog(self, ctx, name: str, *, cog_name: str):
        """Remove a cog from a category."""
        async with self.config.guild(ctx.guild).categories() as cs:
            if name not in cs:
                return await ctx.send("Not found.")
            if cog_name in cs[name]["cogs"]:
                cs[name]["cogs"].remove(cog_name)
        await ctx.send(f"✅ Removed.")

    @hm_cat.command(name="list")
    async def cat_list(self, ctx):
        """List all custom categories."""
        cs = await self.config.guild(ctx.guild).categories()
        if not cs:
            return await ctx.send("No custom categories. Cogs auto-group into their own categories.")
        lines = []
        for n, d in sorted(cs.items(), key=lambda kv: kv[1].get("order", 999)):
            e = d.get("emoji", "📁")
            cogs = d.get("cogs", [])
            h = " (hidden)" if d.get("hidden") else ""
            r = ""
            if d.get("required_role"):
                ro = ctx.guild.get_role(d["required_role"])
                r = f" [role: {ro.name if ro else 'deleted'}]"
            lines.append(f"{e} **{d.get('label', n)}** — order: {d.get('order', 0)}, cogs: {humanize_list(cogs) or 'none'}{h}{r}")
        await ctx.send("\n".join(lines))

    # ━━━━━━━━━━━━━━━━━ Blacklists ━━━━━━━━━━━━━━━━━

    @helpmenu.group(name="hide")
    async def hm_hide(self, ctx):
        """Hide cogs or commands."""

    @hm_hide.command(name="cog")
    async def hide_cog(self, ctx, *, cog_name: str):
        """Hide a cog entirely."""
        async with self.config.guild(ctx.guild).hidden_cogs() as h:
            if cog_name not in h:
                h.append(cog_name)
        await ctx.send(f"✅ **{cog_name}** hidden.")

    @hm_hide.command(name="command", aliases=["cmd"])
    async def hide_cmd(self, ctx, *, command_name: str):
        """Hide a specific command."""
        async with self.config.guild(ctx.guild).hidden_commands() as h:
            if command_name not in h:
                h.append(command_name)
        await ctx.send(f"✅ `{command_name}` hidden.")

    @helpmenu.group(name="unhide")
    async def hm_unhide(self, ctx):
        """Unhide cogs or commands."""

    @hm_unhide.command(name="cog")
    async def unhide_cog(self, ctx, *, cog_name: str):
        """Unhide a cog."""
        async with self.config.guild(ctx.guild).hidden_cogs() as h:
            if cog_name in h:
                h.remove(cog_name)
        await ctx.send(f"✅ **{cog_name}** visible.")

    @hm_unhide.command(name="command", aliases=["cmd"])
    async def unhide_cmd(self, ctx, *, command_name: str):
        """Unhide a command."""
        async with self.config.guild(ctx.guild).hidden_commands() as h:
            if command_name in h:
                h.remove(command_name)
        await ctx.send(f"✅ `{command_name}` visible.")

    @hm_hide.command(name="list")
    async def hide_list(self, ctx):
        """List all hidden items."""
        hc = await self.config.guild(ctx.guild).hidden_cogs()
        hcm = await self.config.guild(ctx.guild).hidden_commands()
        parts = []
        if hc:
            parts.append(f"**Hidden Cogs:** {humanize_list(hc)}")
        if hcm:
            parts.append(f"**Hidden Commands:** {humanize_list([f'`{c}`' for c in hcm])}")
        await ctx.send("\n".join(parts) or "Nothing hidden.")

    # ━━━━━━━━━━━━━━━━━ Quick Links ━━━━━━━━━━━━━━━━━

    @helpmenu.group(name="quicklink", aliases=["ql"])
    async def hm_ql(self, ctx):
        """Manage quick-link buttons."""

    @hm_ql.command(name="add")
    async def ql_add(self, ctx, label: str, url: str, emoji: Optional[str] = None):
        """Add a quick link. Max 5."""
        async with self.config.guild(ctx.guild).quick_links() as ql:
            if len(ql) >= 5:
                return await ctx.send("Max 5 links.")
            ql.append({"label": label, "url": url, "emoji": emoji})
        await ctx.send(f"✅ **{label}** added.")

    @hm_ql.command(name="remove", aliases=["rm"])
    async def ql_rm(self, ctx, label: str):
        """Remove a quick link."""
        async with self.config.guild(ctx.guild).quick_links() as ql:
            ql[:] = [q for q in ql if q.get("label") != label]
        await ctx.send(f"✅ **{label}** removed.")

    @hm_ql.command(name="list")
    async def ql_list(self, ctx):
        """List quick links."""
        ql = await self.config.guild(ctx.guild).quick_links()
        if not ql:
            return await ctx.send("None.")
        await ctx.send("\n".join(f"{q.get('emoji', '🔗')} **{q['label']}** — {q['url']}" for q in ql))

    # ━━━━━━━━━━━━━━━━━ Home Fields ━━━━━━━━━━━━━━━━━

    @helpmenu.group(name="field")
    async def hm_field(self, ctx):
        """Manage home page fields."""

    @hm_field.command(name="add")
    async def field_add(self, ctx, name: str, *, value: str):
        """Add a field. Append `--inline` for inline."""
        inline = False
        if value.endswith("--inline"):
            value = value[:-8].strip()
            inline = True
        async with self.config.guild(ctx.guild).home_fields() as fs:
            fs.append({"name": name, "value": value, "inline": inline})
        await ctx.send(f"✅ Field **{name}** added.")

    @hm_field.command(name="remove", aliases=["rm"])
    async def field_rm(self, ctx, name: str):
        """Remove a field."""
        async with self.config.guild(ctx.guild).home_fields() as fs:
            fs[:] = [f for f in fs if f.get("name") != name]
        await ctx.send(f"✅ Removed.")

    @hm_field.command(name="clear")
    async def field_clear(self, ctx):
        """Clear all fields."""
        await self.config.guild(ctx.guild).home_fields.set([])
        await ctx.send("✅ Cleared.")

    @hm_field.command(name="list")
    async def field_list(self, ctx):
        """List fields."""
        fs = await self.config.guild(ctx.guild).home_fields()
        if not fs:
            return await ctx.send("None.")
        await ctx.send("\n".join(f"**{f['name']}** — {_trunc(f['value'], 60)} {'(inline)' if f.get('inline') else ''}" for f in fs))

    # ━━━━━━━━━━━━━━━━━ Uncategorised ━━━━━━━━━━━━━━━━━

    @helpmenu.command(name="uncatlabel")
    async def hm_uncl(self, ctx, *, label: str):
        """Set uncategorised label."""
        await self.config.guild(ctx.guild).uncategorised_label.set(label)
        await ctx.send(f"✅ Label → {label}")

    @helpmenu.command(name="uncatdesc")
    async def hm_uncd(self, ctx, *, desc: str = ""):
        """Set uncategorised description."""
        await self.config.guild(ctx.guild).uncategorised_description.set(desc)
        await ctx.send("✅ Updated.")

    @helpmenu.command(name="uncatemoji")
    async def hm_unce(self, ctx, emoji: str):
        """Set uncategorised emoji."""
        await self.config.guild(ctx.guild).uncategorised_emoji.set(emoji)
        await ctx.send(f"✅ Emoji → {emoji}")

    @helpmenu.command(name="hideuncat")
    async def hm_huc(self, ctx):
        """Toggle hiding uncategorised section."""
        cur = await self.config.guild(ctx.guild).hide_uncategorised()
        await self.config.guild(ctx.guild).hide_uncategorised.set(not cur)
        await ctx.send(f"✅ Uncategorised **{'hidden' if not cur else 'visible'}**.")

    # ━━━━━━━━━━━━━━━━━ Preview / Settings / Reset ━━━━━━━━━━━━━━━━━

    @helpmenu.command(name="preview")
    async def hm_preview(self, ctx):
        """Preview the help menu."""
        await self._send_help(ctx)

    @helpmenu.command(name="settings")
    async def hm_settings(self, ctx):
        """Show current settings."""
        conf = await self._conf(ctx.guild)
        skip = {"categories", "home_fields", "quick_links"}
        lines = [f"**{k}:** `{v}`" for k, v in sorted(conf.items()) if k not in skip]
        lines.append(f"\n**Categories:** {len(conf.get('categories', {}))}")
        lines.append(f"**Home Fields:** {len(conf.get('home_fields', []))}")
        lines.append(f"**Quick Links:** {len(conf.get('quick_links', []))}")
        for p in pagify("\n".join(lines), page_length=1900):
            await ctx.send(p)

    @helpmenu.command(name="reset")
    async def hm_reset(self, ctx):
        """Reset all settings to defaults."""
        await self.config.guild(ctx.guild).clear()
        await ctx.send("✅ All settings reset.")

    @helpmenu.command(name="export")
    async def hm_export(self, ctx):
        """Export current config as a code block (for backup/sharing)."""
        import json
        conf = await self._conf(ctx.guild)
        text = json.dumps(conf, indent=2, default=str)
        for p in pagify(text, page_length=1900):
            await ctx.send(f"```json\n{p}\n```")

    # ━━━━━━━━━━━━━━━━━ User Favourites ━━━━━━━━━━━━━━━━━

    @commands.command(name="favourite", aliases=["fav", "favorite"])
    @commands.guild_only()
    async def user_fav(self, ctx, *, command_name: str):
        """Toggle a command in your favourites."""
        cmd = self.bot.get_command(command_name)
        if not cmd:
            return await ctx.send(f"`{command_name}` not found.")
        qn = cmd.qualified_name
        async with self.config.member(ctx.author).favourites() as fv:
            if qn in fv:
                fv.remove(qn)
                await ctx.send(f"⭐ **{qn}** removed from favourites.")
            else:
                fv.append(qn)
                await ctx.send(f"⭐ **{qn}** added to favourites!")

    @commands.command(name="favourites", aliases=["favs", "favorites"])
    @commands.guild_only()
    async def user_favs(self, ctx):
        """View your favourites."""
        fv = await self.config.member(ctx.author).favourites()
        if not fv:
            return await ctx.send("No favourites yet. Use `[p]fav <command>` to add one!")
        lines = []
        for qn in fv:
            cmd = self.bot.get_command(qn)
            lines.append(f"⭐ `{qn}` — {cmd.short_doc if cmd else '*not found*'}")
        await ctx.send("\n".join(lines))
