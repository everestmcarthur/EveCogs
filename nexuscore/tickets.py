"""NexusCore — Ticket system v2: panels, categories, transcripts, claims, priorities,
feedback, auto-close, tags, staff tracking, archive, reopen, add/remove user, rename,
custom open/close messages, inactivity timer."""

from __future__ import annotations

import asyncio
import datetime
import io
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    ts_full, duration_str, parse_duration, safe_send, safe_dm, ConfirmView, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
TICKET_DEFAULTS_GUILD = {
    "enabled": False,
    "category_id": None,
    "log_channel": None,
    "transcript_channel": None,
    "archive_channel": None,
    "counter": 0,
    "panels": {},
    "categories": {},
    "open_tickets": {},
    "closed_tickets": {},
    "blacklisted": [],
    "max_per_user": 3,
    "auto_close_hours": 0,
    "thread_mode": False,
    "claim_enabled": True,
    "feedback_enabled": True,
    "dm_on_open": True,
    "dm_on_close": True,
    "mention_on_open": True,
    "naming_format": "ticket-{number}",
    "close_confirm": True,
    "auto_pin_first": True,
    "allow_rename": True,
    "allow_user_close": True,
    "allow_reopen": True,
    "transcript_format": "html",
    "custom_open_msg": "",
    "custom_close_msg": "",
    "tags": {},            # tag_name -> {colour, description}
    "staff_roles": [],
}

TICKET_DEFAULTS_MEMBER = {
    "tickets_opened": 0,
    "tickets_closed": 0,
    "feedback_given": [],
    "avg_response_time": 0,
    "tickets_claimed": 0,
}


# ── Transcript builder ────────────────────────────────────────────────────
async def build_transcript_html(channel: discord.TextChannel, ticket_info: dict) -> str:
    messages = []
    async for msg in channel.history(limit=500, oldest_first=True):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.content or ""
        attachments = " ".join(f'<a href="{a.url}">[{a.filename}]</a>' for a in msg.attachments)
        embeds_html = ""
        for emb in msg.embeds:
            if emb.description:
                embeds_html += f'<div class="embed"><strong>{emb.title or ""}</strong><br>{emb.description}</div>'
        avatar = msg.author.display_avatar.url if msg.author.display_avatar else ""
        messages.append(
            f'<div class="msg">'
            f'<img class="avatar" src="{avatar}" />'
            f'<div class="body">'
            f'<span class="author" style="color:{"#5865F2" if msg.author.bot else "#FFFFFF"}">{msg.author.display_name}</span>'
            f'<span class="ts">{ts}</span>'
            f'<div class="content">{content}</div>'
            f'{attachments}{embeds_html}'
            f'</div></div>'
        )

    msgs_html = "\n".join(messages)
    tags = ticket_info.get("tags", [])
    tags_html = " ".join(f'<span class="tag">{t}</span>' for t in tags) if tags else ""
    claimed = ticket_info.get("claimed_by")
    claimed_str = f" · Claimed by: {claimed}" if claimed else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ticket Transcript</title>
<style>
body {{ background: #36393f; color: #dcddde; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
.header {{ background: #2f3136; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
.header h1 {{ color: #fff; margin: 0; font-size: 1.4em; }}
.header p {{ color: #72767d; margin: 4px 0 0; }}
.tag {{ background: #5865f2; color: #fff; padding: 2px 8px; border-radius: 4px; margin-right: 4px; font-size: 0.85em; }}
.msg {{ display: flex; padding: 8px 16px; }}
.msg:hover {{ background: #32353b; }}
.avatar {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 12px; flex-shrink: 0; }}
.author {{ font-weight: 600; margin-right: 8px; }}
.ts {{ color: #72767d; font-size: 0.75em; }}
.content {{ margin-top: 2px; white-space: pre-wrap; word-wrap: break-word; }}
.embed {{ background: #2f3136; border-left: 4px solid #5865F2; padding: 8px 12px; margin-top: 4px; border-radius: 4px; }}
a {{ color: #00aff4; }}
</style></head><body>
<div class="header">
<h1>Ticket Transcript — #{ticket_info.get("number", "?")}</h1>
<p>Category: {ticket_info.get("category", "General")} · Opened by: {ticket_info.get("user_name", "Unknown")} · {ticket_info.get("opened_at_str", "")}{claimed_str}</p>
{tags_html}
</div>
{msgs_html}
</body></html>"""


# ── Views ──────────────────────────────────────────────────────────────────
class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "TicketsMixin"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🎫 Create Ticket", style=discord.ButtonStyle.primary, custom_id="nexus_ticket_create")
    async def create_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_ticket(interaction, None)

    async def _open_ticket(self, interaction: discord.Interaction, category_name: str | None):
        guild = interaction.guild
        if not guild:
            return
        conf = self.cog.ticket_config.guild(guild)
        data = await conf.all()

        if not data["enabled"]:
            return await interaction.response.send_message("Tickets are disabled.", ephemeral=True)

        if str(interaction.user.id) in [str(x) for x in data["blacklisted"]]:
            return await interaction.response.send_message("You are blacklisted from tickets.", ephemeral=True)

        user_open = sum(
            1 for t in data["open_tickets"].values()
            if str(t.get("user_id")) == str(interaction.user.id) and not t.get("closed")
        )
        if user_open >= data["max_per_user"]:
            return await interaction.response.send_message(
                f"You already have {user_open} open ticket(s) (max {data['max_per_user']}).", ephemeral=True
            )

        cats = data["categories"]
        if not category_name and cats:
            if len(cats) == 1:
                category_name = list(cats.keys())[0]
            else:
                view = CategorySelectView(self.cog, list(cats.keys()), cats)
                return await interaction.response.send_message("Select a category:", view=view, ephemeral=True)

        cat_data = cats.get(category_name, {}) if category_name else {}
        questions = cat_data.get("questions", [])
        if questions:
            modal = TicketFormModal(self.cog, category_name, questions)
            return await interaction.response.send_modal(modal)

        await interaction.response.defer(ephemeral=True)
        ch = await self.cog._create_ticket_channel(interaction, category_name, {})
        if ch:
            await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)


class CategorySelectView(discord.ui.View):
    def __init__(self, cog, cat_names: list[str], cats_data: dict):
        super().__init__(timeout=60)
        options = []
        for name in cat_names[:25]:
            cd = cats_data.get(name, {})
            options.append(discord.SelectOption(
                label=name.title(), value=name,
                description=(cd.get("description", "") or "")[:100],
                emoji=cd.get("emoji") or "🎫",
            ))
        self.select = discord.ui.Select(placeholder="Choose a category...", options=options, custom_id="nexus_cat_sel")
        self.select.callback = self.on_select
        self.add_item(self.select)
        self.cog = cog

    async def on_select(self, interaction: discord.Interaction):
        cat_name = self.select.values[0]
        cats = await self.cog.ticket_config.guild(interaction.guild).categories()
        cat_data = cats.get(cat_name, {})
        questions = cat_data.get("questions", [])
        if questions:
            modal = TicketFormModal(self.cog, cat_name, questions)
            return await interaction.response.send_modal(modal)
        await interaction.response.defer(ephemeral=True)
        ch = await self.cog._create_ticket_channel(interaction, cat_name, {})
        if ch:
            await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)


class TicketFormModal(discord.ui.Modal):
    def __init__(self, cog, category: str | None, questions: list[str]):
        super().__init__(title=f"Ticket — {category or 'New'}"[:45])
        self.cog = cog
        self.category = category
        self.inputs = []
        for i, q in enumerate(questions[:5]):
            inp = discord.ui.TextInput(
                label=q[:45],
                style=discord.TextStyle.paragraph if len(q) > 30 else discord.TextStyle.short,
                required=True, max_length=1024,
            )
            self.inputs.append(inp)
            self.add_item(inp)

    async def on_submit(self, interaction: discord.Interaction):
        answers = {self.inputs[i].label: self.inputs[i].value for i in range(len(self.inputs))}
        await interaction.response.defer(ephemeral=True)
        ch = await self.cog._create_ticket_channel(interaction, self.category, answers)
        if ch:
            await interaction.followup.send(f"Ticket created: {ch.mention}", ephemeral=True)


class TicketControlView(discord.ui.View):
    def __init__(self, cog: "TicketsMixin"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="nexus_ticket_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._close_ticket(interaction)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="🙋", custom_id="nexus_ticket_claim")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._claim_ticket(interaction)

    @discord.ui.button(label="Priority", style=discord.ButtonStyle.secondary, emoji="⚡", custom_id="nexus_ticket_prio")
    async def priority_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PrioritySelectView(self.cog)
        await interaction.response.send_message("Set priority:", view=view, ephemeral=True)

    @discord.ui.button(label="Tag", style=discord.ButtonStyle.secondary, emoji="🏷️", custom_id="nexus_ticket_tag")
    async def tag_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.cog.ticket_config.guild(interaction.guild).all()
        tags = data.get("tags", {})
        if not tags:
            return await interaction.response.send_message("No tags configured.", ephemeral=True)
        view = TagSelectView(self.cog, tags)
        await interaction.response.send_message("Apply a tag:", view=view, ephemeral=True)


class PrioritySelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=30)
        self.cog = cog
        opts = [
            discord.SelectOption(label="Low", value="low", emoji="🟢"),
            discord.SelectOption(label="Medium", value="medium", emoji="🟡"),
            discord.SelectOption(label="High", value="high", emoji="🟠"),
            discord.SelectOption(label="Urgent", value="urgent", emoji="🔴"),
        ]
        self.sel = discord.ui.Select(options=opts, placeholder="Priority level")
        self.sel.callback = self.on_select
        self.add_item(self.sel)

    async def on_select(self, interaction: discord.Interaction):
        prio = self.sel.values[0]
        ch_id = str(interaction.channel.id)
        async with self.cog.ticket_config.guild(interaction.guild).open_tickets() as tickets:
            if ch_id in tickets:
                tickets[ch_id]["priority"] = prio
        prio_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "urgent": "🔴"}
        await interaction.response.send_message(f"{prio_emoji.get(prio, '⚡')} Priority set to **{prio.title()}**")
        self.stop()


class TagSelectView(discord.ui.View):
    def __init__(self, cog, tags: dict):
        super().__init__(timeout=30)
        self.cog = cog
        opts = [discord.SelectOption(label=name.title(), value=name, description=(t.get("description", "") or "")[:100]) for name, t in list(tags.items())[:25]]
        self.sel = discord.ui.Select(options=opts, placeholder="Tag...")
        self.sel.callback = self.on_select
        self.add_item(self.sel)

    async def on_select(self, interaction: discord.Interaction):
        tag = self.sel.values[0]
        ch_id = str(interaction.channel.id)
        async with self.cog.ticket_config.guild(interaction.guild).open_tickets() as tickets:
            if ch_id in tickets:
                tickets[ch_id].setdefault("tags", [])
                if tag not in tickets[ch_id]["tags"]:
                    tickets[ch_id]["tags"].append(tag)
        await interaction.response.send_message(f"🏷️ Tag **{tag}** applied!")
        self.stop()


class FeedbackModal(discord.ui.Modal):
    def __init__(self, cog, channel_id: str):
        super().__init__(title="Ticket Feedback")
        self.cog = cog
        self.channel_id = channel_id
        self.rating = discord.ui.TextInput(label="Rating (1-5 stars)", placeholder="5", max_length=1, required=True)
        self.comments = discord.ui.TextInput(label="Comments (optional)", style=discord.TextStyle.paragraph, required=False, max_length=500)
        self.add_item(self.rating)
        self.add_item(self.comments)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            r = max(1, min(5, int(self.rating.value)))
        except ValueError:
            r = 5
        stars = "⭐" * r
        await interaction.response.send_message(f"Thanks for your feedback! {stars}", ephemeral=True)
        log_ch_id = await self.cog.ticket_config.guild(interaction.guild).log_channel()
        if log_ch_id:
            log_ch = interaction.guild.get_channel(log_ch_id)
            if log_ch:
                e = discord.Embed(title="Ticket Feedback", colour=Clr.TICKET)
                e.add_field(name="Rating", value=stars, inline=True)
                e.add_field(name="User", value=interaction.user.mention, inline=True)
                if self.comments.value:
                    e.add_field(name="Comments", value=self.comments.value, inline=False)
                await safe_send(log_ch, embed=e)


class FeedbackButtonView(discord.ui.View):
    def __init__(self, cog, channel_id: str):
        super().__init__(timeout=3600)
        self.cog = cog
        self.channel_id = channel_id

    @discord.ui.button(label="Leave Feedback", style=discord.ButtonStyle.primary, emoji="📝")
    async def feedback_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = FeedbackModal(self.cog, self.channel_id)
        await interaction.response.send_modal(modal)
        self.stop()


# ── Mixin ──────────────────────────────────────────────────────────────────
class TicketsMixin:
    """Ticket system mixin — v2 with auto-close, tags, staff tracking, archive, reopen."""

    def _init_tickets(self, bot):
        self.ticket_config = Config.get_conf(None, identifier=900001, cog_name="NexusCoreTickets")
        self.ticket_config.register_guild(**TICKET_DEFAULTS_GUILD)
        self.ticket_config.register_member(**TICKET_DEFAULTS_MEMBER)

        self._ticket_panel_view = TicketPanelView(self)
        self._ticket_control_view = TicketControlView(self)
        bot.add_view(self._ticket_panel_view)
        bot.add_view(self._ticket_control_view)
        self._auto_close_tasks = {}

    async def _start_auto_close_loop(self):
        """Check for inactive tickets to auto-close."""
        while True:
            try:
                for guild in self.bot.guilds:
                    data = await self.ticket_config.guild(guild).all()
                    hours = data.get("auto_close_hours", 0)
                    if not hours or not data["enabled"]:
                        continue
                    threshold = ts_now() - (hours * 3600)
                    for ch_id, ticket in list(data["open_tickets"].items()):
                        if ticket.get("closed"):
                            continue
                        last_activity = ticket.get("last_activity", ticket.get("opened_at", 0))
                        if last_activity < threshold:
                            channel = guild.get_channel(int(ch_id))
                            if channel:
                                await channel.send(embed=discord.Embed(
                                    description=f"⏰ This ticket will be auto-closed due to {hours}h of inactivity.\nSend a message to keep it open.",
                                    colour=Clr.TICKET,
                                ))
                                # Give 5 min grace
                                await asyncio.sleep(300)
                                # Re-check
                                fresh = await self.ticket_config.guild(guild).open_tickets()
                                t = fresh.get(ch_id)
                                if t and not t.get("closed"):
                                    la = t.get("last_activity", t.get("opened_at", 0))
                                    if la < threshold:
                                        async with self.ticket_config.guild(guild).open_tickets() as tickets:
                                            if ch_id in tickets:
                                                tickets[ch_id]["closed"] = True
                                                tickets[ch_id]["closed_at"] = ts_now()
                                                tickets[ch_id]["closed_by"] = "auto"
                                        await channel.send(embed=discord.Embed(
                                            description="🔒 Auto-closed due to inactivity. Deleting in 30s...",
                                            colour=Clr.ERROR,
                                        ))
                                        await asyncio.sleep(30)
                                        try:
                                            await channel.delete(reason="Auto-close inactivity")
                                        except discord.HTTPException:
                                            pass
            except Exception:
                pass
            await asyncio.sleep(600)  # Check every 10 min

    async def _update_ticket_activity(self, message: discord.Message):
        """Update last activity timestamp for a ticket channel."""
        if not message.guild:
            return
        ch_id = str(message.channel.id)
        data = await self.ticket_config.guild(message.guild).open_tickets()
        if ch_id in data and not data[ch_id].get("closed"):
            async with self.ticket_config.guild(message.guild).open_tickets() as tickets:
                if ch_id in tickets:
                    tickets[ch_id]["last_activity"] = ts_now()
                    # Track first staff response time
                    if not tickets[ch_id].get("first_response_at"):
                        staff_roles = await self.ticket_config.guild(message.guild).staff_roles()
                        is_staff = message.author.guild_permissions.manage_channels or any(r.id in staff_roles for r in message.author.roles)
                        if is_staff and message.author.id != tickets[ch_id].get("user_id"):
                            tickets[ch_id]["first_response_at"] = ts_now()

    # ── Internal helpers ───────────────────────────────────────────────────
    async def _create_ticket_channel(self, interaction, category_name, answers):
        guild = interaction.guild
        conf = self.ticket_config.guild(guild)
        counter = await conf.counter()
        counter += 1
        await conf.counter.set(counter)

        data = await conf.all()
        cat_data = data["categories"].get(category_name, {}) if category_name else {}
        fmt = cat_data.get("channel_name_fmt") or data["naming_format"]
        ch_name = fmt.format(number=counter, user=interaction.user.name, category=category_name or "general")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        for role_id in cat_data.get("roles", []):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        disc_cat = guild.get_channel(data["category_id"]) if data["category_id"] else None
        try:
            channel = await guild.create_text_channel(ch_name, category=disc_cat, overwrites=overwrites,
                topic=f"Ticket #{counter} · {interaction.user} · {category_name or 'General'}")
        except discord.HTTPException:
            return None

        ticket_info = {
            "user_id": interaction.user.id, "user_name": str(interaction.user),
            "category": category_name or "general",
            "opened_at": ts_now(),
            "opened_at_str": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "number": counter, "claimed_by": None,
            "priority": cat_data.get("default_priority", "medium"),
            "closed": False, "answers": answers, "tags": [],
            "last_activity": ts_now(), "first_response_at": None,
            "participants": [interaction.user.id],
        }
        async with conf.open_tickets() as tickets:
            tickets[str(channel.id)] = ticket_info

        # Custom or default greeting
        greeting = data.get("custom_open_msg") or cat_data.get("greeting") or f"Welcome, {interaction.user.mention}! A staff member will be with you shortly."
        greeting = greeting.replace("{user}", interaction.user.mention).replace("{category}", category_name or "General").replace("{ticket_id}", str(counter))

        prio_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(ticket_info["priority"], "🟡")
        embed = discord.Embed(title=f"🎫 Ticket #{counter}", description=greeting, colour=Clr.TICKET,
            timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="Category", value=category_name or "General", inline=True)
        embed.add_field(name="Priority", value=f"{prio_emoji} {ticket_info['priority'].title()}", inline=True)
        embed.add_field(name="Opened by", value=interaction.user.mention, inline=True)
        if answers:
            for q, a in answers.items():
                embed.add_field(name=q, value=a[:1024], inline=False)
        embed.set_footer(text="Use the buttons below to manage this ticket")

        msg = await channel.send(embed=embed, view=self._ticket_control_view)
        if data["auto_pin_first"]:
            try:
                await msg.pin()
            except discord.HTTPException:
                pass

        if data["mention_on_open"]:
            mentions = " ".join(f"<@&{r}>" for r in cat_data.get("roles", []))
            if mentions:
                m = await channel.send(mentions)
                try:
                    await m.delete(delay=3)
                except discord.HTTPException:
                    pass

        if data["dm_on_open"]:
            await safe_dm(interaction.user, embed=discord.Embed(
                description=f"Your ticket **#{counter}** has been created in **{guild.name}**!\n{channel.mention}",
                colour=Clr.TICKET,
            ))

        await self._ticket_member_update(guild, interaction.user, "tickets_opened", 1)

        log_ch_id = data["log_channel"]
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(title="🎫 Ticket Opened", colour=Clr.TICKET)
                le.add_field(name="Ticket", value=f"#{counter} ({channel.mention})", inline=True)
                le.add_field(name="User", value=interaction.user.mention, inline=True)
                le.add_field(name="Category", value=category_name or "General", inline=True)
                await safe_send(log_ch, embed=le)

        return channel

    async def _ticket_member_update(self, guild, member, key, increment):
        current = await getattr(self.ticket_config.member(member), key)()
        await getattr(self.ticket_config.member(member), key).set(current + increment)

    async def _close_ticket(self, interaction):
        guild = interaction.guild
        ch_id = str(interaction.channel.id)
        data = await self.ticket_config.guild(guild).all()
        ticket = data["open_tickets"].get(ch_id)
        if not ticket:
            return await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
        if ticket.get("closed"):
            return await interaction.response.send_message("Already closed.", ephemeral=True)
        if not data["allow_user_close"] and interaction.user.id == ticket["user_id"]:
            if not interaction.user.guild_permissions.manage_channels:
                return await interaction.response.send_message("Only staff can close tickets.", ephemeral=True)

        if data["close_confirm"]:
            view = ConfirmView(interaction.user.id)
            await interaction.response.send_message("Are you sure you want to close this ticket?", view=view, ephemeral=True)
            await view.wait()
            if not view.value:
                return
        else:
            await interaction.response.defer()

        async with self.ticket_config.guild(guild).open_tickets() as tickets:
            if ch_id in tickets:
                tickets[ch_id]["closed"] = True
                tickets[ch_id]["closed_at"] = ts_now()
                tickets[ch_id]["closed_by"] = interaction.user.id

        # Archive to closed_tickets for stats
        async with self.ticket_config.guild(guild).closed_tickets() as closed:
            closed[ch_id] = dict(ticket)
            closed[ch_id]["closed_at"] = ts_now()
            closed[ch_id]["closed_by"] = interaction.user.id

        # Transcript
        transcript_ch_id = data.get("transcript_channel")
        if transcript_ch_id:
            transcript_ch = guild.get_channel(transcript_ch_id)
            if transcript_ch:
                html = await build_transcript_html(interaction.channel, ticket)
                file = discord.File(io.BytesIO(html.encode()), filename=f"transcript-{ticket.get('number', 0)}.html")
                te = discord.Embed(title=f"📄 Transcript — Ticket #{ticket.get('number', 0)}", colour=Clr.TICKET)
                te.add_field(name="User", value=f"<@{ticket['user_id']}>", inline=True)
                te.add_field(name="Closed by", value=interaction.user.mention, inline=True)
                te.add_field(name="Category", value=ticket.get("category", "General"), inline=True)
                if ticket.get("tags"):
                    te.add_field(name="Tags", value=", ".join(ticket["tags"]), inline=True)
                if ticket.get("first_response_at"):
                    response_time = ticket["first_response_at"] - ticket["opened_at"]
                    te.add_field(name="First Response", value=duration_str(response_time), inline=True)
                await safe_send(transcript_ch, embed=te, file=file)

        # Custom close message
        close_msg = data.get("custom_close_msg") or "🔒 This ticket has been closed."
        if data["dm_on_close"]:
            user = guild.get_member(ticket["user_id"])
            if user:
                await safe_dm(user, embed=discord.Embed(
                    description=f"Your ticket **#{ticket.get('number', 0)}** in **{guild.name}** has been closed.",
                    colour=Clr.TICKET,
                ))

        if data["feedback_enabled"]:
            user = guild.get_member(ticket["user_id"])
            if user:
                try:
                    await user.send("Please rate your support experience!", view=FeedbackButtonView(self, ch_id))
                except discord.HTTPException:
                    pass

        log_ch_id = data["log_channel"]
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(title="🔒 Ticket Closed", colour=Clr.ERROR)
                le.add_field(name="Ticket", value=f"#{ticket.get('number', 0)}", inline=True)
                le.add_field(name="Closed by", value=interaction.user.mention, inline=True)
                await safe_send(log_ch, embed=le)

        # Archive channel option (move instead of delete)
        archive_ch_id = data.get("archive_channel")
        if archive_ch_id:
            archive_cat = guild.get_channel(archive_ch_id)
            if archive_cat and isinstance(archive_cat, discord.CategoryChannel):
                try:
                    await interaction.channel.edit(
                        category=archive_cat,
                        overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False, send_messages=False)},
                        reason="Ticket archived",
                    )
                    await interaction.channel.send(embed=discord.Embed(description=close_msg, colour=Clr.ERROR))
                    return  # Don't delete if archiving
                except discord.HTTPException:
                    pass

        await interaction.channel.send(embed=discord.Embed(description=f"{close_msg}\nDeleting in 10 seconds...", colour=Clr.ERROR))
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason=f"Ticket #{ticket.get('number', 0)} closed")
        except discord.HTTPException:
            pass

    async def _claim_ticket(self, interaction):
        guild = interaction.guild
        ch_id = str(interaction.channel.id)
        data = await self.ticket_config.guild(guild).all()
        ticket = data["open_tickets"].get(ch_id)
        if not ticket:
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        if not data["claim_enabled"]:
            return await interaction.response.send_message("Claim system is disabled.", ephemeral=True)
        if ticket.get("claimed_by"):
            return await interaction.response.send_message(f"Already claimed by <@{ticket['claimed_by']}>.", ephemeral=True)

        async with self.ticket_config.guild(guild).open_tickets() as tickets:
            if ch_id in tickets:
                tickets[ch_id]["claimed_by"] = interaction.user.id
        await self._ticket_member_update(guild, interaction.user, "tickets_claimed", 1)

        await interaction.response.send_message(embed=discord.Embed(
            description=f"🙋 **{interaction.user.display_name}** claimed this ticket.", colour=Clr.SUCCESS,
        ))

    async def _reopen_ticket(self, ctx, channel: discord.TextChannel):
        """Reopen a closed/archived ticket."""
        ch_id = str(channel.id)
        data = await self.ticket_config.guild(ctx.guild).all()
        ticket = data["open_tickets"].get(ch_id)
        if not ticket or not ticket.get("closed"):
            return False
        if not data.get("allow_reopen"):
            return False

        async with self.ticket_config.guild(ctx.guild).open_tickets() as tickets:
            if ch_id in tickets:
                tickets[ch_id]["closed"] = False
                tickets[ch_id].pop("closed_at", None)
                tickets[ch_id].pop("closed_by", None)
                tickets[ch_id]["last_activity"] = ts_now()

        # Restore permissions
        user = ctx.guild.get_member(ticket["user_id"])
        if user:
            await channel.set_permissions(user, view_channel=True, send_messages=True)

        await channel.send(embed=discord.Embed(
            description=f"🔓 Ticket reopened by {ctx.author.mention}.", colour=Clr.SUCCESS,
        ))
        return True

    async def _add_user_to_ticket(self, ctx, user: discord.Member):
        """Add a user to the current ticket channel."""
        ch_id = str(ctx.channel.id)
        data = await self.ticket_config.guild(ctx.guild).open_tickets()
        if ch_id not in data:
            return False
        await ctx.channel.set_permissions(user, view_channel=True, send_messages=True, attach_files=True)
        async with self.ticket_config.guild(ctx.guild).open_tickets() as tickets:
            if ch_id in tickets:
                tickets[ch_id].setdefault("participants", []).append(user.id)
        await ctx.channel.send(embed=discord.Embed(description=f"➕ {user.mention} added to this ticket.", colour=Clr.SUCCESS))
        return True

    async def _remove_user_from_ticket(self, ctx, user: discord.Member):
        """Remove a user from the current ticket channel."""
        ch_id = str(ctx.channel.id)
        data = await self.ticket_config.guild(ctx.guild).open_tickets()
        if ch_id not in data:
            return False
        await ctx.channel.set_permissions(user, overwrite=None)
        async with self.ticket_config.guild(ctx.guild).open_tickets() as tickets:
            if ch_id in tickets:
                p = tickets[ch_id].get("participants", [])
                if user.id in p:
                    p.remove(user.id)
        await ctx.channel.send(embed=discord.Embed(description=f"➖ {user.mention} removed from this ticket.", colour=Clr.ERROR))
        return True

    async def _rename_ticket(self, ctx, new_name: str):
        """Rename the current ticket channel."""
        ch_id = str(ctx.channel.id)
        data = await self.ticket_config.guild(ctx.guild).open_tickets()
        if ch_id not in data:
            return False
        if not data[ch_id].get("closed") and await self.ticket_config.guild(ctx.guild).allow_rename():
            await ctx.channel.edit(name=new_name)
            return True
        return False

    def _get_ticket_stats(self, closed_tickets: dict) -> dict:
        """Compute aggregate ticket stats."""
        total = len(closed_tickets)
        if not total:
            return {"total": 0}
        categories = {}
        total_response = 0
        response_count = 0
        for t in closed_tickets.values():
            cat = t.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1
            frt = t.get("first_response_at")
            opened = t.get("opened_at", 0)
            if frt and opened:
                total_response += frt - opened
                response_count += 1
        avg_response = total_response // max(response_count, 1)
        return {
            "total": total,
            "categories": categories,
            "avg_first_response": duration_str(avg_response) if avg_response else "N/A",
        }
