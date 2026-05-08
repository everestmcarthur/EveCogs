"""NexusCore v2.0.0 — The ultimate all-in-one Red-DiscordBot cog.

Modules: Tickets, Applications, Suggestions, Reaction Roles, Giveaways,
Server Logging, Moderation, Economy, Embed Builder, Dashboard Integration.

100+ commands, persistent views, background tasks, full dashboard support.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Optional

import discord
from redbot.core import Config, commands, checks
from redbot.core.bot import Red

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    ts_full, duration_str, parse_duration, safe_send, safe_dm,
    ConfirmView, Paginator, chunk_list,
)
from .tickets import TicketsMixin
from .applications import ApplicationsMixin
from .suggestions import SuggestionsMixin
from .reactionroles import ReactionRolesMixin
from .giveaways import GiveawaysMixin
from .serverlog import ServerLogMixin, EVENT_TYPES
from .moderation import ModerationMixin
from .economy import EconomyMixin, ShopView, new_deck, bj_value, card_str
from .embedbuilder import EmbedBuilderMixin
from .dashboard_integration import DashboardMixin


class NexusCore(
    TicketsMixin,
    ApplicationsMixin,
    SuggestionsMixin,
    ReactionRolesMixin,
    GiveawaysMixin,
    ServerLogMixin,
    ModerationMixin,
    EconomyMixin,
    EmbedBuilderMixin,
    DashboardMixin,
    commands.Cog,
):
    """🔮 NexusCore — All-in-one server management mega-cog."""

    __version__ = "2.0.0"
    __author__ = "EveCogs"

    def __init__(self, bot: Red):
        self.bot = bot
        self._init_tickets(bot)
        self._init_applications(bot)
        self._init_suggestions(bot)
        self._init_reaction_roles(bot)
        self._init_giveaways(bot)
        self._init_serverlog(bot)
        self._init_moderation(bot)
        self._init_economy(bot)
        self._init_embed_builder(bot)
        try:
            self._init_dashboard(bot)
        except Exception:
            pass

    async def cog_load(self):
        self._bg_tasks = []
        self._bg_tasks.append(asyncio.create_task(self._start_auto_close_loop()))
        self._bg_tasks.append(asyncio.create_task(self._start_gw_loop()))
        self._bg_tasks.append(asyncio.create_task(self._warning_decay_loop()))
        self._bg_tasks.append(asyncio.create_task(self._income_role_loop()))
        self._bg_tasks.append(asyncio.create_task(self._scheduled_embed_loop()))
        await self._load_rr_panels()
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    async def cog_unload(self):
        for task in self._bg_tasks:
            task.cancel()

    # ══════════════════════════════════════════════════════════════════════════
    # LISTENERS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        await self._update_ticket_activity(message)
        await self._check_automod(message)
        self._cache_message(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
        await self._log_message_delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot:
            return
        await self._log_message_edit(before, after)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        await self._log_bulk_delete(messages)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._log_member_join(member)
        await self._check_raid(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._log_member_leave(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        await self._log_member_update(before, after)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self._log_member_ban(guild, user)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await self._log_member_unban(guild, user)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self._log_channel_create(channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self._log_channel_delete(channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        await self._log_channel_update(before, after)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self._log_role_create(role)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self._log_role_delete(role)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        await self._log_role_update(before, after)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self._log_voice_update(member, before, after)

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        await self._log_invite_create(invite)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        await self._log_invite_delete(invite)

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        await self._log_thread_create(thread)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        await self._log_thread_delete(thread)

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        await self._log_thread_update(before, after)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        await self._log_guild_update(before, after)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id:
            await self._handle_reaction_add(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id:
            await self._handle_reaction_remove(payload)

    # ══════════════════════════════════════════════════════════════════════════
    # NEXUS — TOP LEVEL GROUP
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="nexus", aliases=["nx"])
    @commands.guild_only()
    async def nexus(self, ctx: commands.Context):
        """🔮 NexusCore — All-in-one server management."""
        if ctx.invoked_subcommand is None:
            modules = [
                ("🎫 Tickets", "`[p]ticket`"),
                ("📋 Applications", "`[p]apply`"),
                ("💡 Suggestions", "`[p]suggest`"),
                ("🎭 Reaction Roles", "`[p]roles`"),
                ("🎉 Giveaways", "`[p]giveaway`"),
                ("📋 Server Logging", "`[p]serverlog`"),
                ("🛡️ Moderation", "`[p]nmod`"),
                ("🪙 Economy", "`[p]eco`"),
                ("📨 Embed Builder", "`[p]embedbuilder`"),
            ]
            embed = discord.Embed(
                title="🔮 NexusCore v2.0.0",
                description="All-in-one server management with 100+ commands.",
                colour=Clr.PRIMARY,
            )
            for name, cmd in modules:
                embed.add_field(name=name, value=cmd, inline=True)
            embed.set_footer(text="Use [p]help <command> for details")
            await ctx.send(embed=embed)

    @nexus.command(name="version")
    async def nx_version(self, ctx):
        """Show NexusCore version."""
        embed = discord.Embed(
            title="🔮 NexusCore",
            description=f"**Version:** {self.__version__}\n**Author:** {self.__author__}\n**Modules:** 10\n**Commands:** 100+",
            colour=Clr.PRIMARY,
        )
        await ctx.send(embed=embed)

    @nexus.command(name="stats")
    @checks.admin_or_permissions(manage_guild=True)
    async def nx_stats(self, ctx):
        """Show NexusCore statistics."""
        embed = discord.Embed(title="🔮 NexusCore Stats", colour=Clr.PRIMARY)

        # Tickets
        td = await self.ticket_config.guild(ctx.guild).all()
        open_t = sum(1 for t in td["open_tickets"].values() if not t.get("closed"))
        embed.add_field(name="🎫 Tickets", value=f"Open: {open_t} · Total: {td['counter']}", inline=True)

        # Apps
        ad = await self.app_config.guild(ctx.guild).all()
        pending_a = sum(1 for s in ad["submissions"].values() if s["status"] == "pending")
        embed.add_field(name="📋 Applications", value=f"Pending: {pending_a} · Total: {len(ad['submissions'])}", inline=True)

        # Suggestions
        sd = await self.suggest_config.guild(ctx.guild).all()
        embed.add_field(name="💡 Suggestions", value=f"Total: {sd['counter']}", inline=True)

        # RR
        rrd = await self.rr_config.guild(ctx.guild).panels()
        embed.add_field(name="🎭 Role Panels", value=str(len(rrd)), inline=True)

        # Giveaways
        gd = await self.give_config.guild(ctx.guild).all()
        active_gw = sum(1 for g in gd["giveaways"].values() if not g["ended"])
        embed.add_field(name="🎉 Giveaways", value=f"Active: {active_gw}", inline=True)

        # Mod
        md = await self.mod_config.guild(ctx.guild).all()
        embed.add_field(name="🛡️ Cases", value=str(md["case_counter"]), inline=True)

        # Economy
        ed = await self.eco_config.guild(ctx.guild).all()
        embed.add_field(name="🪙 Economy", value=f"{ed['currency_emoji']} {ed['currency_name']} · {len(ed.get('shop_items', {}))} items", inline=True)

        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # TICKETS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="ticket", aliases=["tickets"])
    @commands.guild_only()
    async def ticket(self, ctx: commands.Context):
        """🎫 Ticket system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticket.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_setup(self, ctx, category: discord.CategoryChannel, log_channel: discord.TextChannel):
        """Setup the ticket system."""
        await self.ticket_config.guild(ctx.guild).enabled.set(True)
        await self.ticket_config.guild(ctx.guild).category_id.set(category.id)
        await self.ticket_config.guild(ctx.guild).log_channel.set(log_channel.id)
        await ctx.send(embed=ok_embed(f"Tickets enabled!\nCategory: {category.mention}\nLog: {log_channel.mention}"))

    @ticket.command(name="panel")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_panel(self, ctx, channel: discord.TextChannel = None):
        """Send a ticket creation panel."""
        channel = channel or ctx.channel
        embed = discord.Embed(
            title="🎫 Support Tickets",
            description="Click the button below to create a ticket.\nA staff member will assist you shortly.",
            colour=Clr.TICKET,
        )
        embed.set_footer(text="NexusCore Ticket System")
        await channel.send(embed=embed, view=self._ticket_panel_view)
        await ctx.send(embed=ok_embed(f"Panel sent to {channel.mention}"))

    @ticket.command(name="addcategory")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_addcategory(self, ctx, name: str, *, description: str = ""):
        """Add a ticket category."""
        async with self.ticket_config.guild(ctx.guild).categories() as cats:
            cats[name.lower()] = {
                "description": description, "roles": [],
                "questions": [], "emoji": "🎫",
                "channel_name_fmt": None, "greeting": None,
                "default_priority": "medium",
            }
        await ctx.send(embed=ok_embed(f"Category **{name}** added."))

    @ticket.command(name="addquestion")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_addquestion(self, ctx, category: str, *, question: str):
        """Add a question to a ticket category."""
        async with self.ticket_config.guild(ctx.guild).categories() as cats:
            cat = cats.get(category.lower())
            if not cat:
                return await ctx.send(embed=err_embed("Category not found."))
            cat.setdefault("questions", []).append(question)
        await ctx.send(embed=ok_embed(f"Question added to **{category}**."))

    @ticket.command(name="addrole")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_addrole(self, ctx, category: str, role: discord.Role):
        """Add a staff role to a ticket category."""
        async with self.ticket_config.guild(ctx.guild).categories() as cats:
            cat = cats.get(category.lower())
            if not cat:
                return await ctx.send(embed=err_embed("Category not found."))
            cat.setdefault("roles", []).append(role.id)
        await ctx.send(embed=ok_embed(f"{role.mention} added to **{category}**."))

    @ticket.command(name="transcript")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_transcript(self, ctx, channel: discord.TextChannel):
        """Set the transcript channel."""
        await self.ticket_config.guild(ctx.guild).transcript_channel.set(channel.id)
        await ctx.send(embed=ok_embed(f"Transcripts → {channel.mention}"))

    @ticket.command(name="archive")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_archive(self, ctx, category: discord.CategoryChannel):
        """Set archive category (closed tickets move here instead of being deleted)."""
        await self.ticket_config.guild(ctx.guild).archive_channel.set(category.id)
        await ctx.send(embed=ok_embed(f"Archive category → {category.mention}"))

    @ticket.command(name="autoclose")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_autoclose(self, ctx, hours: int):
        """Set auto-close inactivity timer (0 = disabled)."""
        await self.ticket_config.guild(ctx.guild).auto_close_hours.set(hours)
        await ctx.send(embed=ok_embed(f"Auto-close: {hours}h" if hours else "Auto-close disabled."))

    @ticket.command(name="maxperuser")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_maxperuser(self, ctx, count: int):
        """Set max open tickets per user."""
        await self.ticket_config.guild(ctx.guild).max_per_user.set(count)
        await ctx.send(embed=ok_embed(f"Max per user: {count}"))

    @ticket.command(name="addtag")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_addtag(self, ctx, name: str, *, description: str = ""):
        """Add a ticket tag."""
        async with self.ticket_config.guild(ctx.guild).tags() as tags:
            tags[name.lower()] = {"description": description, "colour": Clr.TICKET.value}
        await ctx.send(embed=ok_embed(f"Tag **{name}** added."))

    @ticket.command(name="add")
    @checks.mod_or_permissions(manage_channels=True)
    async def ticket_add(self, ctx, user: discord.Member):
        """Add a user to the current ticket."""
        success = await self._add_user_to_ticket(ctx, user)
        if not success:
            await ctx.send(embed=err_embed("This isn't a ticket channel."))

    @ticket.command(name="remove")
    @checks.mod_or_permissions(manage_channels=True)
    async def ticket_remove(self, ctx, user: discord.Member):
        """Remove a user from the current ticket."""
        success = await self._remove_user_from_ticket(ctx, user)
        if not success:
            await ctx.send(embed=err_embed("This isn't a ticket channel."))

    @ticket.command(name="rename")
    @checks.mod_or_permissions(manage_channels=True)
    async def ticket_rename(self, ctx, *, new_name: str):
        """Rename the current ticket channel."""
        success = await self._rename_ticket(ctx, new_name)
        if success:
            await ctx.send(embed=ok_embed(f"Renamed to **{new_name}**"))
        else:
            await ctx.send(embed=err_embed("Not a ticket or renaming disabled."))

    @ticket.command(name="reopen")
    @checks.mod_or_permissions(manage_channels=True)
    async def ticket_reopen(self, ctx, channel: discord.TextChannel = None):
        """Reopen a closed ticket."""
        channel = channel or ctx.channel
        success = await self._reopen_ticket(ctx, channel)
        if not success:
            await ctx.send(embed=err_embed("Not a closed ticket or reopen is disabled."))

    @ticket.command(name="close")
    async def ticket_close_cmd(self, ctx):
        """Close the current ticket."""
        from .tickets import TicketControlView
        class _FI:
            guild = ctx.guild
            user = ctx.author
            channel = ctx.channel
            async def response_send_message(self, *a, **k): await ctx.send(*a, **k)
            response = type("R", (), {"send_message": lambda s, *a, **k: ctx.send(*a, **k), "defer": lambda s: None})()
            async def followup_send(self, *a, **k): await ctx.send(*a, **k)
            followup = type("F", (), {"send": lambda s, *a, **k: ctx.send(*a, **k)})()
        fake = _FI()
        fake.guild = ctx.guild
        fake.user = ctx.author
        fake.channel = ctx.channel
        await self._close_ticket(fake)

    @ticket.command(name="blacklist")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_blacklist(self, ctx, user: discord.Member):
        """Toggle blacklist a user from creating tickets."""
        async with self.ticket_config.guild(ctx.guild).blacklisted() as bl:
            if user.id in bl:
                bl.remove(user.id)
                await ctx.send(embed=ok_embed(f"{user.mention} unblacklisted."))
            else:
                bl.append(user.id)
                await ctx.send(embed=ok_embed(f"{user.mention} blacklisted from tickets."))

    @ticket.command(name="stats")
    @checks.mod_or_permissions(manage_channels=True)
    async def ticket_stats(self, ctx):
        """View ticket statistics."""
        closed = await self.ticket_config.guild(ctx.guild).closed_tickets()
        stats = self._get_ticket_stats(closed)
        embed = discord.Embed(title="🎫 Ticket Statistics", colour=Clr.TICKET)
        embed.add_field(name="Total Closed", value=str(stats["total"]), inline=True)
        embed.add_field(name="Avg First Response", value=stats.get("avg_first_response", "N/A"), inline=True)
        if stats.get("categories"):
            cats = "\n".join(f"**{k}:** {v}" for k, v in stats["categories"].items())
            embed.add_field(name="By Category", value=cats, inline=False)
        await ctx.send(embed=embed)

    @ticket.command(name="settings")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_settings(self, ctx):
        """View ticket settings."""
        data = await self.ticket_config.guild(ctx.guild).all()
        embed = discord.Embed(title="🎫 Ticket Settings", colour=Clr.TICKET)
        embed.add_field(name="Enabled", value="✅" if data["enabled"] else "❌", inline=True)
        embed.add_field(name="Max Per User", value=str(data["max_per_user"]), inline=True)
        embed.add_field(name="Auto-Close", value=f"{data['auto_close_hours']}h" if data["auto_close_hours"] else "Off", inline=True)
        embed.add_field(name="Claim", value="✅" if data["claim_enabled"] else "❌", inline=True)
        embed.add_field(name="Feedback", value="✅" if data["feedback_enabled"] else "❌", inline=True)
        embed.add_field(name="DM On Open", value="✅" if data["dm_on_open"] else "❌", inline=True)
        cats = data.get("categories", {})
        if cats:
            embed.add_field(name="Categories", value=", ".join(cats.keys()), inline=False)
        tags = data.get("tags", {})
        if tags:
            embed.add_field(name="Tags", value=", ".join(tags.keys()), inline=False)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # APPLICATIONS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="apply", aliases=["application", "apps"])
    @commands.guild_only()
    async def apply(self, ctx: commands.Context):
        """📋 Application system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @apply.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_setup(self, ctx, review_channel: discord.TextChannel):
        """Setup the application system."""
        await self.app_config.guild(ctx.guild).enabled.set(True)
        await self.app_config.guild(ctx.guild).review_channel.set(review_channel.id)
        await ctx.send(embed=ok_embed(f"Applications enabled! Review → {review_channel.mention}"))

    @apply.command(name="panel")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_panel(self, ctx, channel: discord.TextChannel = None):
        """Send an application panel."""
        channel = channel or ctx.channel
        embed = discord.Embed(
            title="📋 Applications",
            description="Click below to apply!",
            colour=Clr.APP,
        )
        await channel.send(embed=embed, view=self._app_panel_view)
        await ctx.send(embed=ok_embed(f"Panel sent to {channel.mention}"))

    @apply.command(name="addtype")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_addtype(self, ctx, name: str, *, description: str = ""):
        """Add an application type."""
        async with self.app_config.guild(ctx.guild).types() as types:
            types[name.lower()] = {
                "description": description, "enabled": True, "emoji": "📋",
                "questions": [{"label": "Why are you applying?", "style": "long"}],
                "role_on_accept": None, "role_on_deny": None,
                "review_channel": None, "cooldown": None,
                "accept_msg": None, "deny_msg": None,
                "auto_thread": False,
                "require_account_age_days": 0, "require_server_days": 0,
            }
        await ctx.send(embed=ok_embed(f"Type **{name}** added. Add questions: `[p]apply addquestion {name} <question>`"))

    @apply.command(name="addquestion")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_addquestion(self, ctx, type_name: str, *, question: str):
        """Add a question to an application type."""
        async with self.app_config.guild(ctx.guild).types() as types:
            td = types.get(type_name.lower())
            if not td:
                return await ctx.send(embed=err_embed("Type not found."))
            td.setdefault("questions", []).append({"label": question, "style": "long"})
        await ctx.send(embed=ok_embed(f"Question added to **{type_name}**."))

    @apply.command(name="setrole")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_setrole(self, ctx, type_name: str, accept_role: discord.Role, deny_role: discord.Role = None):
        """Set roles given on accept/deny."""
        async with self.app_config.guild(ctx.guild).types() as types:
            td = types.get(type_name.lower())
            if not td:
                return await ctx.send(embed=err_embed("Type not found."))
            td["role_on_accept"] = accept_role.id
            if deny_role:
                td["role_on_deny"] = deny_role.id
        await ctx.send(embed=ok_embed(f"Roles set for **{type_name}**."))

    @apply.command(name="voting")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_voting(self, ctx, enabled: bool, threshold: int = 3):
        """Enable/disable voting on applications."""
        await self.app_config.guild(ctx.guild).voting_enabled.set(enabled)
        await self.app_config.guild(ctx.guild).voting_threshold.set(threshold)
        await ctx.send(embed=ok_embed(f"Voting {'enabled' if enabled else 'disabled'} (threshold: {threshold})"))

    @apply.command(name="webhook")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_webhook(self, ctx, url: str):
        """Set a webhook URL for application notifications."""
        await self.app_config.guild(ctx.guild).webhook_url.set(url)
        await ctx.send(embed=ok_embed("Webhook URL set."))

    @apply.command(name="bulk")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_bulk(self, ctx, type_name: str = None):
        """Bulk accept/deny pending applications."""
        data = await self.app_config.guild(ctx.guild).all()
        pending = {k: v for k, v in data["submissions"].items() if v["status"] == "pending"}
        if type_name:
            pending = {k: v for k, v in pending.items() if v["type"] == type_name.lower()}
        if not pending:
            return await ctx.send(embed=info_embed("No pending applications."))
        from .applications import BulkActionView
        view = BulkActionView(self, list(pending.keys()))
        await ctx.send(f"**{len(pending)}** pending applications. Choose action:", view=view)

    @apply.command(name="savetemplate")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_savetemplate(self, ctx, type_name: str, template_name: str):
        """Save an application type as a template."""
        success = await self._save_app_template(ctx.guild, template_name, type_name.lower())
        if success:
            await ctx.send(embed=ok_embed(f"Template **{template_name}** saved."))
        else:
            await ctx.send(embed=err_embed("Type not found."))

    @apply.command(name="loadtemplate")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_loadtemplate(self, ctx, template_name: str, type_name: str):
        """Load a template into an application type."""
        success = await self._load_app_template(ctx.guild, template_name, type_name.lower())
        if success:
            await ctx.send(embed=ok_embed(f"Template **{template_name}** → **{type_name}**"))
        else:
            await ctx.send(embed=err_embed("Template not found."))

    @apply.command(name="stats")
    @checks.mod_or_permissions(manage_messages=True)
    async def apply_stats(self, ctx):
        """View application statistics."""
        data = await self.app_config.guild(ctx.guild).all()
        stats = self._get_app_stats(data)
        embed = discord.Embed(title="📋 Application Stats", colour=Clr.APP)
        embed.add_field(name="Total", value=str(stats["total"]), inline=True)
        for status, count in stats["by_status"].items():
            embed.add_field(name=status.title(), value=str(count), inline=True)
        s = stats.get("stats", {})
        if s.get("avg_review_time"):
            embed.add_field(name="Avg Review Time", value=duration_str(s["avg_review_time"]), inline=True)
        await ctx.send(embed=embed)

    @apply.command(name="settings")
    @checks.admin_or_permissions(manage_guild=True)
    async def apply_settings(self, ctx):
        """View application settings."""
        data = await self.app_config.guild(ctx.guild).all()
        embed = discord.Embed(title="📋 Application Settings", colour=Clr.APP)
        embed.add_field(name="Enabled", value="✅" if data["enabled"] else "❌", inline=True)
        embed.add_field(name="Voting", value="✅" if data.get("voting_enabled") else "❌", inline=True)
        embed.add_field(name="DM Results", value="✅" if data["dm_results"] else "❌", inline=True)
        types = data.get("types", {})
        if types:
            embed.add_field(name="Types", value=", ".join(types.keys()), inline=False)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # SUGGESTIONS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="suggest", aliases=["suggestion", "suggestions"])
    @commands.guild_only()
    async def suggest(self, ctx: commands.Context):
        """💡 Suggestion system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @suggest.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def suggest_setup(self, ctx, channel: discord.TextChannel):
        """Setup the suggestion system."""
        await self.suggest_config.guild(ctx.guild).enabled.set(True)
        await self.suggest_config.guild(ctx.guild).channel.set(channel.id)
        await ctx.send(embed=ok_embed(f"Suggestions enabled! Channel: {channel.mention}"))

    @suggest.command(name="panel")
    @checks.admin_or_permissions(manage_guild=True)
    async def suggest_panel(self, ctx, channel: discord.TextChannel = None):
        """Send a suggestion panel."""
        channel = channel or ctx.channel
        embed = discord.Embed(
            title="💡 Suggestions", description="Submit your ideas!",
            colour=Clr.SUGGEST,
        )
        await channel.send(embed=embed, view=self._suggest_panel_view)
        await ctx.send(embed=ok_embed(f"Panel sent to {channel.mention}"))

    @suggest.command(name="new")
    async def suggest_new(self, ctx, *, content: str):
        """Submit a suggestion via command."""
        class _FI:
            guild = ctx.guild
            user = ctx.author
            async def response_defer(self, **k): pass
            response = type("R", (), {"defer": lambda s, **k: None})()
            async def followup_send(self, *a, **k): await ctx.send(*a, **k)
            followup = type("F", (), {"send": lambda s, *a, **k: ctx.send(*a, **k)})()
        fake = _FI()
        fake.guild = ctx.guild
        fake.user = ctx.author
        await self._create_suggestion(fake, content)
        await ctx.send(embed=ok_embed("Suggestion submitted!"))

    @suggest.command(name="status")
    @checks.mod_or_permissions(manage_messages=True)
    async def suggest_status(self, ctx, suggestion_id: str, *, status: str):
        """Set suggestion status."""
        from .suggestions import STATUS_MAP
        if status.lower() not in STATUS_MAP:
            valid = ", ".join(STATUS_MAP.keys())
            return await ctx.send(embed=err_embed(f"Valid statuses: {valid}"))
        class _FI:
            guild = ctx.guild
            user = ctx.author
            async def response_send_message(self, *a, **k): await ctx.send(*a, **k)
            response = type("R", (), {"send_message": lambda s, *a, **k: ctx.send(*a, **k)})()
        await self._set_status(_FI(), suggestion_id, status.lower())

    @suggest.command(name="respond")
    @checks.mod_or_permissions(manage_messages=True)
    async def suggest_respond(self, ctx, suggestion_id: str, *, response: str):
        """Add a staff response to a suggestion."""
        conf = self.suggest_config.guild(ctx.guild)
        async with conf.suggestions() as subs:
            s = subs.get(suggestion_id)
            if not s:
                return await ctx.send(embed=err_embed("Not found."))
            s["staff_response"] = response
            s.setdefault("staff_responses", []).append({
                "text": response, "author": ctx.author.id, "at": ts_now()
            })
        data = await conf.all()
        channel = ctx.guild.get_channel(data["channel"])
        if channel and s.get("message_id"):
            try:
                msg = await channel.fetch_message(s["message_id"])
                if msg.embeds:
                    embed = msg.embeds[0]
                    embed.add_field(name=f"Staff Response — {ctx.author.display_name}", value=response[:1024], inline=False)
                    await msg.edit(embed=embed)
            except discord.HTTPException:
                pass
        await ctx.send(embed=ok_embed("Response added."))

    @suggest.command(name="edit")
    async def suggest_edit(self, ctx, suggestion_id: str):
        """Edit your suggestion (within edit window)."""
        data = await self.suggest_config.guild(ctx.guild).all()
        s = data["suggestions"].get(suggestion_id)
        if not s:
            return await ctx.send(embed=err_embed("Not found."))
        if s["user_id"] != ctx.author.id:
            return await ctx.send(embed=err_embed("You can only edit your own suggestions."))
        from .suggestions import EditSuggestionModal
        # Can't send modal from a prefix command; give instructions
        await ctx.send(embed=info_embed(f"To edit, use the suggestion panel button or DM-reply feature. Edit window: {data.get('edit_window', 300)}s."))

    @suggest.command(name="merge")
    @checks.mod_or_permissions(manage_messages=True)
    async def suggest_merge(self, ctx, target_id: str, source_id: str):
        """Merge a duplicate suggestion into another."""
        success = await self._merge_suggestions(ctx.guild, target_id, source_id)
        if success:
            await ctx.send(embed=ok_embed(f"Suggestion #{source_id} merged into #{target_id}."))
        else:
            await ctx.send(embed=err_embed("One or both suggestions not found."))

    @suggest.command(name="tag")
    @checks.mod_or_permissions(manage_messages=True)
    async def suggest_tag(self, ctx, suggestion_id: str, *, tag: str):
        """Add a tag to a suggestion."""
        success = await self._tag_suggestion(ctx.guild, suggestion_id, tag.lower())
        if success:
            await ctx.send(embed=ok_embed(f"Tag **{tag}** added."))
        else:
            await ctx.send(embed=err_embed("Not found."))

    @suggest.command(name="addcategory")
    @checks.admin_or_permissions(manage_guild=True)
    async def suggest_addcategory(self, ctx, *, category: str):
        """Add a suggestion category."""
        async with self.suggest_config.guild(ctx.guild).categories() as cats:
            if category.lower() not in cats:
                cats.append(category.lower())
        await ctx.send(embed=ok_embed(f"Category **{category}** added."))

    @suggest.command(name="stats")
    @checks.mod_or_permissions(manage_messages=True)
    async def suggest_stats(self, ctx):
        """View suggestion statistics."""
        data = await self.suggest_config.guild(ctx.guild).all()
        stats = self._get_suggestion_stats(data)
        embed = discord.Embed(title="💡 Suggestion Stats", colour=Clr.SUGGEST)
        embed.add_field(name="Total", value=str(stats["total"]), inline=True)
        embed.add_field(name="Total Upvotes", value=str(stats["total_upvotes"]), inline=True)
        embed.add_field(name="Total Downvotes", value=str(stats["total_downvotes"]), inline=True)
        for status, count in stats["by_status"].items():
            embed.add_field(name=status.title(), value=str(count), inline=True)
        await ctx.send(embed=embed)

    @suggest.command(name="settings")
    @checks.admin_or_permissions(manage_guild=True)
    async def suggest_settings(self, ctx):
        """View suggestion settings."""
        data = await self.suggest_config.guild(ctx.guild).all()
        embed = discord.Embed(title="💡 Suggestion Settings", colour=Clr.SUGGEST)
        ch = ctx.guild.get_channel(data["channel"]) if data["channel"] else None
        embed.add_field(name="Enabled", value="✅" if data["enabled"] else "❌", inline=True)
        embed.add_field(name="Channel", value=ch.mention if ch else "Not set", inline=True)
        embed.add_field(name="Anonymous", value="✅" if data["anonymous_allowed"] else "❌", inline=True)
        embed.add_field(name="Auto Thread", value="✅" if data["auto_thread"] else "❌", inline=True)
        embed.add_field(name="Button Voting", value="✅" if data["voting_buttons"] else "❌", inline=True)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # REACTION ROLES
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="roles", aliases=["rr", "reactionroles"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def roles(self, ctx: commands.Context):
        """🎭 Reaction role panels."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @roles.command(name="create")
    async def rr_create(self, ctx, channel: discord.TextChannel, mode: str, *, title: str):
        """Create a role panel: [p]roles create #channel button My Panel Title
        Modes: button, select, reaction"""
        if mode not in ("button", "select", "reaction"):
            return await ctx.send(embed=err_embed("Mode must be `button`, `select`, or `reaction`."))
        panel_id = await self._create_rr_panel(ctx, channel, title, "Select your roles below!", mode)
        await ctx.send(embed=ok_embed(f"Panel created! ID: `{panel_id}`\nNow add roles: `[p]roles add {panel_id} @Role`"))

    @roles.command(name="add")
    async def rr_add(self, ctx, panel_id: str, role: discord.Role, emoji: str = None, *, label: str = None):
        """Add a role to a panel."""
        success = await self._add_role_to_panel(ctx.guild, panel_id, role, label=label, emoji=emoji)
        if success:
            await ctx.send(embed=ok_embed(f"**{role.name}** added to panel `{panel_id}`"))
        else:
            await ctx.send(embed=err_embed("Panel not found."))

    @roles.command(name="exclusive")
    async def rr_exclusive(self, ctx, panel_id: str, group_name: str, max_picks: int = 1):
        """Make a group exclusive: [p]roles exclusive panel_id colours 1"""
        async with self.rr_config.guild(ctx.guild).panels() as panels:
            panel = panels.get(panel_id)
            if not panel:
                return await ctx.send(embed=err_embed("Panel not found."))
            panel.setdefault("exclusive_groups", {})[group_name] = max_picks
        await ctx.send(embed=ok_embed(f"Group **{group_name}** is exclusive (max {max_picks})."))

    @roles.command(name="setgroup")
    async def rr_setgroup(self, ctx, panel_id: str, role: discord.Role, group_name: str):
        """Assign a role on a panel to a group."""
        async with self.rr_config.guild(ctx.guild).panels() as panels:
            panel = panels.get(panel_id)
            if not panel:
                return await ctx.send(embed=err_embed("Panel not found."))
            for r in panel.get("roles", []):
                if r["role_id"] == role.id:
                    r["group"] = group_name
                    break
        await self._refresh_rr_panel(ctx.guild, panel_id)
        await ctx.send(embed=ok_embed(f"**{role.name}** → group **{group_name}**"))

    @roles.command(name="maxroles")
    async def rr_maxroles(self, ctx, panel_id: str, count: int):
        """Set max roles a user can pick from a panel."""
        async with self.rr_config.guild(ctx.guild).panels() as panels:
            if panel_id not in panels:
                return await ctx.send(embed=err_embed("Panel not found."))
            panels[panel_id]["max_roles"] = count
        await ctx.send(embed=ok_embed(f"Max roles: {count}"))

    @roles.command(name="sticky")
    async def rr_sticky(self, ctx, panel_id: str):
        """Toggle sticky mode (roles can't be removed)."""
        async with self.rr_config.guild(ctx.guild).panels() as panels:
            if panel_id not in panels:
                return await ctx.send(embed=err_embed("Panel not found."))
            panels[panel_id]["sticky"] = not panels[panel_id].get("sticky", False)
            sticky = panels[panel_id]["sticky"]
        await ctx.send(embed=ok_embed(f"Sticky mode {'enabled' if sticky else 'disabled'}"))

    @roles.command(name="temp")
    async def rr_temp(self, ctx, panel_id: str, minutes: int):
        """Set temporary role duration (0 = permanent)."""
        async with self.rr_config.guild(ctx.guild).panels() as panels:
            if panel_id not in panels:
                return await ctx.send(embed=err_embed("Panel not found."))
            panels[panel_id]["temp_minutes"] = minutes
        await ctx.send(embed=ok_embed(f"Temp role: {minutes}m" if minutes else "Roles are now permanent"))

    @roles.command(name="require")
    async def rr_require(self, ctx, panel_id: str, role: discord.Role):
        """Require a role to use a panel."""
        async with self.rr_config.guild(ctx.guild).panels() as panels:
            if panel_id not in panels:
                return await ctx.send(embed=err_embed("Panel not found."))
            panels[panel_id]["require_role"] = role.id
        await ctx.send(embed=ok_embed(f"Panel `{panel_id}` requires {role.mention}"))

    @roles.command(name="clone")
    async def rr_clone(self, ctx, panel_id: str, channel: discord.TextChannel):
        """Clone a role panel to another channel."""
        new_id = await self._clone_panel(ctx.guild, panel_id, channel)
        if new_id:
            await ctx.send(embed=ok_embed(f"Cloned! New panel ID: `{new_id}`"))
        else:
            await ctx.send(embed=err_embed("Panel not found."))

    @roles.command(name="verify")
    async def rr_verify(self, ctx, channel: discord.TextChannel, role: discord.Role, *, title: str = "Verification"):
        """Create a verification panel."""
        vpid = await self._create_verification_panel(ctx, channel, role, title=title)
        await ctx.send(embed=ok_embed(f"Verification panel created! ID: `{vpid}`"))

    @roles.command(name="list")
    async def rr_list(self, ctx):
        """List all role panels."""
        panels = await self.rr_config.guild(ctx.guild).panels()
        if not panels:
            return await ctx.send(embed=info_embed("No role panels."))
        embed = discord.Embed(title="🎭 Role Panels", colour=Clr.ROLES)
        for pid, p in panels.items():
            ch = ctx.guild.get_channel(p["channel_id"])
            embed.add_field(
                name=f"`{pid}` — {p.get('title', 'Untitled')}",
                value=f"Mode: {p.get('mode', '?')} · Roles: {len(p.get('roles', []))} · Channel: {ch.mention if ch else '?'}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @roles.command(name="delete")
    async def rr_delete(self, ctx, panel_id: str):
        """Delete a role panel."""
        async with self.rr_config.guild(ctx.guild).panels() as panels:
            if panel_id not in panels:
                return await ctx.send(embed=err_embed("Panel not found."))
            panel = panels.pop(panel_id)
        ch = ctx.guild.get_channel(panel["channel_id"])
        if ch and panel.get("message_id"):
            try:
                msg = await ch.fetch_message(panel["message_id"])
                await msg.delete()
            except discord.HTTPException:
                pass
        await ctx.send(embed=ok_embed(f"Panel `{panel_id}` deleted."))

    @roles.command(name="stats")
    async def rr_stats(self, ctx):
        """View reaction role stats."""
        stats = await self.rr_config.guild(ctx.guild).stats()
        if not stats:
            return await ctx.send(embed=info_embed("No role stats yet."))
        embed = discord.Embed(title="🎭 Role Stats", colour=Clr.ROLES)
        for rid, data in list(stats.items())[:20]:
            role = ctx.guild.get_role(int(rid))
            name = role.name if role else f"ID:{rid}"
            embed.add_field(name=name, value=f"➕ {data.get('added', 0)} · ➖ {data.get('removed', 0)}", inline=True)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # GIVEAWAYS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="giveaway", aliases=["gw"])
    @commands.guild_only()
    async def giveaway(self, ctx: commands.Context):
        """🎉 Giveaway system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @giveaway.command(name="start")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_start(self, ctx, channel: discord.TextChannel, duration: str, winners: int, *, prize: str):
        """Start a giveaway: [p]gw start #channel 1d 1 Nitro Classic"""
        dur = parse_duration(duration)
        if not dur:
            return await ctx.send(embed=err_embed("Invalid duration. Use e.g. `1d`, `12h`, `30m`."))
        gw_id = await self._create_giveaway(ctx, channel, prize, dur, winners)
        await ctx.send(embed=ok_embed(f"Giveaway started! ID: `{gw_id}`"))

    @giveaway.command(name="drop")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_drop(self, ctx, channel: discord.TextChannel, winners: int, *, prize: str):
        """Start a drop giveaway (first N to click win)."""
        gw_id = await self._create_giveaway(ctx, channel, prize, 86400, winners, drop_mode=True)
        await ctx.send(embed=ok_embed(f"Drop giveaway started! ID: `{gw_id}`"))

    @giveaway.command(name="end")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_end(self, ctx, gw_id: str):
        """End a giveaway early."""
        await self._end_giveaway(ctx.guild, gw_id)
        await ctx.send(embed=ok_embed("Giveaway ended."))

    @giveaway.command(name="reroll")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_reroll_cmd(self, ctx, gw_id: str):
        """Reroll a giveaway winner."""
        class _FI:
            guild = ctx.guild
            user = ctx.author
            async def response_send_message(s, *a, **k): await ctx.send(*a, **k)
            response = type("R", (), {"send_message": lambda s, *a, **k: ctx.send(*a, **k)})()
        await self._reroll_giveaway(_FI(), gw_id)

    @giveaway.command(name="list")
    async def gw_list(self, ctx):
        """List active giveaways."""
        data = await self.give_config.guild(ctx.guild).all()
        active = {k: v for k, v in data["giveaways"].items() if not v["ended"]}
        if not active:
            return await ctx.send(embed=info_embed("No active giveaways."))
        embed = discord.Embed(title="🎉 Active Giveaways", colour=Clr.GIVE)
        for gid, gw in active.items():
            embed.add_field(
                name=f"`{gid}` — {gw['prize']}",
                value=f"Ends: {ts_relative(gw['ends_at'])} · Entries: {len(gw['entries'])} · Winners: {gw['winners_count']}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @giveaway.command(name="require")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_require(self, ctx, gw_id: str, role: discord.Role):
        """Set a required role for a giveaway."""
        async with self.give_config.guild(ctx.guild).giveaways() as gws:
            if gw_id not in gws:
                return await ctx.send(embed=err_embed("Not found."))
            gws[gw_id]["require_role"] = role.id
        await ctx.send(embed=ok_embed(f"Giveaway `{gw_id}` now requires {role.mention}"))

    @giveaway.command(name="bonus")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_bonus(self, ctx, gw_id: str, role: discord.Role, entries: int):
        """Add bonus entries for a role."""
        async with self.give_config.guild(ctx.guild).giveaways() as gws:
            if gw_id not in gws:
                return await ctx.send(embed=err_embed("Not found."))
            gws[gw_id].setdefault("bonus_roles", {})[str(role.id)] = entries
        await ctx.send(embed=ok_embed(f"{role.mention} gets +{entries} bonus entries in `{gw_id}`"))

    @giveaway.command(name="savetemplate")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_savetemplate(self, ctx, name: str, channel: discord.TextChannel, duration: str, winners: int, *, prize: str):
        """Save a giveaway template."""
        dur = parse_duration(duration)
        if not dur:
            return await ctx.send(embed=err_embed("Invalid duration."))
        await self._save_gw_template(ctx.guild, name.lower(), {
            "prize": prize, "duration": dur, "winners_count": winners, "channel_id": channel.id,
        })
        await ctx.send(embed=ok_embed(f"Template **{name}** saved."))

    @giveaway.command(name="usetemplate")
    @checks.admin_or_permissions(manage_guild=True)
    async def gw_usetemplate(self, ctx, name: str):
        """Start a giveaway from a template."""
        template = await self._load_gw_template(ctx.guild, name.lower())
        if not template:
            return await ctx.send(embed=err_embed("Template not found."))
        channel = ctx.guild.get_channel(template["channel_id"])
        if not channel:
            return await ctx.send(embed=err_embed("Template channel not found."))
        gw_id = await self._create_giveaway(ctx, channel, template["prize"], template["duration"], template["winners_count"])
        await ctx.send(embed=ok_embed(f"Giveaway started from template! ID: `{gw_id}`"))

    @giveaway.command(name="stats")
    async def gw_stats(self, ctx):
        """View giveaway statistics."""
        data = await self.give_config.guild(ctx.guild).all()
        stats = data.get("stats", {})
        embed = discord.Embed(title="🎉 Giveaway Stats", colour=Clr.GIVE)
        embed.add_field(name="Total Hosted", value=str(stats.get("total_hosted", 0)), inline=True)
        embed.add_field(name="Total Entries", value=str(stats.get("total_entries", 0)), inline=True)
        embed.add_field(name="Total Winners", value=str(stats.get("total_winners", 0)), inline=True)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # SERVER LOGGING
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="serverlog", aliases=["slog"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def serverlog(self, ctx: commands.Context):
        """📋 Server logging configuration."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @serverlog.command(name="enable")
    async def slog_enable(self, ctx, channel: discord.TextChannel):
        """Enable logging with a default channel."""
        await self.log_config.guild(ctx.guild).enabled.set(True)
        await self.log_config.guild(ctx.guild).default_channel.set(channel.id)
        await ctx.send(embed=ok_embed(f"Logging enabled! Default channel: {channel.mention}"))

    @serverlog.command(name="disable")
    async def slog_disable(self, ctx):
        """Disable logging."""
        await self.log_config.guild(ctx.guild).enabled.set(False)
        await ctx.send(embed=ok_embed("Logging disabled."))

    @serverlog.command(name="set")
    async def slog_set(self, ctx, event_type: str, channel: discord.TextChannel):
        """Set a specific channel for an event type."""
        if event_type not in EVENT_TYPES:
            return await ctx.send(embed=err_embed(f"Valid types: {', '.join(EVENT_TYPES[:10])}... ({len(EVENT_TYPES)} total)"))
        async with self.log_config.guild(ctx.guild).channels() as channels:
            channels[event_type] = channel.id
        await ctx.send(embed=ok_embed(f"`{event_type}` → {channel.mention}"))

    @serverlog.command(name="toggle")
    async def slog_toggle(self, ctx, event_type: str):
        """Toggle an event type on/off."""
        if event_type not in EVENT_TYPES:
            return await ctx.send(embed=err_embed("Invalid event type."))
        async with self.log_config.guild(ctx.guild).enabled_events() as events:
            events[event_type] = not events.get(event_type, True)
            state = events[event_type]
        await ctx.send(embed=ok_embed(f"`{event_type}` {'enabled' if state else 'disabled'}"))

    @serverlog.command(name="ignore")
    async def slog_ignore(self, ctx, target: discord.TextChannel | discord.Role | discord.Member):
        """Ignore a channel, role, or user from logging."""
        if isinstance(target, discord.TextChannel):
            async with self.log_config.guild(ctx.guild).ignore_channels() as ic:
                if target.id in ic:
                    ic.remove(target.id)
                    await ctx.send(embed=ok_embed(f"{target.mention} unignored."))
                else:
                    ic.append(target.id)
                    await ctx.send(embed=ok_embed(f"{target.mention} ignored."))
        elif isinstance(target, discord.Role):
            async with self.log_config.guild(ctx.guild).ignore_roles() as ir:
                if target.id in ir:
                    ir.remove(target.id)
                    await ctx.send(embed=ok_embed(f"{target.mention} unignored."))
                else:
                    ir.append(target.id)
                    await ctx.send(embed=ok_embed(f"{target.mention} ignored."))
        elif isinstance(target, discord.Member):
            async with self.log_config.guild(ctx.guild).ignore_users() as iu:
                if target.id in iu:
                    iu.remove(target.id)
                    await ctx.send(embed=ok_embed(f"{target.mention} unignored."))
                else:
                    iu.append(target.id)
                    await ctx.send(embed=ok_embed(f"{target.mention} ignored."))

    @serverlog.command(name="events")
    async def slog_events(self, ctx):
        """List all event types and their status."""
        data = await self.log_config.guild(ctx.guild).all()
        events = data.get("enabled_events", {})
        lines = []
        for et in EVENT_TYPES:
            status = "✅" if events.get(et, True) else "❌"
            lines.append(f"{status} `{et}`")
        pages = []
        for chunk in chunk_list(lines, 15):
            embed = discord.Embed(title="📋 Log Events", description="\n".join(chunk), colour=Clr.LOG)
            pages.append(embed)
        pag = Paginator(pages, author_id=ctx.author.id)
        await pag.send(ctx)

    @serverlog.command(name="settings")
    async def slog_settings(self, ctx):
        """View logging settings."""
        data = await self.log_config.guild(ctx.guild).all()
        embed = discord.Embed(title="📋 Logging Settings", colour=Clr.LOG)
        embed.add_field(name="Enabled", value="✅" if data["enabled"] else "❌", inline=True)
        dc = ctx.guild.get_channel(data["default_channel"]) if data["default_channel"] else None
        embed.add_field(name="Default Channel", value=dc.mention if dc else "Not set", inline=True)
        embed.add_field(name="Ignore Bots", value="✅" if data["ignore_bots"] else "❌", inline=True)
        embed.add_field(name="Events Tracked", value=f"{sum(1 for v in data.get('enabled_events', {}).values() if v)}/{len(EVENT_TYPES)}", inline=True)
        overrides = []
        for evt, ch_id in data.get("channels", {}).items():
            ch = ctx.guild.get_channel(ch_id)
            if ch:
                overrides.append(f"`{evt}` → {ch.mention}")
        if overrides:
            embed.add_field(name="Channel Overrides", value="\n".join(overrides[:10]), inline=False)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # MODERATION
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="nmod", aliases=["nexusmod"])
    @commands.guild_only()
    async def nmod(self, ctx: commands.Context):
        """🛡️ NexusCore Moderation."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @nmod.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def nmod_setup(self, ctx, modlog: discord.TextChannel):
        """Set the modlog channel."""
        await self.mod_config.guild(ctx.guild).modlog_channel.set(modlog.id)
        await ctx.send(embed=ok_embed(f"Modlog: {modlog.mention}"))

    @nmod.command(name="warn")
    @checks.mod_or_permissions(manage_messages=True)
    async def nmod_warn(self, ctx, user: discord.Member, *, reason: str = "No reason"):
        """Warn a user."""
        if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=err_embed("Can't warn someone with equal or higher role."))
        case_id = await self._warn_user(ctx, user, reason)
        await ctx.send(embed=ok_embed(f"⚠️ {user.mention} warned (Case #{case_id}): {reason}"))

    @nmod.command(name="mute")
    @checks.mod_or_permissions(moderate_members=True)
    async def nmod_mute(self, ctx, user: discord.Member, duration: str, *, reason: str = "No reason"):
        """Mute (timeout) a user."""
        dur = parse_duration(duration)
        if not dur:
            return await ctx.send(embed=err_embed("Invalid duration."))
        case_id = await self._mute_user(ctx, user, dur, reason)
        await ctx.send(embed=ok_embed(f"🔇 {user.mention} muted for {duration_str(dur)} (Case #{case_id})"))

    @nmod.command(name="unmute")
    @checks.mod_or_permissions(moderate_members=True)
    async def nmod_unmute(self, ctx, user: discord.Member, *, reason: str = "Unmuted"):
        """Unmute a user."""
        case_id = await self._unmute_user(ctx, user, reason)
        await ctx.send(embed=ok_embed(f"🔊 {user.mention} unmuted (Case #{case_id})"))

    @nmod.command(name="kick")
    @checks.mod_or_permissions(kick_members=True)
    async def nmod_kick(self, ctx, user: discord.Member, *, reason: str = "No reason"):
        """Kick a user."""
        await self._kick_user(ctx, user, reason)
        await ctx.send(embed=ok_embed(f"👢 {user.mention} kicked: {reason}"))

    @nmod.command(name="ban")
    @checks.mod_or_permissions(ban_members=True)
    async def nmod_ban(self, ctx, user: discord.User, *, reason: str = "No reason"):
        """Ban a user."""
        await self._ban_user(ctx, user, reason)
        await ctx.send(embed=ok_embed(f"🔨 {user.mention} banned: {reason}"))

    @nmod.command(name="softban")
    @checks.mod_or_permissions(ban_members=True)
    async def nmod_softban(self, ctx, user: discord.Member, *, reason: str = "No reason"):
        """Softban (ban + unban to purge messages)."""
        await self._softban_user(ctx, user, reason)
        await ctx.send(embed=ok_embed(f"🧹 {user.mention} softbanned: {reason}"))

    @nmod.command(name="tempban")
    @checks.mod_or_permissions(ban_members=True)
    async def nmod_tempban(self, ctx, user: discord.Member, duration: str, *, reason: str = "No reason"):
        """Temporarily ban a user."""
        dur = parse_duration(duration)
        if not dur:
            return await ctx.send(embed=err_embed("Invalid duration."))
        await self._tempban_user(ctx, user, dur, reason)
        await ctx.send(embed=ok_embed(f"⏰ {user.mention} temp-banned for {duration_str(dur)}: {reason}"))

    @nmod.command(name="unban")
    @checks.mod_or_permissions(ban_members=True)
    async def nmod_unban(self, ctx, user_id: int, *, reason: str = "Unbanned"):
        """Unban a user by ID."""
        user = await self.bot.fetch_user(user_id)
        await self._unban_user(ctx, user, reason)
        await ctx.send(embed=ok_embed(f"🔓 {user} unbanned: {reason}"))

    @nmod.command(name="note")
    @checks.mod_or_permissions(manage_messages=True)
    async def nmod_note(self, ctx, user: discord.User, *, text: str):
        """Add a staff note on a user."""
        await self._add_note(ctx.guild, user, ctx.author, text)
        await ctx.send(embed=ok_embed(f"📝 Note added for {user.mention}"))

    @nmod.command(name="notes")
    @checks.mod_or_permissions(manage_messages=True)
    async def nmod_notes(self, ctx, user: discord.User):
        """View notes on a user."""
        notes = await self.mod_config.guild(ctx.guild).notes()
        user_notes = notes.get(str(user.id), [])
        if not user_notes:
            return await ctx.send(embed=info_embed(f"No notes for {user}."))
        embed = discord.Embed(title=f"📝 Notes — {user}", colour=Clr.MOD)
        for n in user_notes[-10:]:
            embed.add_field(
                name=f"<@{n['author_id']}> · {ts_relative(n['timestamp'])}",
                value=n["text"][:1024], inline=False,
            )
        await ctx.send(embed=embed)

    @nmod.command(name="warnings", aliases=["warns"])
    @checks.mod_or_permissions(manage_messages=True)
    async def nmod_warnings(self, ctx, user: discord.User):
        """View a user's warnings."""
        warnings = await self.mod_config.guild(ctx.guild).warnings()
        user_warns = warnings.get(str(user.id), [])
        if not user_warns:
            return await ctx.send(embed=info_embed(f"No warnings for {user}."))
        embed = discord.Embed(title=f"⚠️ Warnings — {user}", colour=Clr.MOD)
        for w in user_warns[-15:]:
            embed.add_field(
                name=f"Case #{w['id']} · {ts_relative(w['timestamp'])}",
                value=f"{w['reason']} (by <@{w['mod_id']}>)", inline=False,
            )
        embed.set_footer(text=f"Total: {len(user_warns)} warnings")
        await ctx.send(embed=embed)

    @nmod.command(name="clearwarns")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_clearwarns(self, ctx, user: discord.User):
        """Clear all warnings for a user."""
        async with self.mod_config.guild(ctx.guild).warnings() as warnings:
            warnings.pop(str(user.id), None)
        await ctx.send(embed=ok_embed(f"Warnings cleared for {user.mention}"))

    @nmod.command(name="history")
    @checks.mod_or_permissions(manage_messages=True)
    async def nmod_history(self, ctx, user: discord.User):
        """View a user's full moderation history."""
        cases = await self.mod_config.guild(ctx.guild).cases()
        user_cases = {cid: c for cid, c in cases.items() if c["user_id"] == user.id}
        if not user_cases:
            return await ctx.send(embed=info_embed(f"No cases for {user}."))
        pages = []
        for chunk in chunk_list(list(user_cases.items()), 5):
            embed = discord.Embed(title=f"📋 History — {user}", colour=Clr.MOD)
            for cid, c in chunk:
                embed.add_field(
                    name=f"#{cid} {c['type'].upper()} · {ts_relative(c['timestamp'])}",
                    value=f"{c['reason'][:200]} (by <@{c['mod_id']}>)", inline=False,
                )
            pages.append(embed)
        pag = Paginator(pages, author_id=ctx.author.id)
        await pag.send(ctx)

    @nmod.command(name="quarantine")
    @checks.admin_or_permissions(manage_guild=True)
    async def nmod_quarantine(self, ctx, user: discord.Member, *, reason: str = "Quarantined"):
        """Quarantine a user (assigns quarantine role)."""
        case_id = await self._quarantine_user(ctx, user, reason)
        if case_id:
            await ctx.send(embed=ok_embed(f"🔒 {user.mention} quarantined (Case #{case_id})"))
        else:
            await ctx.send(embed=err_embed("Set quarantine role first: `[p]nmod setquarantine @role`"))

    @nmod.command(name="unquarantine")
    @checks.admin_or_permissions(manage_guild=True)
    async def nmod_unquarantine(self, ctx, user: discord.Member, *, reason: str = "Released"):
        """Release a user from quarantine."""
        case_id = await self._unquarantine_user(ctx, user, reason)
        if case_id:
            await ctx.send(embed=ok_embed(f"🔓 {user.mention} released (Case #{case_id})"))
        else:
            await ctx.send(embed=err_embed("No quarantine role set."))

    @nmod.command(name="setquarantine")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_setquarantine(self, ctx, role: discord.Role):
        """Set the quarantine role."""
        await self.mod_config.guild(ctx.guild).quarantine_role.set(role.id)
        await ctx.send(embed=ok_embed(f"Quarantine role: {role.mention}"))

    @nmod.command(name="reputation", aliases=["rep"])
    @checks.mod_or_permissions(manage_messages=True)
    async def nmod_reputation(self, ctx, user: discord.Member):
        """View a user's reputation score."""
        rep = await self._get_reputation(ctx.guild, user)
        embed = discord.Embed(title=f"📊 Reputation — {user.display_name}", colour=Clr.MOD)
        embed.add_field(name="Score", value=str(rep), inline=True)
        await ctx.send(embed=embed)

    @nmod.command(name="lockdown")
    @checks.admin_or_permissions(manage_channels=True)
    async def nmod_lockdown(self, ctx, channel: discord.TextChannel = None):
        """Lock a channel (or current channel)."""
        channel = channel or ctx.channel
        await self._lockdown_channel(channel, f"Locked by {ctx.author}")
        await ctx.send(embed=ok_embed(f"🔒 {channel.mention} locked."))

    @nmod.command(name="unlock")
    @checks.admin_or_permissions(manage_channels=True)
    async def nmod_unlock(self, ctx, channel: discord.TextChannel = None):
        """Unlock a channel."""
        channel = channel or ctx.channel
        await self._unlock_channel(channel, f"Unlocked by {ctx.author}")
        await ctx.send(embed=ok_embed(f"🔓 {channel.mention} unlocked."))

    @nmod.command(name="serverlockdown")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_serverlockdown(self, ctx, *, reason: str = "Server lockdown"):
        """Lock ALL text channels in the server."""
        view = ConfirmView(ctx.author.id)
        msg = await ctx.send("⚠️ This will lock **all** text channels. Continue?", view=view)
        await view.wait()
        if view.value:
            await self._lockdown_server(ctx.guild, ctx.author, reason)
            await ctx.send(embed=ok_embed(f"🔒 Server lockdown activated: {reason}"))
        else:
            await ctx.send(embed=info_embed("Cancelled."))

    @nmod.command(name="antiraid")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_antiraid(self, ctx, enabled: bool, threshold: int = 10, window: int = 10, action: str = "lockdown"):
        """Configure anti-raid: [p]nmod antiraid true 10 10 lockdown"""
        await self.mod_config.guild(ctx.guild).anti_raid.set({
            "enabled": enabled, "join_threshold": threshold, "join_window": window,
            "action": action, "notify_channel": ctx.channel.id,
        })
        await ctx.send(embed=ok_embed(f"Anti-raid {'enabled' if enabled else 'disabled'}: {threshold} joins in {window}s → {action}"))

    @nmod.command(name="antinuke")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_antinuke(self, ctx, enabled: bool, action: str = "strip_roles"):
        """Configure anti-nuke: [p]nmod antinuke true strip_roles"""
        async with self.mod_config.guild(ctx.guild).anti_nuke() as an:
            an["enabled"] = enabled
            an["action"] = action
        await ctx.send(embed=ok_embed(f"Anti-nuke {'enabled' if enabled else 'disabled'}: action → {action}"))

    @nmod.command(name="automod")
    @checks.admin_or_permissions(manage_guild=True)
    async def nmod_automod(self, ctx, module: str, enabled: bool):
        """Toggle auto-mod modules: anti_spam, anti_caps, anti_invite, anti_links, anti_mention, anti_newlines."""
        valid = ["anti_spam", "anti_caps", "anti_invite", "anti_links", "anti_mention", "anti_newlines"]
        if module not in valid:
            return await ctx.send(embed=err_embed(f"Valid modules: {', '.join(valid)}"))
        async with self.mod_config.guild(ctx.guild).auto_mod() as am:
            if module in am:
                am[module]["enabled"] = enabled
        await ctx.send(embed=ok_embed(f"`{module}` {'enabled' if enabled else 'disabled'}"))

    @nmod.command(name="escalation")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_escalation(self, ctx, warn_count: int, action: str):
        """Set an escalation threshold: [p]nmod escalation 3 mute_1h"""
        async with self.mod_config.guild(ctx.guild).escalation() as esc:
            esc.setdefault("thresholds", {})[str(warn_count)] = action
        await ctx.send(embed=ok_embed(f"{warn_count} warnings → `{action}`"))

    @nmod.command(name="warndecay")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_warndecay(self, ctx, days: int, amount: int = 1):
        """Set warning decay (days until old warnings are removed)."""
        await self.mod_config.guild(ctx.guild).warn_decay_days.set(days)
        await self.mod_config.guild(ctx.guild).warn_decay_amount.set(amount)
        await ctx.send(embed=ok_embed(f"Warning decay: {amount} warning(s) removed after {days} days" if days else "Decay disabled."))

    @nmod.command(name="appeal")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_appeal(self, ctx, channel: discord.TextChannel):
        """Set the appeal channel and enable appeals."""
        await self.mod_config.guild(ctx.guild).appeal_channel.set(channel.id)
        await self.mod_config.guild(ctx.guild).appeal_enabled.set(True)
        await ctx.send(embed=ok_embed(f"Appeals enabled! Channel: {channel.mention}"))

    @nmod.command(name="appealpanel")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_appealpanel(self, ctx, channel: discord.TextChannel = None):
        """Send an appeal button panel."""
        channel = channel or ctx.channel
        embed = discord.Embed(
            title="📨 Appeals",
            description="Click below to submit an appeal for a moderation action.",
            colour=Clr.MOD,
        )
        from .moderation import AppealButtonView
        await channel.send(embed=embed, view=AppealButtonView(self))
        await ctx.send(embed=ok_embed(f"Appeal panel sent to {channel.mention}"))

    @nmod.command(name="purge")
    @checks.mod_or_permissions(manage_messages=True)
    async def nmod_purge(self, ctx, count: int, user: discord.Member = None):
        """Purge messages (optionally from a specific user)."""
        if count > 500:
            return await ctx.send(embed=err_embed("Max 500 messages."))
        def check(m):
            if user:
                return m.author.id == user.id
            return True
        deleted = await ctx.channel.purge(limit=count, check=check)
        await ctx.send(embed=ok_embed(f"🗑️ Purged {len(deleted)} messages."), delete_after=5)

    @nmod.command(name="massban")
    @checks.admin_or_permissions(ban_members=True)
    async def nmod_massban(self, ctx, *user_ids: int):
        """Ban multiple users by ID."""
        if not user_ids:
            return await ctx.send(embed=err_embed("Provide user IDs."))
        banned = 0
        for uid in user_ids[:50]:
            try:
                user = await self.bot.fetch_user(uid)
                await ctx.guild.ban(user, reason=f"Massban by {ctx.author}")
                banned += 1
            except discord.HTTPException:
                pass
        await ctx.send(embed=ok_embed(f"Banned {banned}/{len(user_ids)} users."))

    @nmod.command(name="stafflb", aliases=["staffleaderboard"])
    @checks.admin_or_permissions(manage_guild=True)
    async def nmod_stafflb(self, ctx):
        """View staff moderation leaderboard."""
        stats = await self.mod_config.guild(ctx.guild).staff_stats()
        if not stats:
            return await ctx.send(embed=info_embed("No staff stats."))
        sorted_stats = sorted(stats.items(), key=lambda x: sum(x[1].values()), reverse=True)
        embed = discord.Embed(title="🛡️ Staff Leaderboard", colour=Clr.MOD)
        for i, (mod_id, s) in enumerate(sorted_stats[:15], 1):
            member = ctx.guild.get_member(int(mod_id))
            name = member.display_name if member else f"ID:{mod_id}"
            total = sum(s.values())
            embed.add_field(
                name=f"#{i} {name} — {total} actions",
                value=f"⚠️ {s.get('warns', 0)} · 🔇 {s.get('mutes', 0)} · 👢 {s.get('kicks', 0)} · 🔨 {s.get('bans', 0)}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @nmod.command(name="crossban")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_crossban(self, ctx, enabled: bool, webhook_url: str = None):
        """Enable cross-server ban sync via webhook."""
        await self.mod_config.guild(ctx.guild).cross_server_ban.set({
            "enabled": enabled, "webhook_url": webhook_url, "log_only": True,
        })
        await ctx.send(embed=ok_embed(f"Cross-server ban sync {'enabled' if enabled else 'disabled'}"))

    # ══════════════════════════════════════════════════════════════════════════
    # ECONOMY
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="eco", aliases=["economy"])
    @commands.guild_only()
    async def eco(self, ctx: commands.Context):
        """🪙 Economy system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @eco.command(name="balance", aliases=["bal"])
    async def eco_bal(self, ctx, user: discord.Member = None):
        """Check your (or someone's) balance."""
        user = user or ctx.author
        wallet, bank = await self._get_balance(user)
        data = await self.eco_config.guild(ctx.guild).all()
        emoji = data["currency_emoji"]
        embed = discord.Embed(title=f"{emoji} {user.display_name}'s Balance", colour=Clr.ECO)
        embed.add_field(name="Wallet", value=f"{emoji} {wallet:,}", inline=True)
        embed.add_field(name="Bank", value=f"{emoji} {bank:,}", inline=True)
        embed.add_field(name="Total", value=f"{emoji} {wallet + bank:,}", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        await ctx.send(embed=embed)
        await self._check_millionaire(user)

    @eco.command(name="daily")
    async def eco_daily(self, ctx):
        """Claim your daily reward."""
        await self._daily(ctx)

    @eco.command(name="weekly")
    async def eco_weekly(self, ctx):
        """Claim your weekly reward."""
        await self._weekly(ctx)

    @eco.command(name="work")
    async def eco_work(self, ctx):
        """Work for coins."""
        await self._work(ctx)

    @eco.command(name="crime")
    async def eco_crime(self, ctx):
        """Attempt a crime (risky!)."""
        await self._crime(ctx)

    @eco.command(name="rob")
    async def eco_rob(self, ctx, target: discord.Member):
        """Rob another user."""
        await self._rob(ctx, target)

    @eco.command(name="deposit", aliases=["dep"])
    async def eco_deposit(self, ctx, amount: str):
        """Deposit coins to bank."""
        if amount.lower() == "all":
            amount = await self.eco_config.member(ctx.author).wallet()
        else:
            amount = int(amount)
        await self._deposit(ctx, amount)

    @eco.command(name="withdraw", aliases=["with"])
    async def eco_withdraw(self, ctx, amount: str):
        """Withdraw coins from bank."""
        if amount.lower() == "all":
            amount = await self.eco_config.member(ctx.author).bank()
        else:
            amount = int(amount)
        await self._withdraw(ctx, amount)

    @eco.command(name="pay", aliases=["give", "transfer"])
    async def eco_pay(self, ctx, user: discord.Member, amount: int):
        """Pay another user."""
        if user.id == ctx.author.id:
            return await ctx.send(embed=err_embed("Can't pay yourself."))
        if amount <= 0:
            return await ctx.send(embed=err_embed("Amount must be positive."))
        wallet = await self.eco_config.member(ctx.author).wallet()
        if amount > wallet:
            return await ctx.send(embed=err_embed("Not enough coins."))
        data = await self.eco_config.guild(ctx.guild).all()
        tax = int(amount * data["tax_rate"] / 100)
        received = amount - tax
        await self._remove_balance(ctx.author, amount)
        await self._add_balance(user, received)
        await self._add_transaction(ctx.author, -amount, f"Paid {user}")
        await self._add_transaction(user, received, f"Received from {ctx.author}")
        desc = f"Sent **{await self._format_amount(ctx.guild, received)}** to {user.mention}"
        if tax:
            desc += f"\n(Tax: {tax:,})"
        await ctx.send(embed=ok_embed(desc))

    @eco.command(name="leaderboard", aliases=["lb", "top"])
    async def eco_lb(self, ctx, page: int = 1):
        """View the richest users."""
        all_members = await self.eco_config.all_members(ctx.guild)
        rankings = []
        for uid, data in all_members.items():
            total = data.get("wallet", 0) + data.get("bank", 0)
            if total > 0:
                rankings.append((uid, total))
        rankings.sort(key=lambda x: x[1], reverse=True)
        per_page = 10
        start = (page - 1) * per_page
        chunk = rankings[start:start + per_page]
        if not chunk:
            return await ctx.send(embed=info_embed("No data."))
        data = await self.eco_config.guild(ctx.guild).all()
        emoji = data["currency_emoji"]
        lines = []
        for i, (uid, total) in enumerate(chunk, start=start + 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"**{i}.**")
            lines.append(f"{medal} <@{uid}> — {emoji} {total:,}")
        embed = discord.Embed(title=f"{emoji} Leaderboard", description="\n".join(lines), colour=Clr.ECO)
        embed.set_footer(text=f"Page {page} · {len(rankings)} total users")
        await ctx.send(embed=embed)

    @eco.command(name="coinflip", aliases=["cf"])
    async def eco_coinflip(self, ctx, bet: int, choice: str):
        """Coinflip! [p]eco cf 100 heads"""
        await self._coinflip(ctx, bet, choice)

    @eco.command(name="slots")
    async def eco_slots(self, ctx, bet: int):
        """Play the slot machine!"""
        await self._slots(ctx, bet)

    @eco.command(name="blackjack", aliases=["bj"])
    async def eco_blackjack(self, ctx, bet: int):
        """Play blackjack!"""
        await self._blackjack(ctx, bet)

    @eco.command(name="roulette")
    async def eco_roulette(self, ctx, bet: int, *, choice: str):
        """Play roulette! Choices: red, black, even, odd, high, low, or 0-36"""
        await self._roulette(ctx, bet, choice)

    @eco.command(name="dice")
    async def eco_dice(self, ctx, bet: int, guess: int):
        """Roll dice! Guess the total (2-12)."""
        await self._dice(ctx, bet, guess)

    @eco.command(name="fish")
    async def eco_fish(self, ctx):
        """Go fishing!"""
        await self._fish(ctx)

    @eco.command(name="mine")
    async def eco_mine(self, ctx):
        """Go mining!"""
        await self._mine(ctx)

    @eco.command(name="craft")
    async def eco_craft(self, ctx, *, recipe: str):
        """Craft an item from materials."""
        await self._craft(ctx, recipe.lower().replace(" ", "_"))

    @eco.command(name="materials", aliases=["mats"])
    async def eco_materials(self, ctx, user: discord.Member = None):
        """View your gathered materials."""
        user = user or ctx.author
        mats = await self.eco_config.member(user).materials()
        if not mats:
            return await ctx.send(embed=info_embed(f"{user.display_name} has no materials."))
        data = await self.eco_config.guild(ctx.guild).all()
        mining_types = data.get("mining", {}).get("ore_types", {})
        embed = discord.Embed(title=f"⛏️ {user.display_name}'s Materials", colour=Clr.ECO)
        for mat, count in mats.items():
            mt = mining_types.get(mat, {})
            emoji = mt.get("emoji", "📦")
            embed.add_field(name=f"{emoji} {mat.replace('_', ' ').title()}", value=f"x{count}", inline=True)
        await ctx.send(embed=embed)

    @eco.command(name="shop")
    async def eco_shop(self, ctx):
        """Browse the server shop."""
        data = await self.eco_config.guild(ctx.guild).all()
        items = data.get("shop_items", {})
        if not items:
            return await ctx.send(embed=info_embed("Shop is empty!"))
        emoji = data["currency_emoji"]
        embed = discord.Embed(title="🛒 Shop", colour=Clr.ECO)
        for iid, item in items.items():
            stock_text = f"Stock: {item['stock']}" if item.get("stock", -1) >= 0 else "∞"
            embed.add_field(
                name=f"{item.get('emoji', '📦')} {item['name']} — {emoji} {item['price']:,}",
                value=f"{item.get('description', 'No description')}\n{stock_text}",
                inline=False,
            )
        view = ShopView(self, ctx.guild, items)
        await ctx.send(embed=embed, view=view)

    @eco.command(name="additem")
    @checks.admin_or_permissions(manage_guild=True)
    async def eco_additem(self, ctx, name: str, price: int, *, description: str = ""):
        """Add a shop item."""
        item_id = short_id(8)
        async with self.eco_config.guild(ctx.guild).shop_items() as items:
            items[item_id] = {
                "name": name, "description": description, "price": price,
                "emoji": "📦", "role_id": None, "stock": -1,
                "max_per_user": 0, "usable": False, "type": "item",
            }
        await ctx.send(embed=ok_embed(f"Item **{name}** added (ID: `{item_id}`, Price: {price:,})"))

    @eco.command(name="addroleitem")
    @checks.admin_or_permissions(manage_guild=True)
    async def eco_addroleitem(self, ctx, name: str, price: int, role: discord.Role, *, description: str = ""):
        """Add a role shop item."""
        item_id = short_id(8)
        async with self.eco_config.guild(ctx.guild).shop_items() as items:
            items[item_id] = {
                "name": name, "description": description, "price": price,
                "emoji": "🏷️", "role_id": role.id, "stock": -1,
                "max_per_user": 1, "usable": False, "type": "role",
            }
        await ctx.send(embed=ok_embed(f"Role item **{name}** added ({role.mention}, {price:,})"))

    @eco.command(name="removeitem")
    @checks.admin_or_permissions(manage_guild=True)
    async def eco_removeitem(self, ctx, item_id: str):
        """Remove a shop item."""
        async with self.eco_config.guild(ctx.guild).shop_items() as items:
            if item_id not in items:
                return await ctx.send(embed=err_embed("Item not found."))
            removed = items.pop(item_id)
        await ctx.send(embed=ok_embed(f"Removed **{removed['name']}**"))

    @eco.command(name="inventory", aliases=["inv"])
    async def eco_inventory(self, ctx, user: discord.Member = None):
        """View inventory."""
        user = user or ctx.author
        inv = await self.eco_config.member(user).inventory()
        if not inv:
            return await ctx.send(embed=info_embed(f"{user.display_name} has no items."))
        items_data = await self.eco_config.guild(ctx.guild).shop_items()
        embed = discord.Embed(title=f"🎒 {user.display_name}'s Inventory", colour=Clr.ECO)
        for iid, count in inv.items():
            item = items_data.get(iid, {})
            name = item.get("name", iid)
            emoji = item.get("emoji", "📦")
            embed.add_field(name=f"{emoji} {name}", value=f"x{count}", inline=True)
        await ctx.send(embed=embed)

    @eco.command(name="heist")
    async def eco_heist(self, ctx, bet: int):
        """Start a heist! Others can join."""
        await self._start_heist(ctx, bet)

    @eco.command(name="pet")
    async def eco_pet(self, ctx):
        """View your pets."""
        pets = await self.eco_config.member(ctx.author).pets()
        if not pets:
            data = await self.eco_config.guild(ctx.guild).all()
            types = data.get("pets", {}).get("types", {})
            available = "\n".join(f"{v['emoji']} **{k}** — {v['base_price']:,} coins" for k, v in types.items())
            return await ctx.send(embed=info_embed(f"You have no pets.\n\nAvailable:\n{available}\n\nBuy: `[p]eco buypet <type> <name>`"))
        data = await self.eco_config.guild(ctx.guild).all()
        types = data.get("pets", {}).get("types", {})
        embed = discord.Embed(title=f"🐾 {ctx.author.display_name}'s Pets", colour=Clr.ECO)
        for name, pet in pets.items():
            pt = types.get(pet["type"], {})
            emoji = pt.get("emoji", "🐾")
            embed.add_field(
                name=f"{emoji} {name}",
                value=f"Type: {pet['type']} · Lv.{pet['level']} · XP: {pet['xp']} · ❤️ {pet['happiness']}%",
                inline=False,
            )
        embed.set_footer(text="Feed: [p]eco feed <name> · Collect: [p]eco collect")
        await ctx.send(embed=embed)

    @eco.command(name="buypet")
    async def eco_buypet(self, ctx, pet_type: str, *, name: str):
        """Buy a pet."""
        await self._buy_pet(ctx, pet_type.lower(), name)

    @eco.command(name="feed")
    async def eco_feed(self, ctx, *, name: str):
        """Feed a pet."""
        await self._feed_pet(ctx, name)

    @eco.command(name="collect")
    async def eco_collect(self, ctx):
        """Collect earnings from pets."""
        await self._pet_collect(ctx)

    @eco.command(name="gamblestats")
    async def eco_gamblestats(self, ctx, user: discord.Member = None):
        """View gambling statistics."""
        user = user or ctx.author
        stats = await self.eco_config.member(user).gambling_stats()
        data = await self.eco_config.guild(ctx.guild).all()
        emoji = data["currency_emoji"]
        embed = discord.Embed(title=f"🎰 {user.display_name}'s Gambling Stats", colour=Clr.ECO)
        embed.add_field(name="Won", value=f"{emoji} {stats.get('won', 0):,}", inline=True)
        embed.add_field(name="Lost", value=f"{emoji} {stats.get('lost', 0):,}", inline=True)
        embed.add_field(name="Total Wagered", value=f"{emoji} {stats.get('total_wagered', 0):,}", inline=True)
        embed.add_field(name="Biggest Win", value=f"{emoji} {stats.get('biggest_win', 0):,}", inline=True)
        net = stats.get("won", 0) - stats.get("lost", 0)
        embed.add_field(name="Net", value=f"{emoji} {net:,}", inline=True)
        await ctx.send(embed=embed)

    @eco.command(name="achievements", aliases=["ach"])
    async def eco_achievements(self, ctx, user: discord.Member = None):
        """View achievements."""
        user = user or ctx.author
        earned = await self.eco_config.member(user).achievements()
        data = await self.eco_config.guild(ctx.guild).all()
        all_achs = data.get("achievements", {})
        embed = discord.Embed(title=f"🏆 {user.display_name}'s Achievements", colour=Clr.ECO)
        for aid, ach in all_achs.items():
            status = "✅" if aid in earned else "🔒"
            embed.add_field(
                name=f"{status} {ach.get('emoji', '🏆')} {ach['name']}",
                value=f"{ach.get('description', '')}" + (f"\nReward: {ach.get('reward', 0):,}" if ach.get("reward") else ""),
                inline=True,
            )
        embed.set_footer(text=f"{len(earned)}/{len(all_achs)} unlocked")
        await ctx.send(embed=embed)

    @eco.command(name="auction")
    async def eco_auction(self, ctx):
        """View the auction house."""
        data = await self.eco_config.guild(ctx.guild).all()
        auction_data = data.get("auction", {})
        if not auction_data.get("enabled"):
            return await ctx.send(embed=err_embed("Auction house is disabled."))
        listings = auction_data.get("listings", {})
        active = {k: v for k, v in listings.items() if not v.get("ended")}
        if not active:
            return await ctx.send(embed=info_embed("No active auctions."))
        embed = discord.Embed(title="🏛️ Auction House", colour=Clr.ECO)
        for lid, listing in list(active.items())[:10]:
            embed.add_field(
                name=f"`{lid}` — {listing['item_name']}",
                value=f"Current bid: {listing.get('current_bid', listing.get('starting_price', 0)):,}\nSeller: <@{listing['seller_id']}>",
                inline=True,
            )
        from .economy import AuctionListView
        view = AuctionListView(self, ctx.guild, active)
        await ctx.send(embed=embed, view=view)

    @eco.command(name="setcurrency")
    @checks.admin_or_permissions(manage_guild=True)
    async def eco_setcurrency(self, ctx, name: str, emoji: str, symbol: str = "$"):
        """Set currency name and emoji."""
        await self.eco_config.guild(ctx.guild).currency_name.set(name)
        await self.eco_config.guild(ctx.guild).currency_emoji.set(emoji)
        await self.eco_config.guild(ctx.guild).currency_symbol.set(symbol)
        await ctx.send(embed=ok_embed(f"Currency: {emoji} {name} ({symbol})"))

    @eco.command(name="setbalance")
    @checks.admin_or_permissions(administrator=True)
    async def eco_setbalance(self, ctx, user: discord.Member, wallet: int, bank: int = 0):
        """Set a user's balance (admin)."""
        await self.eco_config.member(user).wallet.set(wallet)
        await self.eco_config.member(user).bank.set(bank)
        await ctx.send(embed=ok_embed(f"Balance set — {user.mention}: Wallet {wallet:,}, Bank {bank:,}"))

    @eco.command(name="addmoney")
    @checks.admin_or_permissions(administrator=True)
    async def eco_addmoney(self, ctx, user: discord.Member, amount: int):
        """Add coins to a user's wallet (admin)."""
        await self._add_balance(user, amount)
        await ctx.send(embed=ok_embed(f"Added {amount:,} to {user.mention}'s wallet."))

    @eco.command(name="removemoney")
    @checks.admin_or_permissions(administrator=True)
    async def eco_removemoney(self, ctx, user: discord.Member, amount: int):
        """Remove coins from a user (admin)."""
        await self._remove_balance(user, amount)
        await ctx.send(embed=ok_embed(f"Removed {amount:,} from {user.mention}."))

    @eco.command(name="reset")
    @checks.admin_or_permissions(administrator=True)
    async def eco_reset(self, ctx, user: discord.Member):
        """Reset a user's economy data (admin)."""
        await self.eco_config.member(user).clear()
        await ctx.send(embed=ok_embed(f"{user.mention}'s economy data reset."))

    @eco.command(name="incomerole")
    @checks.admin_or_permissions(manage_guild=True)
    async def eco_incomerole(self, ctx, role: discord.Role, amount: int, hours: int = 1):
        """Set passive income for a role."""
        async with self.eco_config.guild(ctx.guild).income_roles() as ir:
            ir[str(role.id)] = {"amount": amount, "interval_hours": hours}
        await ctx.send(embed=ok_embed(f"{role.mention} earns {amount:,} every {hours}h."))

    @eco.command(name="settings")
    @checks.admin_or_permissions(manage_guild=True)
    async def eco_settings(self, ctx):
        """View economy settings."""
        data = await self.eco_config.guild(ctx.guild).all()
        embed = discord.Embed(title="🪙 Economy Settings", colour=Clr.ECO)
        embed.add_field(name="Currency", value=f"{data['currency_emoji']} {data['currency_name']}", inline=True)
        embed.add_field(name="Daily", value=f"{data['daily_amount']:,}", inline=True)
        embed.add_field(name="Weekly", value=f"{data['weekly_amount']:,}", inline=True)
        embed.add_field(name="Work", value=f"{data['work_min']}-{data['work_max']}", inline=True)
        embed.add_field(name="Crime", value=f"{data['crime_min']}-{data['crime_max']} ({data['crime_fail_chance']}% fail)", inline=True)
        embed.add_field(name="Rob", value="✅" if data['rob_enabled'] else "❌", inline=True)
        embed.add_field(name="Tax", value=f"{data['tax_rate']}%", inline=True)
        embed.add_field(name="Interest", value=f"{data['interest_rate']}%", inline=True)
        embed.add_field(name="Shop Items", value=str(len(data.get('shop_items', {}))), inline=True)
        embed.add_field(name="Fishing", value="✅" if data.get("fishing", {}).get("enabled") else "❌", inline=True)
        embed.add_field(name="Mining", value="✅" if data.get("mining", {}).get("enabled") else "❌", inline=True)
        embed.add_field(name="Auction", value="✅" if data.get("auction", {}).get("enabled") else "❌", inline=True)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # EMBED BUILDER
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="embedbuilder", aliases=["eb"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def embedbuilder(self, ctx: commands.Context):
        """📨 Embed Builder — Create custom embeds and send via webhooks."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @embedbuilder.command(name="create")
    async def eb_create(self, ctx):
        """Open the interactive embed builder."""
        await self._open_embed_builder(ctx)

    @embedbuilder.command(name="send")
    async def eb_send(self, ctx, channel: discord.TextChannel, *, json_data: str = None):
        """Send an embed via JSON. Supports Discohook JSON format."""
        if not json_data:
            return await ctx.send(embed=info_embed("Paste Discohook JSON: `[p]eb send #channel {\"embeds\": [...]}`"))
        await self._send_json_embed(ctx, channel, json_data)

    @embedbuilder.command(name="webhook")
    async def eb_webhook(self, ctx, channel: discord.TextChannel, *, name: str = "NexusCore"):
        """Create/set a webhook for a channel."""
        await self._setup_webhook(ctx, channel, name)

    @embedbuilder.command(name="templates")
    async def eb_templates(self, ctx):
        """List saved embed templates."""
        await self._list_templates(ctx)

    @embedbuilder.command(name="save")
    async def eb_save(self, ctx, name: str, *, json_data: str):
        """Save an embed template."""
        await self._save_template(ctx, name, json_data)

    @embedbuilder.command(name="load")
    async def eb_load(self, ctx, name: str, channel: discord.TextChannel):
        """Load and send a saved template."""
        await self._load_and_send_template(ctx, name, channel)

    @embedbuilder.command(name="schedule")
    async def eb_schedule(self, ctx, channel: discord.TextChannel, interval: str, *, json_data: str):
        """Schedule a recurring embed. Interval: 1h, 6h, 1d, etc."""
        dur = parse_duration(interval)
        if not dur:
            return await ctx.send(embed=err_embed("Invalid interval."))
        await self._schedule_embed(ctx, channel, dur, json_data)
        await ctx.send(embed=ok_embed(f"Embed scheduled every {duration_str(dur)} in {channel.mention}"))
