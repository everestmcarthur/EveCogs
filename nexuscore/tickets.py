"""NexusCore — Ticket system with panels, categories, transcripts, claims, priorities, feedback."""

from __future__ import annotations

import asyncio
import datetime
import io
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    ts_full, duration_str, safe_send, safe_dm, ConfirmView, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
TICKET_DEFAULTS_GUILD = {
    "enabled": False,
    "category_id": None,
    "log_channel": None,
    "transcript_channel": None,
    "counter": 0,
    "panels": {},        # msg_id -> {channel_id, title, description, colour, categories}
    "categories": {},    # name -> {description, emoji, roles, questions, greeting, priority, channel_name_fmt}
    "open_tickets": {},  # channel_id -> {user_id, category, opened_at, claimed_by, priority, closed}
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
    "transcript_format": "html",
}

TICKET_DEFAULTS_MEMBER = {
    "tickets_opened": 0,
    "feedback_given": [],
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
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ticket Transcript</title>
<style>
body {{ background: #36393f; color: #dcddde; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
.header {{ background: #2f3136; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
.header h1 {{ color: #fff; margin: 0; font-size: 1.4em; }}
.header p {{ color: #72767d; margin: 4px 0 0; }}
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
<p>Category: {ticket_info.get("category", "General")} · Opened by: {ticket_info.get("user_name", "Unknown")} · {ticket_info.get("opened_at_str", "")}</p>
</div>
{msgs_html}
</body></html>"""


# ── Views ──────────────────────────────────────────────────────────────────
class TicketPanelView(discord.ui.View):
    """Persistent panel with a select menu for category or a single create button."""

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
                label=name.title(),
                value=name,
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
                required=True,
                max_length=1024,
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
    """Controls inside a ticket channel: close, claim, priority."""

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
        await interaction.response.send_message(
            f"{prio_emoji.get(prio, '⚡')} Priority set to **{prio.title()}**", ephemeral=False
        )
        self.stop()


class FeedbackModal(discord.ui.Modal):
    def __init__(self, cog, channel_id: str):
        super().__init__(title="Ticket Feedback")
        self.cog = cog
        self.channel_id = channel_id
        self.rating = discord.ui.TextInput(
            label="Rating (1-5 stars)", placeholder="5", max_length=1, required=True
        )
        self.comments = discord.ui.TextInput(
            label="Comments (optional)", style=discord.TextStyle.paragraph, required=False, max_length=500
        )
        self.add_item(self.rating)
        self.add_item(self.comments)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            r = int(self.rating.value)
            r = max(1, min(5, r))
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


# ── Mixin ──────────────────────────────────────────────────────────────────
class TicketsMixin:
    """Ticket system mixin — mixed into the main NexusCore cog."""

    def _init_tickets(self, bot):
        self.ticket_config = Config.get_conf(
            None, identifier=900001, cog_name="NexusCoreTickets"
        )
        self.ticket_config.register_guild(**TICKET_DEFAULTS_GUILD)
        self.ticket_config.register_member(**TICKET_DEFAULTS_MEMBER)

        self._ticket_panel_view = TicketPanelView(self)
        self._ticket_control_view = TicketControlView(self)
        bot.add_view(self._ticket_panel_view)
        bot.add_view(self._ticket_control_view)

    # ── Internal helpers ───────────────────────────────────────────────────
    async def _create_ticket_channel(
        self, interaction: discord.Interaction, category_name: str | None, answers: dict
    ) -> discord.TextChannel | None:
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
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True, embed_links=True
            ),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        for role_id in cat_data.get("roles", []):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        disc_cat = guild.get_channel(data["category_id"]) if data["category_id"] else None

        try:
            channel = await guild.create_text_channel(
                ch_name,
                category=disc_cat,
                overwrites=overwrites,
                topic=f"Ticket #{counter} · {interaction.user} · {category_name or 'General'}",
            )
        except discord.HTTPException:
            return None

        ticket_info = {
            "user_id": interaction.user.id,
            "user_name": str(interaction.user),
            "category": category_name or "general",
            "opened_at": ts_now(),
            "opened_at_str": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "number": counter,
            "claimed_by": None,
            "priority": cat_data.get("default_priority", "medium"),
            "closed": False,
            "answers": answers,
        }
        async with conf.open_tickets() as tickets:
            tickets[str(channel.id)] = ticket_info

        greeting = cat_data.get("greeting") or f"Welcome, {interaction.user.mention}! A staff member will be with you shortly."
        prio_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "urgent": "🔴"}.get(ticket_info["priority"], "🟡")

        embed = discord.Embed(
            title=f"🎫 Ticket #{counter}",
            description=greeting,
            colour=Clr.TICKET,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
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

    async def _close_ticket(self, interaction: discord.Interaction):
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

        transcript_ch_id = data.get("transcript_channel")
        if transcript_ch_id:
            transcript_ch = guild.get_channel(transcript_ch_id)
            if transcript_ch:
                html = await build_transcript_html(interaction.channel, ticket)
                file = discord.File(
                    io.BytesIO(html.encode()),
                    filename=f"transcript-{ticket.get('number', 0)}.html"
                )
                te = discord.Embed(
                    title=f"📄 Transcript — Ticket #{ticket.get('number', 0)}",
                    colour=Clr.TICKET,
                )
                te.add_field(name="User", value=f"<@{ticket['user_id']}>", inline=True)
                te.add_field(name="Closed by", value=interaction.user.mention, inline=True)
                te.add_field(name="Category", value=ticket.get("category", "General"), inline=True)
                await safe_send(transcript_ch, embed=te, file=file)

        if data["dm_on_close"]:
            user = guild.get_member(ticket["user_id"]) or await guild.fetch_member(ticket["user_id"])
            if user:
                await safe_dm(user, embed=discord.Embed(
                    description=f"Your ticket **#{ticket.get('number', 0)}** in **{guild.name}** has been closed.",
                    colour=Clr.TICKET,
                ))

        if data["feedback_enabled"]:
            user = guild.get_member(ticket["user_id"])
            if user:
                modal = FeedbackModal(self, ch_id)
                try:
                    await user.send(
                        "Please rate your support experience!",
                        view=FeedbackButtonView(self, ch_id)
                    )
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

        await interaction.channel.send(embed=discord.Embed(
            description="🔒 This ticket has been closed. Deleting in 10 seconds...",
            colour=Clr.ERROR,
        ))
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason=f"Ticket #{ticket.get('number', 0)} closed")
        except discord.HTTPException:
            pass

    async def _claim_ticket(self, interaction: discord.Interaction):
        guild = interaction.guild
        ch_id = str(interaction.channel.id)
        data = await self.ticket_config.guild(guild).all()
        ticket = data["open_tickets"].get(ch_id)
        if not ticket:
            return await interaction.response.send_message("Not a ticket channel.", ephemeral=True)
        if not data["claim_enabled"]:
            return await interaction.response.send_message("Claim system is disabled.", ephemeral=True)
        if ticket.get("claimed_by"):
            return await interaction.response.send_message(
                f"Already claimed by <@{ticket['claimed_by']}>.", ephemeral=True
            )

        async with self.ticket_config.guild(guild).open_tickets() as tickets:
            if ch_id in tickets:
                tickets[ch_id]["claimed_by"] = interaction.user.id

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🙋 **{interaction.user.display_name}** claimed this ticket.",
                colour=Clr.SUCCESS,
            )
        )


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
