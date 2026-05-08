"""
NewHelpMenu — Components V2 mega cog for Red-DiscordBot.

Replaces Red's help system, converts all embeds to Components V2,
and overrides menus/pagination. Toggle on/off, default off.

Requires discord.py 2.6+ (ships with Red 3.5.21+).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import discord
from discord import ui
from discord.ext import commands as dpy_commands
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify

from .converter import embed_to_container, embeds_to_layout, view_items_to_action_rows
from .formatter import (
    CV2MenuPaginator,
    EmbedHelpView,
    HelpPaginatorView,
    gather_bot_help_data,
    gather_cog_help_data,
    gather_command_help_data,
    build_bot_help_embeds,
    build_command_help_embed,
    build_cog_help_embed,
    build_cv2_bot_help_pages,
    build_cv2_command_help,
    build_cv2_cog_help,
    _make_category_container,
)

log = logging.getLogger("red.evecogs.newhelpmenu")

# ──────────────────────────── defaults ────────────────────────────

DEFAULT_GUILD: Dict[str, Any] = {
    # Master toggle — everything is behind this
    "enabled": False,
    # Sub-toggles
    "help_override": True,
    "embed_override": True,
    "menu_override": True,
    # Appearance
    "accent_color": 0x5865F2,  # Blurple
    "show_thumbnail": True,
    "show_footer": True,
    "compact_fields": False,
    "bot_thumbnail_url": "",  # Empty = use bot avatar
    # Help system
    "categories": {},  # {cat_name: [cog_name, ...]}
    "category_emojis": {},  # {cat_name: emoji}
    "blacklisted_cogs": [],
    "blacklisted_commands": [],
    "show_hidden": False,
    "help_timeout": 180,
    "help_in_dm": False,
    # Override scope
    "override_mode": "all",  # "all", "help_only", "commands_only"
    # Per-cog overrides: {cog_name: True/False}
    "cog_overrides": {},
}

DEFAULT_GLOBAL: Dict[str, Any] = {
    "schema_version": 1,
}


class NewHelpMenu(commands.Cog):
    """Components V2 help menu + global embed/menu override.

    Replaces Red's help system and optionally converts ALL bot embeds
    and menus into Discord Components V2 layouts.

    **Toggle on/off with `[p]cv2 toggle` (off by default).**
    """

    __version__ = "1.0.0"
    __author__ = "everestmcarthur"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=7283901647, force_registration=True
        )
        self.config.register_guild(**DEFAULT_GUILD)
        self.config.register_global(**DEFAULT_GLOBAL)

        # Store original methods for restoration
        self._original_send: Optional[Callable] = None
        self._original_help_command: Optional[commands.Command] = None
        self._original_channel_send: Optional[Callable] = None
        self._active_views: Dict[int, ui.LayoutView] = {}  # msg_id -> view
        self._patched = False

    async def initialize(self):
        """Called after cog is added — set up monkey patches."""
        await self._apply_patches()

    async def cog_unload(self):
        """Restore everything on unload."""
        await self._remove_patches()
        # Stop all active views
        for view in self._active_views.values():
            view.stop()
        self._active_views.clear()
        # Restore Red's original help command
        if self._original_help_command is not None:
            self.bot.add_command(self._original_help_command)
            log.info("NewHelpMenu: Restored original help command")

    # ═══════════════════════════════════════════════════════════════
    #  MONKEY PATCHING
    # ═══════════════════════════════════════════════════════════════

    async def _apply_patches(self):
        """Monkey-patch Context.send AND channel.send to intercept embeds globally."""
        if self._patched:
            return

        original_ctx_send = commands.Context.send
        original_channel_send = discord.abc.Messageable.send

        cog_ref = self  # closure reference
        _converting = set()  # recursion guard (task ids)

        async def _convert_and_send(original_fn, self_obj, content, kwargs):
            """Shared logic: convert embeds → CV2, call the original fn."""
            # Recursion guard: Context.send calls super().send (Messageable.send)
            # which we also patch. Use asyncio task id to detect re-entry.
            task = id(asyncio.current_task())
            if task in _converting:
                return await original_fn(self_obj, content, **kwargs)
            _converting.add(task)
            try:
                # Resolve the guild from whatever object we're sending to
                guild = None
                if isinstance(self_obj, commands.Context):
                    guild = self_obj.guild
                elif isinstance(self_obj, (discord.TextChannel, discord.VoiceChannel,
                                           discord.StageChannel, discord.Thread)):
                    guild = self_obj.guild
                elif isinstance(self_obj, discord.Member):
                    guild = self_obj.guild

                if guild is None:
                    return await original_fn(self_obj, content, **kwargs)

                settings = await cog_ref.config.guild(guild).all()

                if not settings["enabled"] or not settings["embed_override"]:
                    return await original_fn(self_obj, content, **kwargs)

                # Don't intercept if there's already a LayoutView
                existing_view = kwargs.get("view")
                if isinstance(existing_view, ui.LayoutView):
                    return await original_fn(self_obj, content, **kwargs)

                # Check override mode (help_only = don't convert general sends)
                mode = settings["override_mode"]
                if mode == "help_only":
                    return await original_fn(self_obj, content, **kwargs)

                # Check per-cog override (only applies to Context sends)
                if isinstance(self_obj, commands.Context):
                    cmd = self_obj.command
                    if cmd and cmd.cog_name:
                        cog_overrides = settings.get("cog_overrides", {})
                        if cmd.cog_name in cog_overrides:
                            if not cog_overrides[cmd.cog_name]:
                                return await original_fn(self_obj, content, **kwargs)

                # Check if there are embeds to convert
                embed = kwargs.pop("embed", None)
                embeds = kwargs.pop("embeds", None)

                embed_list: List[discord.Embed] = []
                if embed is not None:
                    embed_list.append(embed)
                if embeds:
                    embed_list.extend(embeds)

                if not embed_list:
                    return await original_fn(self_obj, content, **kwargs)

                # Convert embeds to LayoutView
                accent = settings["accent_color"]

                # Extract existing view items if present
                action_rows = None
                if existing_view and isinstance(existing_view, ui.View):
                    action_rows = view_items_to_action_rows(existing_view)
                    kwargs.pop("view", None)

                layout = embeds_to_layout(
                    embed_list,
                    content=content,
                    accent_color=accent,
                    show_thumbnail=settings["show_thumbnail"],
                    show_footer=settings["show_footer"],
                    compact=settings["compact_fields"],
                    existing_action_rows=action_rows,
                )

                # Send with LayoutView (content must be None for CV2)
                kwargs["view"] = layout
                kwargs.pop("embed", None)
                kwargs.pop("embeds", None)
                msg = await original_fn(self_obj, None, **kwargs)

                # Track for cleanup
                if msg:
                    cog_ref._active_views[msg.id] = layout

                return msg

            except Exception as e:
                log.warning(f"CV2 conversion failed, falling back to original: {e}")
                return await original_fn(self_obj, content, **kwargs)
            finally:
                _converting.discard(task)

        async def patched_ctx_send(ctx_self, content=None, **kwargs):
            """Wrapper around Context.send."""
            return await _convert_and_send(original_ctx_send, ctx_self, content, kwargs)

        async def patched_channel_send(channel_self, content=None, **kwargs):
            """Wrapper around Messageable.send (channels, threads, etc.)."""
            return await _convert_and_send(original_channel_send, channel_self, content, kwargs)

        self._original_send = original_ctx_send
        self._original_channel_send = original_channel_send
        commands.Context.send = patched_ctx_send
        discord.abc.Messageable.send = patched_channel_send
        self._patched = True
        log.info("NewHelpMenu: Patched Context.send + Messageable.send for global embed → CV2")

    async def _remove_patches(self):
        """Restore original methods."""
        if self._original_send:
            commands.Context.send = self._original_send
            self._original_send = None
        if self._original_channel_send:
            discord.abc.Messageable.send = self._original_channel_send
            self._original_channel_send = None
        self._patched = False
        log.info("NewHelpMenu: Restored original send methods")

    # ═══════════════════════════════════════════════════════════════
    #  HELP SYSTEM — Embeds by default, CV2 when enabled
    # ═══════════════════════════════════════════════════════════════

    async def _send_help(
        self,
        ctx: commands.Context,
        thing: Optional[str] = None,
    ):
        """Send help for the bot, a cog, or a command.

        Uses embeds by default. When CV2 is enabled, uses Components V2 containers.
        """
        settings = await self.config.guild(ctx.guild).all()
        accent = settings["accent_color"]
        categories = settings["categories"]
        category_emojis = settings["category_emojis"]
        blacklisted_cogs = settings["blacklisted_cogs"]
        blacklisted_commands = settings["blacklisted_commands"]
        show_hidden = settings["show_hidden"]
        timeout = settings["help_timeout"]
        use_cv2 = settings["enabled"]
        destination = ctx.author if settings["help_in_dm"] else ctx.channel

        if thing is None:
            # ── Full bot help ──
            cat_data, total = await gather_bot_help_data(
                ctx, self.bot,
                categories=categories,
                category_emojis=category_emojis,
                show_hidden=show_hidden,
                blacklisted_cogs=blacklisted_cogs,
                blacklisted_commands=blacklisted_commands,
            )

            if use_cv2:
                pages, select_opts = build_cv2_bot_help_pages(
                    ctx, self.bot, cat_data, total, accent_color=accent
                )
                view = HelpPaginatorView(
                    pages, author_id=ctx.author.id,
                    timeout=float(timeout), category_options=select_opts,
                )
                msg = await destination.send(view=view)
                view.message = msg
                self._active_views[msg.id] = view
            else:
                embeds, select_opts = build_bot_help_embeds(
                    ctx, self.bot, cat_data, total, accent_color=accent
                )
                if len(embeds) == 1:
                    msg = await destination.send(embed=embeds[0])
                else:
                    view = EmbedHelpView(
                        embeds, author_id=ctx.author.id,
                        timeout=float(timeout), category_options=select_opts,
                    )
                    msg = await destination.send(embed=embeds[0], view=view)
                    view.message = msg

        else:
            # ── Specific thing ──
            cmd = self.bot.get_command(thing)
            if cmd:
                data = await gather_command_help_data(ctx, cmd)
                if use_cv2:
                    components = build_cv2_command_help(ctx, data, accent_color=accent)
                    layout = ui.LayoutView()
                    for comp in components:
                        layout.add_item(comp)
                    msg = await destination.send(view=layout)
                    self._active_views[msg.id] = layout
                else:
                    embed = build_command_help_embed(ctx, data, accent_color=accent)
                    await destination.send(embed=embed)
                return

            cog = self.bot.get_cog(thing)
            if cog:
                cog_name, cog_doc, cmds = await gather_cog_help_data(ctx, cog, show_hidden=show_hidden)
                if use_cv2:
                    components = build_cv2_cog_help(ctx, cog_name, cog_doc, cmds, accent_color=accent)
                    layout = ui.LayoutView()
                    for comp in components:
                        layout.add_item(comp)
                    msg = await destination.send(view=layout)
                    self._active_views[msg.id] = layout
                else:
                    embed = build_cog_help_embed(ctx, cog_name, cog_doc, cmds, accent_color=accent)
                    await destination.send(embed=embed)
                return

            # Try category
            for cat_name, cog_list in categories.items():
                if cat_name.lower() == thing.lower():
                    all_cmds: List[Tuple[str, str]] = []
                    for cog_name_str in cog_list:
                        cog_obj = self.bot.get_cog(cog_name_str)
                        if cog_obj:
                            for c in sorted(cog_obj.get_commands(), key=lambda x: x.name):
                                if c.hidden and not show_hidden:
                                    continue
                                try:
                                    if not await c.can_run(ctx):
                                        continue
                                except Exception:
                                    continue
                                short = c.short_doc or "No description"
                                all_cmds.append((f"{ctx.clean_prefix}{c.qualified_name}", short))

                    emoji = category_emojis.get(cat_name, "📂")
                    prefix = ctx.clean_prefix
                    if use_cv2:
                        container = _make_category_container(cat_name, all_cmds, accent_color=accent, emoji=emoji, prefix=prefix)
                        layout = ui.LayoutView()
                        layout.add_item(container)
                        msg = await destination.send(view=layout)
                        self._active_views[msg.id] = layout
                    else:
                        bot_avatar = self.bot.user.display_avatar.url if self.bot.user else None
                        embed = discord.Embed(color=discord.Colour(accent))
                        embed.set_author(name=f"{emoji}  {cat_name}", icon_url=bot_avatar)
                        cmd_lines = []
                        for cmd_name, short in all_cmds:
                            display = cmd_name
                            if display.startswith(prefix):
                                display = display[len(prefix):]
                            cmd_lines.append(f"**`{display}`** · {short[:60]}")
                        embed.description = "\n".join(cmd_lines)
                        embed.set_footer(text=f"{prefix}help <command> for details")
                        await destination.send(embed=embed)
                    return

            # Nothing found
            if use_cv2:
                layout = ui.LayoutView()
                container = ui.Container(accent_colour=discord.Colour(0xED4245))
                container.add_item(ui.TextDisplay(f"❌ No command, cog, or category named **{thing}** found."))
                layout.add_item(container)
                await ctx.send(view=layout)
            else:
                embed = discord.Embed(
                    description=f"❌ No command, cog, or category named **{thing}** found.",
                    color=discord.Colour(0xED4245),
                )
                await ctx.send(embed=embed)

    # ═══════════════════════════════════════════════════════════════
    #  LISTENERS
    # ═══════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Route button/select interactions to our active views."""
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "") if interaction.data else ""
        if not custom_id.startswith(("help_", "cv2menu_")):
            return

        msg_id = interaction.message.id if interaction.message else None
        if msg_id and msg_id in self._active_views:
            view = self._active_views[msg_id]
            if hasattr(view, "handle_interaction"):
                await view.handle_interaction(interaction)
                return

        try:
            await interaction.response.defer()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    #  HELP COMMAND — replaces Red's default (removed in __init__.py)
    # ═══════════════════════════════════════════════════════════════

    @commands.command(name="help")
    async def _help_command(self, ctx: commands.Context, *, thing: str = None):
        """Shows help for the bot, a command, a cog, or a category."""
        if ctx.guild:
            try:
                await self._send_help(ctx, thing)
                return
            except Exception as e:
                log.exception(f"Help menu failed, using text fallback: {e}")

        # Fallback for DMs or on error — paginate to stay under 2000 chars
        if thing is None:
            prefix = ctx.clean_prefix
            header = f"**{ctx.bot.user.display_name} — Help**\nUse `{prefix}help <command>` for details.\n"
            chunks: List[str] = []
            current = header
            cog_names = sorted(ctx.bot.cogs.keys())
            for cog_name in cog_names:
                cog_obj = ctx.bot.get_cog(cog_name)
                cmds = [c for c in cog_obj.get_commands() if not c.hidden]
                if cmds:
                    cmd_names = ", ".join(f"`{c.name}`" for c in sorted(cmds, key=lambda c: c.name))
                    line = f"**{cog_name}** — {cmd_names}\n"
                    if len(current) + len(line) > 1900:
                        chunks.append(current)
                        current = line
                    else:
                        current += line
            if current:
                chunks.append(current)
            for chunk in chunks:
                await ctx.send(chunk)
        else:
            cmd = ctx.bot.get_command(thing)
            if cmd:
                prefix = ctx.clean_prefix
                sig = cmd.signature or ""
                desc = cmd.help or cmd.short_doc or "No description."
                text = f"**{prefix}{cmd.qualified_name}** {sig}\n\n{desc}"
                if cmd.aliases:
                    text += f"\n\n**Aliases:** {', '.join(cmd.aliases)}"
                await ctx.send(text)
            else:
                cog_obj = ctx.bot.get_cog(thing)
                if cog_obj:
                    prefix = ctx.clean_prefix
                    lines = [f"**{cog_obj.qualified_name}**\n{cog_obj.help or cog_obj.__doc__ or 'No description.'}\n"]
                    for c in sorted(cog_obj.get_commands(), key=lambda c: c.name):
                        if not c.hidden:
                            lines.append(f"`{prefix}{c.qualified_name}` — {c.short_doc or 'No description'}")
                    await ctx.send("\n".join(lines))
                else:
                    await ctx.send(f"No command or category named **{thing}** found.")

    # ═══════════════════════════════════════════════════════════════
    #  SETTINGS COMMANDS
    # ═══════════════════════════════════════════════════════════════

    @commands.group(name="cv2", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2(self, ctx: commands.Context):
        """Components V2 settings and controls."""
        prefix = ctx.clean_prefix
        cmds = "\n".join(
            f"`{prefix}cv2 {c.name}` — {c.short_doc}" for c in sorted(self.cv2.commands, key=lambda c: c.name)
        )
        await ctx.send(f"**CV2 Settings**\n{cmds}")

    @cv2.command(name="toggle")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_toggle(self, ctx: commands.Context):
        """Toggle Components V2 on/off for this server."""
        current = await self.config.guild(ctx.guild).enabled()
        new_val = not current
        await self.config.guild(ctx.guild).enabled.set(new_val)

        status = "✅ **Enabled**" if new_val else "❌ **Disabled**"

        if new_val:
            layout = ui.LayoutView()
            container = ui.Container(
                accent_colour=discord.Colour(
                    await self.config.guild(ctx.guild).accent_color()
                )
            )
            container.add_item(
                ui.TextDisplay(f"## Components V2 {status}")
            )
            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            container.add_item(
                ui.TextDisplay(
                    "All bot embeds, help menus, and paginated menus will now use "
                    "Discord's new Components V2 layout system.\n\n"
                    f"Use `{ctx.clean_prefix}cv2 settings` to see all options.\n"
                    f"Use `{ctx.clean_prefix}cv2 help toggle` to toggle help override.\n"
                    f"Use `{ctx.clean_prefix}cv2 embeds toggle` to toggle embed conversion."
                )
            )
            layout.add_item(container)
            await ctx.send(view=layout)
        else:
            await ctx.send(f"Components V2 {status} — reverted to standard embeds.")

    @cv2.group(name="help", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_help(self, ctx: commands.Context):
        """Help menu override settings."""
        enabled = await self.config.guild(ctx.guild).help_override()
        status = "✅ Enabled" if enabled else "❌ Disabled"
        await ctx.send(f"Help menu override: {status}")

    @cv2_help.command(name="toggle")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_help_toggle(self, ctx: commands.Context):
        """Toggle the Components V2 help menu."""
        current = await self.config.guild(ctx.guild).help_override()
        new_val = not current
        await self.config.guild(ctx.guild).help_override.set(new_val)
        status = "✅ Enabled" if new_val else "❌ Disabled"
        await ctx.send(f"Help menu override: {status}")

    @cv2_help.command(name="dm")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_help_dm(self, ctx: commands.Context):
        """Toggle whether help is sent via DM."""
        current = await self.config.guild(ctx.guild).help_in_dm()
        new_val = not current
        await self.config.guild(ctx.guild).help_in_dm.set(new_val)
        where = "DMs" if new_val else "the channel"
        await ctx.send(f"Help will now be sent to {where}.")

    @cv2_help.command(name="timeout")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_help_timeout(self, ctx: commands.Context, seconds: int):
        """Set the help menu timeout in seconds (30-600)."""
        seconds = max(30, min(600, seconds))
        await self.config.guild(ctx.guild).help_timeout.set(seconds)
        await ctx.send(f"Help menu timeout set to **{seconds}s**.")

    @cv2_help.command(name="hidden")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_help_hidden(self, ctx: commands.Context):
        """Toggle showing hidden commands in help."""
        current = await self.config.guild(ctx.guild).show_hidden()
        new_val = not current
        await self.config.guild(ctx.guild).show_hidden.set(new_val)
        status = "shown" if new_val else "hidden"
        await ctx.send(f"Hidden commands are now **{status}** in help.")

    @cv2.group(name="embeds", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_embeds(self, ctx: commands.Context):
        """Embed conversion settings."""
        enabled = await self.config.guild(ctx.guild).embed_override()
        status = "✅ Enabled" if enabled else "❌ Disabled"
        await ctx.send(f"Embed → Components V2 conversion: {status}")

    @cv2_embeds.command(name="toggle")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_embeds_toggle(self, ctx: commands.Context):
        """Toggle automatic embed → Components V2 conversion."""
        current = await self.config.guild(ctx.guild).embed_override()
        new_val = not current
        await self.config.guild(ctx.guild).embed_override.set(new_val)
        status = "✅ Enabled" if new_val else "❌ Disabled"
        await ctx.send(f"Embed → Components V2 conversion: {status}")

    @cv2_embeds.command(name="mode")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_embeds_mode(self, ctx: commands.Context, mode: str):
        """Set override mode: `all`, `help_only`, or `commands_only`.

        - **all** — Convert all bot embeds everywhere
        - **help_only** — Only convert the help menu
        - **commands_only** — Only convert command responses
        """
        mode = mode.lower()
        if mode not in ("all", "help_only", "commands_only"):
            await ctx.send("Invalid mode. Choose: `all`, `help_only`, or `commands_only`.")
            return
        await self.config.guild(ctx.guild).override_mode.set(mode)
        await ctx.send(f"Override mode set to **{mode}**.")

    @cv2_embeds.command(name="cog")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_embeds_cog(self, ctx: commands.Context, cog_name: str, enable: bool):
        """Override embed conversion for a specific cog.

        Example: `[p]cv2 embeds cog Moderation false` — disable CV2 for Moderation.
        """
        async with self.config.guild(ctx.guild).cog_overrides() as overrides:
            overrides[cog_name] = enable
        status = "enabled" if enable else "disabled"
        await ctx.send(f"Embed conversion for **{cog_name}**: {status}")

    @cv2.group(name="menus", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_menus(self, ctx: commands.Context):
        """Menu/pagination override settings."""
        enabled = await self.config.guild(ctx.guild).menu_override()
        status = "✅ Enabled" if enabled else "❌ Disabled"
        await ctx.send(f"Menu → Components V2 override: {status}")

    @cv2_menus.command(name="toggle")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_menus_toggle(self, ctx: commands.Context):
        """Toggle Components V2 menu pagination."""
        current = await self.config.guild(ctx.guild).menu_override()
        new_val = not current
        await self.config.guild(ctx.guild).menu_override.set(new_val)
        status = "✅ Enabled" if new_val else "❌ Disabled"
        await ctx.send(f"Menu → Components V2 override: {status}")

    # ── Appearance ──

    @cv2.command(name="color", aliases=["colour"])
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_color(self, ctx: commands.Context, hex_color: str):
        """Set the global accent colour (hex).

        Example: `[p]cv2 color #FF5733` or `[p]cv2 color 5865F2`
        """
        hex_color = hex_color.strip("#")
        try:
            color_int = int(hex_color, 16)
            if color_int < 0 or color_int > 0xFFFFFF:
                raise ValueError
        except ValueError:
            await ctx.send("Invalid hex colour. Use format: `#5865F2` or `5865F2`.")
            return

        await self.config.guild(ctx.guild).accent_color.set(color_int)

        if await self.config.guild(ctx.guild).enabled():
            layout = ui.LayoutView()
            container = ui.Container(accent_colour=discord.Colour(color_int))
            container.add_item(
                ui.TextDisplay(f"### ✅ Accent colour updated to `#{hex_color.upper()}`")
            )
            container.add_item(
                ui.TextDisplay("This is how your containers will look.")
            )
            layout.add_item(container)
            await ctx.send(view=layout)
        else:
            await ctx.send(f"Accent colour set to `#{hex_color.upper()}`.")

    @cv2.command(name="thumbnail")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_thumbnail(self, ctx: commands.Context, *, url: str = ""):
        """Set a custom bot thumbnail URL for help pages.

        Leave empty to use the bot's avatar. Use `off` to disable.
        """
        if url.lower() == "off":
            await self.config.guild(ctx.guild).show_thumbnail.set(False)
            await ctx.send("Thumbnails disabled.")
        elif url:
            await self.config.guild(ctx.guild).bot_thumbnail_url.set(url)
            await self.config.guild(ctx.guild).show_thumbnail.set(True)
            await ctx.send(f"Custom thumbnail set: {url}")
        else:
            await self.config.guild(ctx.guild).bot_thumbnail_url.set("")
            await self.config.guild(ctx.guild).show_thumbnail.set(True)
            await ctx.send("Thumbnail reset to bot avatar.")

    @cv2.command(name="compact")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_compact(self, ctx: commands.Context):
        """Toggle compact field rendering."""
        current = await self.config.guild(ctx.guild).compact_fields()
        new_val = not current
        await self.config.guild(ctx.guild).compact_fields.set(new_val)
        mode = "compact" if new_val else "expanded"
        await ctx.send(f"Field rendering mode: **{mode}**.")

    @cv2.command(name="footer")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_footer(self, ctx: commands.Context):
        """Toggle footer display on converted embeds."""
        current = await self.config.guild(ctx.guild).show_footer()
        new_val = not current
        await self.config.guild(ctx.guild).show_footer.set(new_val)
        status = "shown" if new_val else "hidden"
        await ctx.send(f"Footers: **{status}**.")

    # ── Categories ──

    @cv2.group(name="category", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_category(self, ctx: commands.Context):
        """Manage custom help categories."""
        categories = await self.config.guild(ctx.guild).categories()
        emojis = await self.config.guild(ctx.guild).category_emojis()

        if not categories:
            await ctx.send(
                f"No custom categories set. Cogs will be listed individually.\n"
                f"Use `{ctx.clean_prefix}cv2 category add <name> <cog1> [cog2]...` to create one."
            )
            return

        lines = []
        for cat, cogs in categories.items():
            emoji = emojis.get(cat, "📂")
            cog_list = ", ".join(cogs)
            lines.append(f"{emoji} **{cat}** → {cog_list}")

        await ctx.send("\n".join(lines))

    @cv2_category.command(name="add")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_category_add(self, ctx: commands.Context, name: str, *cogs: str):
        """Create or update a custom category.

        Example: `[p]cv2 category add Moderation Mod Warnings AutoMod`
        """
        if not cogs:
            await ctx.send("Provide at least one cog name.")
            return

        async with self.config.guild(ctx.guild).categories() as categories:
            categories[name] = list(cogs)

        await ctx.send(
            f"Category **{name}** set with cogs: {humanize_list(list(cogs))}\n"
            f"Set an emoji: `{ctx.clean_prefix}cv2 category emoji {name} 🛡️`"
        )

    @cv2_category.command(name="remove", aliases=["delete"])
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_category_remove(self, ctx: commands.Context, name: str):
        """Remove a custom category."""
        async with self.config.guild(ctx.guild).categories() as categories:
            if name in categories:
                del categories[name]
                async with self.config.guild(ctx.guild).category_emojis() as emojis:
                    emojis.pop(name, None)
                await ctx.send(f"Category **{name}** removed.")
            else:
                await ctx.send(f"Category **{name}** not found.")

    @cv2_category.command(name="emoji")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_category_emoji(self, ctx: commands.Context, name: str, emoji: str):
        """Set the emoji for a category.

        Example: `[p]cv2 category emoji Moderation 🛡️`
        """
        categories = await self.config.guild(ctx.guild).categories()
        if name not in categories:
            await ctx.send(f"Category **{name}** doesn't exist. Create it first.")
            return

        async with self.config.guild(ctx.guild).category_emojis() as emojis:
            emojis[name] = emoji

        await ctx.send(f"Emoji for **{name}** set to {emoji}")

    # ── Blacklist ──

    @cv2.group(name="blacklist", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_blacklist(self, ctx: commands.Context):
        """Manage blacklisted cogs/commands from help."""
        bl_cogs = await self.config.guild(ctx.guild).blacklisted_cogs()
        bl_cmds = await self.config.guild(ctx.guild).blacklisted_commands()

        parts = []
        if bl_cogs:
            parts.append(f"**Blacklisted cogs:** {humanize_list(bl_cogs)}")
        if bl_cmds:
            parts.append(f"**Blacklisted commands:** {humanize_list(bl_cmds)}")
        if not parts:
            parts.append("No blacklisted cogs or commands.")

        await ctx.send("\n".join(parts))

    @cv2_blacklist.command(name="cog")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_blacklist_cog(self, ctx: commands.Context, *, cog_name: str):
        """Add/remove a cog from the help blacklist."""
        async with self.config.guild(ctx.guild).blacklisted_cogs() as bl:
            if cog_name in bl:
                bl.remove(cog_name)
                await ctx.send(f"**{cog_name}** removed from help blacklist.")
            else:
                bl.append(cog_name)
                await ctx.send(f"**{cog_name}** added to help blacklist.")

    @cv2_blacklist.command(name="command")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_blacklist_command(self, ctx: commands.Context, *, command_name: str):
        """Add/remove a command from the help blacklist."""
        async with self.config.guild(ctx.guild).blacklisted_commands() as bl:
            if command_name in bl:
                bl.remove(command_name)
                await ctx.send(f"`{command_name}` removed from help blacklist.")
            else:
                bl.append(command_name)
                await ctx.send(f"`{command_name}` added to help blacklist.")

    # ── Settings overview ──

    @cv2.command(name="settings", aliases=["config", "status"])
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_settings(self, ctx: commands.Context):
        """View all current Components V2 settings."""
        s = await self.config.guild(ctx.guild).all()
        prefix = ctx.clean_prefix

        enabled_emoji = "✅" if s["enabled"] else "❌"
        help_emoji = "✅" if s["help_override"] else "❌"
        embed_emoji = "✅" if s["embed_override"] else "❌"
        menu_emoji = "✅" if s["menu_override"] else "❌"
        thumb_emoji = "✅" if s["show_thumbnail"] else "❌"
        footer_emoji = "✅" if s["show_footer"] else "❌"
        compact_emoji = "✅" if s["compact_fields"] else "❌"
        hidden_emoji = "✅" if s["show_hidden"] else "❌"
        dm_emoji = "📬" if s["help_in_dm"] else "💬"

        color_hex = f"#{s['accent_color']:06X}"
        cat_count = len(s["categories"])
        bl_cogs = len(s["blacklisted_cogs"])
        bl_cmds = len(s["blacklisted_commands"])
        cog_ov = len(s.get("cog_overrides", {}))

        if s["enabled"]:
            layout = ui.LayoutView()
            container = ui.Container(accent_colour=discord.Colour(s["accent_color"]))

            container.add_item(ui.TextDisplay("## ⚙️ Components V2 Settings"))
            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

            status_text = (
                f"{enabled_emoji} **Master Toggle:** {'On' if s['enabled'] else 'Off'}\n"
                f"{help_emoji} **Help Override:** {'On' if s['help_override'] else 'Off'}\n"
                f"{embed_emoji} **Embed Conversion:** {'On' if s['embed_override'] else 'Off'}\n"
                f"{menu_emoji} **Menu Override:** {'On' if s['menu_override'] else 'Off'}\n"
                f"🔧 **Override Mode:** `{s['override_mode']}`"
            )
            container.add_item(ui.TextDisplay(status_text))

            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

            appearance_text = (
                f"🎨 **Accent Colour:** `{color_hex}`\n"
                f"{thumb_emoji} **Thumbnails:** {'On' if s['show_thumbnail'] else 'Off'}\n"
                f"{footer_emoji} **Footers:** {'On' if s['show_footer'] else 'Off'}\n"
                f"{compact_emoji} **Compact Fields:** {'On' if s['compact_fields'] else 'Off'}\n"
                f"{dm_emoji} **Help Destination:** {'DMs' if s['help_in_dm'] else 'Channel'}\n"
                f"⏱️ **Help Timeout:** {s['help_timeout']}s\n"
                f"{hidden_emoji} **Show Hidden:** {'Yes' if s['show_hidden'] else 'No'}"
            )
            container.add_item(ui.TextDisplay(appearance_text))

            container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

            meta_text = (
                f"📂 **Categories:** {cat_count}\n"
                f"🚫 **Blacklisted Cogs:** {bl_cogs}\n"
                f"🚫 **Blacklisted Commands:** {bl_cmds}\n"
                f"🔀 **Per-Cog Overrides:** {cog_ov}"
            )
            container.add_item(ui.TextDisplay(meta_text))

            layout.add_item(container)
            await ctx.send(view=layout)
        else:
            embed = discord.Embed(
                title="⚙️ Components V2 Settings",
                colour=discord.Colour(s["accent_color"]),
            )
            embed.add_field(
                name="Toggles",
                value=(
                    f"{enabled_emoji} Master: Off\n"
                    f"{help_emoji} Help: {'On' if s['help_override'] else 'Off'}\n"
                    f"{embed_emoji} Embeds: {'On' if s['embed_override'] else 'Off'}\n"
                    f"{menu_emoji} Menus: {'On' if s['menu_override'] else 'Off'}"
                ),
                inline=True,
            )
            embed.add_field(
                name="Appearance",
                value=(
                    f"🎨 Colour: `{color_hex}`\n"
                    f"Mode: `{s['override_mode']}`\n"
                    f"Timeout: {s['help_timeout']}s"
                ),
                inline=True,
            )
            embed.set_footer(
                text=f"Enable with {prefix}cv2 toggle"
            )
            await ctx.send(embed=embed)

    @cv2.command(name="preview")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_preview(self, ctx: commands.Context):
        """Preview what Components V2 looks like with current settings."""
        s = await self.config.guild(ctx.guild).all()
        accent = s["accent_color"]
        bot_user = self.bot.user
        bot_name = bot_user.display_name if bot_user else "Bot"
        avatar_url = bot_user.display_avatar.url if bot_user else None

        layout = ui.LayoutView()

        header_container = ui.Container(accent_colour=discord.Colour(accent))

        if s["show_thumbnail"] and avatar_url:
            section = ui.Section(accessory=ui.Thumbnail(avatar_url))
            section.add_item(ui.TextDisplay(f"## {bot_name} — Preview"))
            section.add_item(
                ui.TextDisplay("This is what your help and embeds will look like.")
            )
            header_container.add_item(section)
        else:
            header_container.add_item(
                ui.TextDisplay(f"## {bot_name} — Preview\nThis is what your help and embeds will look like.")
            )

        header_container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        header_container.add_item(
            ui.TextDisplay(
                "**Field 1** — Inline\n"
                "Some value here"
            )
        )
        header_container.add_item(
            ui.TextDisplay(
                "**Field 2** — Inline\n"
                "Another value"
            )
        )

        if s["show_footer"]:
            header_container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
            header_container.add_item(ui.TextDisplay("-# Footer text · Just now"))

        layout.add_item(header_container)

        layout.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))
        nav_row = ui.ActionRow()
        nav_row.add_item(ui.Button(emoji="◀️", style=discord.ButtonStyle.primary, custom_id="preview_prev", disabled=True))
        nav_row.add_item(ui.Button(label="1/3", style=discord.ButtonStyle.secondary, custom_id="preview_ind", disabled=True))
        nav_row.add_item(ui.Button(emoji="▶️", style=discord.ButtonStyle.primary, custom_id="preview_next", disabled=True))
        nav_row.add_item(ui.Button(label="Close", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="preview_close", disabled=True))
        layout.add_item(nav_row)

        await ctx.send(view=layout)

    @cv2.command(name="reset")
    @checks.admin_or_permissions(manage_guild=True)
    async def cv2_reset(self, ctx: commands.Context):
        """Reset all Components V2 settings to defaults."""
        await self.config.guild(ctx.guild).clear()
        await ctx.send("✅ All Components V2 settings reset to defaults (disabled).")

    @cv2.command(name="version")
    async def cv2_version(self, ctx: commands.Context):
        """Show the cog version."""
        await ctx.send(f"**NewHelpMenu** v{self.__version__} by {self.__author__}")

    # ═══════════════════════════════════════════════════════════════
    #  PUBLIC API — Other cogs can use these
    # ═══════════════════════════════════════════════════════════════

    async def is_enabled(self, guild: Optional[discord.Guild]) -> bool:
        """Check if CV2 is enabled for a guild."""
        if guild is None:
            return False
        return await self.config.guild(guild).enabled()

    async def get_accent_color(self, guild: discord.Guild) -> int:
        """Get the accent colour for a guild."""
        return await self.config.guild(guild).accent_color()

    async def send_cv2_menu(
        self,
        ctx: commands.Context,
        pages: List[Any],
        *,
        timeout: float = 120.0,
    ) -> Optional[discord.Message]:
        """Send a CV2 paginated menu. Use this from other cogs!

        Parameters
        ----------
        ctx: The command context.
        pages: List of embeds, strings, or containers.
        timeout: Menu timeout in seconds.

        Returns
        -------
        The sent message, or None.
        """
        if not ctx.guild:
            return None

        accent = await self.config.guild(ctx.guild).accent_color()
        view = CV2MenuPaginator(
            pages,
            author_id=ctx.author.id,
            timeout=timeout,
            accent_color=accent,
        )
        msg = await ctx.send(view=view)
        view.message = msg
        self._active_views[msg.id] = view
        return msg
