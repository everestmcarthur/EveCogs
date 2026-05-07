"""NexusCore — The ultimate all-in-one server management cog for Red-DiscordBot.

Tickets · Applications · Suggestions · Reaction Roles · Giveaways · Logging · Moderation · Economy
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Optional

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    duration_str, parse_duration, safe_send, Paginator, chunk_list, ConfirmView,
)
from .tickets import TicketsMixin
from .applications import ApplicationsMixin
from .suggestions import SuggestionsMixin
from .reactionroles import ReactionRolesMixin
from .giveaways import GiveawaysMixin
from .serverlog import ServerLogMixin
from .moderation import ModerationMixin
from .economy import EconomyMixin, ShopView


class NexusCore(
    TicketsMixin,
    ApplicationsMixin,
    SuggestionsMixin,
    ReactionRolesMixin,
    GiveawaysMixin,
    ServerLogMixin,
    ModerationMixin,
    EconomyMixin,
    commands.Cog,
):
    """🔥 NexusCore — The ultimate server management cog.

    Tickets, Applications, Suggestions, Reaction Roles, Giveaways,
    Logging, Moderation, and Economy all in one powerful package.
    """

    __version__ = "1.0.0"
    __author__ = "everestmcarthur"

    def __init__(self, bot: Red):
        self.bot = bot
        super().__init__()

        # Initialise all subsystem configs
        self._init_tickets(bot)
        self._init_applications(bot)
        self._init_suggestions(bot)
        self._init_reaction_roles(bot)
        self._init_giveaways(bot)
        self._init_logging(bot)
        self._init_moderation(bot)
        self._init_economy(bot)

    async def cog_load(self):
        await self._load_rr_panels()
        await self._load_giveaways()
        # Cache invites for logging
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    def cog_unload(self):
        # Cancel giveaway tasks
        for task in self._gw_tasks.values():
            task.cancel()
        for task in self._rr_temp_tasks.values():
            task.cancel()

    # ══════════════════════════════════════════════════════════════════════════
    # LISTENERS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        await self._cache_message(message)
        await self._check_automod(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        await self._log_message_edit(before, after)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        await self._log_message_delete(message)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        await self._log_bulk_delete(messages)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._log_member_join(member)
        await self._check_anti_raid(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._log_member_leave(member)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        await self._log_member_ban(guild, user)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        await self._log_member_unban(guild, user)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        await self._log_member_update(before, after)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        await self._log_voice(member, before, after)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self._log_channel_create(channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self._log_channel_delete(channel)
        if channel.guild:
            # Anti-nuke check
            try:
                async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                    if entry.user:
                        await self._check_anti_nuke(channel.guild, "channel_delete", entry.user)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._log_role_create(role)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._log_role_delete(role)
        try:
            async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
                if entry.user:
                    await self._check_anti_nuke(role.guild, "role_delete", entry.user)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id:
            await self._handle_reaction_add(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id:
            await self._handle_reaction_remove(payload)

    # ══════════════════════════════════════════════════════════════════════════
    # NEXUS — Main settings group
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="nexus", aliases=["nx"])
    @commands.guild_only()
    async def nexus(self, ctx: commands.Context):
        """🔥 NexusCore — The ultimate server management suite."""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🔥 NexusCore v1.0.0",
                description=(
                    "The ultimate all-in-one server management cog.\n\n"
                    "**Modules:**\n"
                    "🎫 `[p]ticket` — Ticket system\n"
                    "📋 `[p]apply` — Applications\n"
                    "💡 `[p]suggest` — Suggestions\n"
                    "🎭 `[p]roles` — Reaction roles\n"
                    "🎉 `[p]giveaway` — Giveaways\n"
                    "📋 `[p]serverlog` — Logging\n"
                    "🛡️ `[p]nmod` — Moderation\n"
                    "🪙 `[p]eco` — Economy\n"
                ),
                colour=Clr.INFO,
            )
            embed.set_footer(text="Use [p]nexus <module> for module settings")
            await ctx.send(embed=embed)

    @nexus.command(name="dashboard")
    @checks.admin_or_permissions(administrator=True)
    async def nexus_dashboard(self, ctx: commands.Context):
        """View the status of all NexusCore modules."""
        t = await self.ticket_config.guild(ctx.guild).enabled()
        a = await self.app_config.guild(ctx.guild).enabled()
        s = await self.suggest_config.guild(ctx.guild).enabled()
        r = await self.rr_config.guild(ctx.guild).enabled()
        g = await self.give_config.guild(ctx.guild).enabled()
        l = await self.log_config.guild(ctx.guild).enabled()
        m = await self.mod_config.guild(ctx.guild).enabled()
        e = await self.eco_config.guild(ctx.guild).enabled()

        def status(v): return "✅ Enabled" if v else "❌ Disabled"

        embed = discord.Embed(title="📊 NexusCore Dashboard", colour=Clr.INFO)
        embed.add_field(name="🎫 Tickets", value=status(t), inline=True)
        embed.add_field(name="📋 Applications", value=status(a), inline=True)
        embed.add_field(name="💡 Suggestions", value=status(s), inline=True)
        embed.add_field(name="🎭 Reaction Roles", value=status(r), inline=True)
        embed.add_field(name="🎉 Giveaways", value=status(g), inline=True)
        embed.add_field(name="📋 Logging", value=status(l), inline=True)
        embed.add_field(name="🛡️ Moderation", value=status(m), inline=True)
        embed.add_field(name="🪙 Economy", value=status(e), inline=True)
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # TICKETS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="ticket", aliases=["tk"])
    @commands.guild_only()
    async def ticket(self, ctx: commands.Context):
        """🎫 Ticket system management."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticket.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_setup(self, ctx, channel: discord.TextChannel, category: discord.CategoryChannel):
        """Set up the ticket system with a log channel and category."""
        await self.ticket_config.guild(ctx.guild).enabled.set(True)
        await self.ticket_config.guild(ctx.guild).log_channel.set(channel.id)
        await self.ticket_config.guild(ctx.guild).category_id.set(category.id)
        await ctx.send(embed=ok_embed(f"Tickets enabled! Log: {channel.mention}, Category: {category.mention}"))

    @ticket.command(name="panel")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_panel(self, ctx, channel: discord.TextChannel, *, title: str = "Support Tickets"):
        """Send a ticket panel to a channel."""
        embed = discord.Embed(
            title=f"🎫 {title}",
            description="Click the button below to create a ticket.\nA staff member will assist you shortly.",
            colour=Clr.TICKET,
        )
        embed.set_footer(text="NexusCore Tickets")
        msg = await channel.send(embed=embed, view=self._ticket_panel_view)
        await ctx.send(embed=ok_embed(f"Panel sent to {channel.mention}!"))

    @ticket.command(name="addcategory", aliases=["addcat"])
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_addcategory(self, ctx, name: str, role: discord.Role, *, description: str = ""):
        """Add a ticket category with a staff role."""
        async with self.ticket_config.guild(ctx.guild).categories() as cats:
            cats[name.lower()] = {
                "description": description,
                "emoji": "🎫",
                "roles": [role.id],
                "questions": [],
                "greeting": "",
                "default_priority": "medium",
                "channel_name_fmt": f"ticket-{name.lower()}-{{number}}",
            }
        await ctx.send(embed=ok_embed(f"Category **{name}** added with role {role.mention}"))

    @ticket.command(name="addquestion")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_addquestion(self, ctx, category: str, *, question: str):
        """Add a question to a ticket category (shown in modal)."""
        async with self.ticket_config.guild(ctx.guild).categories() as cats:
            cat = cats.get(category.lower())
            if not cat:
                return await ctx.send(embed=err_embed(f"Category `{category}` not found."))
            if len(cat.get("questions", [])) >= 5:
                return await ctx.send(embed=err_embed("Max 5 questions per category (Discord modal limit)."))
            cat.setdefault("questions", []).append(question)
        await ctx.send(embed=ok_embed(f"Question added to **{category}**: {question}"))

    @ticket.command(name="transcript")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_transcript_channel(self, ctx, channel: discord.TextChannel):
        """Set the transcript channel."""
        await self.ticket_config.guild(ctx.guild).transcript_channel.set(channel.id)
        await ctx.send(embed=ok_embed(f"Transcripts will be sent to {channel.mention}"))

    @ticket.command(name="maxperuser")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_max(self, ctx, count: int):
        """Set max open tickets per user."""
        await self.ticket_config.guild(ctx.guild).max_per_user.set(count)
        await ctx.send(embed=ok_embed(f"Max tickets per user: {count}"))

    @ticket.command(name="blacklist")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_blacklist(self, ctx, user: discord.Member):
        """Blacklist a user from creating tickets."""
        async with self.ticket_config.guild(ctx.guild).blacklisted() as bl:
            if user.id in bl:
                bl.remove(user.id)
                await ctx.send(embed=ok_embed(f"{user.mention} removed from ticket blacklist."))
            else:
                bl.append(user.id)
                await ctx.send(embed=ok_embed(f"{user.mention} blacklisted from tickets."))

    @ticket.command(name="close")
    async def ticket_close_cmd(self, ctx):
        """Close the current ticket."""
        class _FakeInteraction:
            guild = ctx.guild
            channel = ctx.channel
            user = ctx.author
            async def response_send_message(self, *a, **k): await ctx.send(*a, **k)
            response = type("R", (), {"send_message": response_send_message, "defer": lambda s: asyncio.sleep(0)})()
        # Use a simpler approach
        ch_id = str(ctx.channel.id)
        data = await self.ticket_config.guild(ctx.guild).all()
        if ch_id not in data["open_tickets"]:
            return await ctx.send(embed=err_embed("This is not a ticket channel."))

        from .tickets import build_transcript_html
        ticket = data["open_tickets"][ch_id]
        async with self.ticket_config.guild(ctx.guild).open_tickets() as tickets:
            tickets[ch_id]["closed"] = True
        # Transcript
        transcript_ch_id = data.get("transcript_channel")
        if transcript_ch_id:
            ch = ctx.guild.get_channel(transcript_ch_id)
            if ch:
                import io
                html = await build_transcript_html(ctx.channel, ticket)
                file = discord.File(io.BytesIO(html.encode()), filename=f"transcript-{ticket.get('number',0)}.html")
                await safe_send(ch, file=file)

        await ctx.send(embed=info_embed("🔒 Ticket closed. Deleting in 10s..."))
        await asyncio.sleep(10)
        try:
            await ctx.channel.delete(reason=f"Ticket closed by {ctx.author}")
        except discord.HTTPException:
            pass

    @ticket.command(name="settings")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_settings(self, ctx):
        """View current ticket settings."""
        data = await self.ticket_config.guild(ctx.guild).all()
        embed = discord.Embed(title="🎫 Ticket Settings", colour=Clr.TICKET)
        embed.add_field(name="Enabled", value="✅" if data["enabled"] else "❌", inline=True)
        embed.add_field(name="Max/User", value=str(data["max_per_user"]), inline=True)
        embed.add_field(name="Claim", value="✅" if data["claim_enabled"] else "❌", inline=True)
        embed.add_field(name="Feedback", value="✅" if data["feedback_enabled"] else "❌", inline=True)
        embed.add_field(name="DM on Open", value="✅" if data["dm_on_open"] else "❌", inline=True)
        embed.add_field(name="DM on Close", value="✅" if data["dm_on_close"] else "❌", inline=True)
        cats = data.get("categories", {})
        if cats:
            embed.add_field(name="Categories", value=", ".join(cats.keys()), inline=False)
        await ctx.send(embed=embed)

    @ticket.command(name="toggle")
    @checks.admin_or_permissions(manage_guild=True)
    async def ticket_toggle(self, ctx, setting: str):
        """Toggle a ticket setting: claim, feedback, dm_open, dm_close, user_close, pin, thread."""
        toggles = {
            "claim": "claim_enabled", "feedback": "feedback_enabled",
            "dm_open": "dm_on_open", "dm_close": "dm_on_close",
            "user_close": "allow_user_close", "pin": "auto_pin_first",
            "thread": "thread_mode",
        }
        if setting not in toggles:
            return await ctx.send(embed=err_embed(f"Options: {', '.join(toggles.keys())}"))
        key = toggles[setting]
        current = await getattr(self.ticket_config.guild(ctx.guild), key)()
        await getattr(self.ticket_config.guild(ctx.guild), key).set(not current)
        await ctx.send(embed=ok_embed(f"**{setting}** {'disabled' if current else 'enabled'}"))

    # ══════════════════════════════════════════════════════════════════════════
    # APPLICATIONS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="apply", aliases=["app", "application"])
    @commands.guild_only()
    async def apply(self, ctx: commands.Context):
        """📋 Application system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @apply.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def app_setup(self, ctx, review_channel: discord.TextChannel):
        """Set up applications with a review channel."""
        await self.app_config.guild(ctx.guild).enabled.set(True)
        await self.app_config.guild(ctx.guild).review_channel.set(review_channel.id)
        await ctx.send(embed=ok_embed(f"Applications enabled! Review channel: {review_channel.mention}"))

    @apply.command(name="addtype")
    @checks.admin_or_permissions(manage_guild=True)
    async def app_addtype(self, ctx, name: str, *, description: str = ""):
        """Add an application type."""
        async with self.app_config.guild(ctx.guild).types() as types:
            types[name.lower()] = {
                "description": description,
                "emoji": "📋",
                "questions": [],
                "role_on_accept": None,
                "role_on_deny": None,
                "accept_msg": "",
                "deny_msg": "",
                "review_channel": None,
                "cooldown": 0,
                "max_pending": 1,
                "auto_thread": True,
                "require_account_age_days": 0,
                "require_server_days": 0,
                "enabled": True,
                "review_roles": [],
            }
        await ctx.send(embed=ok_embed(f"Application type **{name}** created."))

    @apply.command(name="addquestion")
    @checks.admin_or_permissions(manage_guild=True)
    async def app_addquestion(self, ctx, type_name: str, style: str, *, label: str):
        """Add a question: [p]apply addquestion staff short What is your timezone?"""
        if style not in ("short", "long"):
            return await ctx.send(embed=err_embed("Style must be `short` or `long`."))
        async with self.app_config.guild(ctx.guild).types() as types:
            t = types.get(type_name.lower())
            if not t:
                return await ctx.send(embed=err_embed(f"Type `{type_name}` not found."))
            t.setdefault("questions", []).append({"label": label, "style": style, "required": True, "max_length": 1024})
        await ctx.send(embed=ok_embed(f"Question added to **{type_name}**: {label}"))

    @apply.command(name="setrole")
    @checks.admin_or_permissions(manage_guild=True)
    async def app_setrole(self, ctx, type_name: str, action: str, role: discord.Role):
        """Set role given on accept/deny: [p]apply setrole staff accept @StaffRole"""
        if action not in ("accept", "deny"):
            return await ctx.send(embed=err_embed("Action must be `accept` or `deny`."))
        key = f"role_on_{action}"
        async with self.app_config.guild(ctx.guild).types() as types:
            t = types.get(type_name.lower())
            if not t:
                return await ctx.send(embed=err_embed(f"Type `{type_name}` not found."))
            t[key] = role.id
        await ctx.send(embed=ok_embed(f"**{type_name}** — {action} role set to {role.mention}"))

    @apply.command(name="panel")
    @checks.admin_or_permissions(manage_guild=True)
    async def app_panel(self, ctx, channel: discord.TextChannel):
        """Send an application panel to a channel."""
        types = await self.app_config.guild(ctx.guild).types()
        desc = "\n".join(f"• **{name.title()}** — {td.get('description', '')}" for name, td in types.items())
        embed = discord.Embed(
            title="📋 Applications",
            description=f"Click below to apply!\n\n{desc}" if desc else "Click below to apply!",
            colour=Clr.APP,
        )
        await channel.send(embed=embed, view=self._app_panel_view)
        await ctx.send(embed=ok_embed(f"Application panel sent to {channel.mention}"))

    @apply.command(name="list")
    @checks.admin_or_permissions(manage_guild=True)
    async def app_list(self, ctx, status: str = "pending"):
        """List applications by status: pending, accepted, denied, interview."""
        subs = await self.app_config.guild(ctx.guild).submissions()
        filtered = {k: v for k, v in subs.items() if v["status"] == status}
        if not filtered:
            return await ctx.send(embed=info_embed(f"No {status} applications."))

        pages = []
        for chunk in chunk_list(list(filtered.items()), 5):
            embed = discord.Embed(title=f"📋 Applications — {status.title()}", colour=Clr.APP)
            for sub_id, sub in chunk:
                embed.add_field(
                    name=f"{sub_id} — {sub.get('user_name', 'Unknown')}",
                    value=f"Type: {sub['type']} · {ts_relative(sub['submitted_at'])}",
                    inline=False,
                )
            pages.append(embed)

        pag = Paginator(pages, author_id=ctx.author.id)
        await pag.send(ctx)

    # ══════════════════════════════════════════════════════════════════════════
    # SUGGESTIONS
    # ══════════════════════════════════════════════════════════════════════════

    @commands.group(name="suggest", aliases=["suggestion"])
    @commands.guild_only()
    async def suggest(self, ctx: commands.Context):
        """💡 Suggestion system."""
        if ctx.invoked_subcommand is None:
            # Quick-suggest if text provided
            if ctx.message.content.strip().split(None, 1).__len__() > 1:
                text = ctx.message.content.strip().split(None, 1)[1]
                return await self._quick_suggest(ctx, text)
            await ctx.send_help(ctx.command)

    async def _quick_suggest(self, ctx, text):
        data = await self.suggest_config.guild(ctx.guild).all()
        if not data["enabled"]:
            return await ctx.send(embed=err_embed("Suggestions are disabled."))
        if len(text) < data["min_length"]:
            return await ctx.send(embed=err_embed(f"Suggestion must be at least {data['min_length']} chars."))

        class _FakeInteraction:
            guild = ctx.guild
            user = ctx.author
        await self._create_suggestion(_FakeInteraction(), text)
        await ctx.send(embed=ok_embed("Suggestion submitted!"), delete_after=5)
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

    @suggest.command(name="setup")
    @checks.admin_or_permissions(manage_guild=True)
    async def suggest_setup(self, ctx, channel: discord.TextChannel):
        """Set the suggestions channel."""
        await self.suggest_config.guild(ctx.guild).enabled.set(True)
        await self.suggest_config.guild(ctx.guild).channel.set(channel.id)
        await ctx.send(embed=ok_embed(f"Suggestions enabled in {channel.mention}"))

    @suggest.command(name="status")
    @checks.admin_or_permissions(manage_messages=True)
    async def suggest_status(self, ctx, suggestion_id: str):
        """Change a suggestion's status."""
        from .suggestions import StatusSelectView
        view = StatusSelectView(self, suggestion_id)
        await ctx.send("Select a status:", view=view)

    @suggest.command(name="respond")
    @checks.admin_or_permissions(manage_messages=True)
    async def suggest_respond(self, ctx, suggestion_id: str, *, response: str):
        """Add a staff response to a suggestion."""
        data = await self.suggest_config.guild(ctx.guild).all()
        s = data["suggestions"].get(suggestion_id)
        if not s:
            return await ctx.send(embed=err_embed("Not found."))

        async with self.suggest_config.guild(ctx.guild).suggestions() as subs:
            subs[suggestion_id]["staff_response"] = response

        channel = ctx.guild.get_channel(data["channel"])
        if channel and s.get("message_id"):
            try:
                msg = await channel.fetch_message(s["message_id"])
                if msg.embeds:
                    embed = msg.embeds[0]
                    embed.add_field(name="💬 Staff Response", value=response[:1024], inline=False)
                    await msg.edit(embed=embed)
            except discord.HTTPException:
                pass
        await ctx.send(embed=ok_embed("Response added."))

    @suggest.command(name="panel")
    @checks.admin_or_permissions(manage_guild=True)
    async def suggest_panel(self, ctx, channel: discord.TextChannel):
        """Send a suggestion panel with buttons."""
        embed = discord.Embed(
            title="💡 Suggestions",
            description="Click below to submit a suggestion!",
            colour=Clr.SUGGEST,
        )
        await channel.send(embed=embed, view=self._suggest_panel_view)
        await ctx.send(embed=ok_embed(f"Suggestion panel sent to {channel.mention}"))

    @suggest.command(name="top")
    async def suggest_top(self, ctx, limit: int = 10):
        """View top voted suggestions."""
        data = await self.suggest_config.guild(ctx.guild).all()
        subs = data["suggestions"]
        sorted_subs = sorted(subs.items(), key=lambda x: len(x[1].get("upvotes", [])) - len(x[1].get("downvotes", [])), reverse=True)
        embed = discord.Embed(title="💡 Top Suggestions", colour=Clr.SUGGEST)
        for s_id, s in sorted_subs[:limit]:
            score = len(s.get("upvotes", [])) - len(s.get("downvotes", []))
            embed.add_field(
                name=f"#{s_id} ({score:+d})",
                value=s["content"][:100],
                inline=False,
            )
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
            response = type("R", (), {"send_message": response_send_message})()
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
        from .serverlog import EVENT_TYPES
        if event_type not in EVENT_TYPES:
            return await ctx.send(embed=err_embed(f"Valid types: {', '.join(EVENT_TYPES)}"))
        async with self.log_config.guild(ctx.guild).channels() as channels:
            channels[event_type] = channel.id
        await ctx.send(embed=ok_embed(f"`{event_type}` → {channel.mention}"))

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

    @serverlog.command(name="settings")
    async def slog_settings(self, ctx):
        """View logging settings."""
        data = await self.log_config.guild(ctx.guild).all()
        embed = discord.Embed(title="📋 Logging Settings", colour=Clr.LOG)
        embed.add_field(name="Enabled", value="✅" if data["enabled"] else "❌", inline=True)
        dc = ctx.guild.get_channel(data["default_channel"]) if data["default_channel"] else None
        embed.add_field(name="Default Channel", value=dc.mention if dc else "Not set", inline=True)
        embed.add_field(name="Ignore Bots", value="✅" if data["ignore_bots"] else "❌", inline=True)
        overrides = []
        for evt, ch_id in data.get("channels", {}).items():
            ch = ctx.guild.get_channel(ch_id)
            if ch:
                overrides.append(f"`{evt}` → {ch.mention}")
        if overrides:
            embed.add_field(name="Channel Overrides", value="\n".join(overrides), inline=False)
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
                value=n["text"][:1024],
                inline=False,
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
                value=f"{w['reason']} (by <@{w['mod_id']}>)",
                inline=False,
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
                    value=f"{c['reason'][:200]} (by <@{c['mod_id']}>)",
                    inline=False,
                )
            pages.append(embed)
        pag = Paginator(pages, author_id=ctx.author.id)
        await pag.send(ctx)

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
            "enabled": enabled,
            "join_threshold": threshold,
            "join_window": window,
            "action": action,
            "notify_channel": ctx.channel.id,
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

    @nmod.command(name="appeal")
    @checks.admin_or_permissions(administrator=True)
    async def nmod_appeal(self, ctx, channel: discord.TextChannel):
        """Set the appeal channel and enable appeals."""
        await self.mod_config.guild(ctx.guild).appeal_channel.set(channel.id)
        await self.mod_config.guild(ctx.guild).appeal_enabled.set(True)
        await ctx.send(embed=ok_embed(f"Appeals enabled! Channel: {channel.mention}"))

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
        name = data["currency_name"]
        embed = discord.Embed(title=f"{emoji} {user.display_name}'s Balance", colour=Clr.ECO)
        embed.add_field(name="Wallet", value=f"{emoji} {wallet:,}", inline=True)
        embed.add_field(name="Bank", value=f"{emoji} {bank:,}", inline=True)
        embed.add_field(name="Total", value=f"{emoji} {wallet + bank:,}", inline=True)
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        await ctx.send(embed=embed)

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

        embed = discord.Embed(
            title=f"{emoji} Leaderboard",
            description="\n".join(lines),
            colour=Clr.ECO,
        )
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

    @eco.command(name="addroletiem", aliases=["addroleitem"])
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
            guild_data = await self.eco_config.guild(ctx.guild).all()
            types = guild_data.get("pets", {}).get("types", {})
            available = "\n".join(f"{v['emoji']} **{k}** — {v['base_price']:,} coins" for k, v in types.items())
            return await ctx.send(embed=info_embed(f"You have no pets.\n\nAvailable:\n{available}\n\nBuy: `[p]eco buypet <type> <name>`"))

        guild_data = await self.eco_config.guild(ctx.guild).all()
        types = guild_data.get("pets", {}).get("types", {})
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

    @eco.command(name="settings")
    @checks.admin_or_permissions(manage_guild=True)
    async def eco_settings(self, ctx):
        """View economy settings."""
        data = await self.eco_config.guild(ctx.guild).all()
        embed = discord.Embed(title="🪙 Economy Settings", colour=Clr.ECO)
        embed.add_field(name="Currency", value=f"{data['currency_emoji']} {data['currency_name']}", inline=True)
        embed.add_field(name="Daily", value=str(data['daily_amount']), inline=True)
        embed.add_field(name="Weekly", value=str(data['weekly_amount']), inline=True)
        embed.add_field(name="Work", value=f"{data['work_min']}-{data['work_max']}", inline=True)
        embed.add_field(name="Crime", value=f"{data['crime_min']}-{data['crime_max']} ({data['crime_fail_chance']}% fail)", inline=True)
        embed.add_field(name="Rob", value="✅" if data['rob_enabled'] else "❌", inline=True)
        embed.add_field(name="Tax", value=f"{data['tax_rate']}%", inline=True)
        embed.add_field(name="Interest", value=f"{data['interest_rate']}%", inline=True)
        embed.add_field(name="Shop Items", value=str(len(data.get('shop_items', {}))), inline=True)
        await ctx.send(embed=embed)
