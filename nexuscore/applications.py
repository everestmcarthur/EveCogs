"""NexusCore — Application / forms system with modals, review, multi-type, auto-role."""

from __future__ import annotations

import datetime
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    safe_send, safe_dm, ConfirmView, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
APP_DEFAULTS_GUILD = {
    "enabled": False,
    "review_channel": None,
    "log_channel": None,
    "types": {},
    # type_name -> {
    #   description, emoji, questions: [{label, placeholder, style, required, max_length}],
    #   role_on_accept, role_on_deny, dm_on_accept, dm_on_deny,
    #   accept_msg, deny_msg, review_roles, cooldown, max_pending,
    #   auto_thread, require_account_age_days, require_server_days,
    #   enabled, panel_channel, panel_message
    # }
    "submissions": {},
    # sub_id -> {user_id, type, answers, status, submitted_at, reviewed_by, reviewed_at, review_msg_id, notes}
    "blacklisted": [],
    "global_cooldown": 86400,
    "dm_results": True,
    "anonymous_review": False,
}


# ── Views ──────────────────────────────────────────────────────────────────
class AppPanelView(discord.ui.View):
    """Persistent panel with a button per application type."""
    def __init__(self, cog: "ApplicationsMixin"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="📋 Apply", style=discord.ButtonStyle.success, custom_id="nexus_app_apply")
    async def apply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.cog.app_config.guild(interaction.guild).all()
        if not data["enabled"]:
            return await interaction.response.send_message("Applications are disabled.", ephemeral=True)

        types = {k: v for k, v in data["types"].items() if v.get("enabled", True)}
        if not types:
            return await interaction.response.send_message("No application types available.", ephemeral=True)

        if len(types) == 1:
            t_name = list(types.keys())[0]
            return await self.cog._start_application(interaction, t_name)

        view = AppTypeSelectView(self.cog, types)
        await interaction.response.send_message("Choose an application type:", view=view, ephemeral=True)


class AppTypeSelectView(discord.ui.View):
    def __init__(self, cog, types: dict):
        super().__init__(timeout=60)
        self.cog = cog
        options = []
        for name, td in list(types.items())[:25]:
            options.append(discord.SelectOption(
                label=name.title(),
                value=name,
                description=(td.get("description", "") or "")[:100],
                emoji=td.get("emoji") or "📋",
            ))
        self.sel = discord.ui.Select(placeholder="Select type...", options=options)
        self.sel.callback = self.on_select
        self.add_item(self.sel)

    async def on_select(self, interaction: discord.Interaction):
        await self.cog._start_application(interaction, self.sel.values[0])


class AppFormModal(discord.ui.Modal):
    """Modal with up to 5 questions."""
    def __init__(self, cog, app_type: str, questions: list[dict], page: int = 0):
        super().__init__(title=f"Application — {app_type.title()}"[:45])
        self.cog = cog
        self.app_type = app_type
        self.page = page
        self.inputs = []
        start = page * 5
        for q in questions[start:start + 5]:
            style = discord.TextStyle.paragraph if q.get("style") == "long" else discord.TextStyle.short
            inp = discord.ui.TextInput(
                label=q["label"][:45],
                placeholder=q.get("placeholder", "")[:100] or None,
                style=style,
                required=q.get("required", True),
                max_length=q.get("max_length", 1024),
            )
            self.inputs.append(inp)
            self.add_item(inp)
        self._questions = questions

    async def on_submit(self, interaction: discord.Interaction):
        answers = {}
        start = self.page * 5
        for i, inp in enumerate(self.inputs):
            answers[self._questions[start + i]["label"]] = inp.value

        cache_key = f"{interaction.user.id}_{self.app_type}"
        if not hasattr(self.cog, "_app_answer_cache"):
            self.cog._app_answer_cache = {}
        if cache_key not in self.cog._app_answer_cache:
            self.cog._app_answer_cache[cache_key] = {}
        self.cog._app_answer_cache[cache_key].update(answers)

        next_page = self.page + 1
        if next_page * 5 < len(self._questions):
            modal = AppFormModal(self.cog, self.app_type, self._questions, next_page)
            await interaction.response.send_modal(modal)
        else:
            all_answers = self.cog._app_answer_cache.pop(cache_key, answers)
            await interaction.response.defer(ephemeral=True)
            await self.cog._submit_application(interaction, self.app_type, all_answers)
            await interaction.followup.send("✅ Your application has been submitted!", ephemeral=True)


class ReviewView(discord.ui.View):
    """Accept / Deny / Interview buttons on a review embed."""
    def __init__(self, cog: "ApplicationsMixin", sub_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.sub_id = sub_id

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id="nexus_app_accept")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._review_application(interaction, self.sub_id, "accepted")

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌", custom_id="nexus_app_deny")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._review_application(interaction, self.sub_id, "denied")

    @discord.ui.button(label="Interview", style=discord.ButtonStyle.primary, emoji="🎙️", custom_id="nexus_app_interview")
    async def interview_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._review_application(interaction, self.sub_id, "interview")

    @discord.ui.button(label="Note", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="nexus_app_note")
    async def note_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AppNoteModal(self.cog, self.sub_id)
        await interaction.response.send_modal(modal)


class AppNoteModal(discord.ui.Modal):
    def __init__(self, cog, sub_id: str):
        super().__init__(title="Add Staff Note")
        self.cog = cog
        self.sub_id = sub_id
        self.note_input = discord.ui.TextInput(label="Note", style=discord.TextStyle.paragraph, max_length=500)
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        async with self.cog.app_config.guild(interaction.guild).submissions() as subs:
            if self.sub_id in subs:
                if "notes" not in subs[self.sub_id]:
                    subs[self.sub_id]["notes"] = []
                subs[self.sub_id]["notes"].append({
                    "author": interaction.user.id,
                    "text": self.note_input.value,
                    "at": ts_now(),
                })
        await interaction.response.send_message(f"📝 Note added.", ephemeral=True)


# ── Mixin ──────────────────────────────────────────────────────────────────
class ApplicationsMixin:
    """Application system mixin."""

    def _init_applications(self, bot):
        self.app_config = Config.get_conf(
            None, identifier=900002, cog_name="NexusCoreApps"
        )
        self.app_config.register_guild(**APP_DEFAULTS_GUILD)
        self._app_answer_cache = {}

        self._app_panel_view = AppPanelView(self)
        bot.add_view(self._app_panel_view)

    async def _start_application(self, interaction: discord.Interaction, type_name: str):
        guild = interaction.guild
        data = await self.app_config.guild(guild).all()

        if str(interaction.user.id) in [str(x) for x in data["blacklisted"]]:
            return await interaction.response.send_message("You are blacklisted from applications.", ephemeral=True)

        type_data = data["types"].get(type_name)
        if not type_data or not type_data.get("enabled", True):
            return await interaction.response.send_message("This application type is unavailable.", ephemeral=True)

        # Cooldown check
        cooldown = type_data.get("cooldown") or data["global_cooldown"]
        for sub in data["submissions"].values():
            if str(sub["user_id"]) == str(interaction.user.id) and sub["type"] == type_name:
                if sub["status"] == "pending":
                    return await interaction.response.send_message("You already have a pending application.", ephemeral=True)
                if ts_now() - sub.get("submitted_at", 0) < cooldown:
                    remaining = cooldown - (ts_now() - sub.get("submitted_at", 0))
                    return await interaction.response.send_message(
                        f"Cooldown active. Try again {ts_relative(ts_now() + remaining)}.", ephemeral=True
                    )

        # Account age check
        req_age = type_data.get("require_account_age_days", 0)
        if req_age:
            age = (datetime.datetime.now(datetime.timezone.utc) - interaction.user.created_at).days
            if age < req_age:
                return await interaction.response.send_message(
                    f"Your account must be at least {req_age} days old.", ephemeral=True
                )

        # Server membership check
        req_server = type_data.get("require_server_days", 0)
        if req_server and interaction.user.joined_at:
            days = (datetime.datetime.now(datetime.timezone.utc) - interaction.user.joined_at).days
            if days < req_server:
                return await interaction.response.send_message(
                    f"You must be in the server for at least {req_server} days.", ephemeral=True
                )

        questions = type_data.get("questions", [])
        if not questions:
            questions = [{"label": "Why are you applying?", "style": "long"}]

        modal = AppFormModal(self, type_name, questions, 0)
        await interaction.response.send_modal(modal)

    async def _submit_application(self, interaction: discord.Interaction, type_name: str, answers: dict):
        guild = interaction.guild
        data = await self.app_config.guild(guild).all()
        type_data = data["types"].get(type_name, {})

        sub_id = short_id(12)
        submission = {
            "user_id": interaction.user.id,
            "user_name": str(interaction.user),
            "type": type_name,
            "answers": answers,
            "status": "pending",
            "submitted_at": ts_now(),
            "reviewed_by": None,
            "reviewed_at": None,
            "review_msg_id": None,
            "notes": [],
        }

        async with self.app_config.guild(guild).submissions() as subs:
            subs[sub_id] = submission

        review_ch_id = type_data.get("review_channel") or data["review_channel"]
        if review_ch_id:
            review_ch = guild.get_channel(review_ch_id)
            if review_ch:
                embed = discord.Embed(
                    title=f"📋 New Application — {type_name.title()}",
                    colour=Clr.APP,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                embed.set_author(
                    name=str(interaction.user),
                    icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                )
                embed.add_field(name="User", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=True)
                embed.add_field(name="Type", value=type_name.title(), inline=True)
                embed.add_field(name="ID", value=f"`{sub_id}`", inline=True)

                for q, a in answers.items():
                    embed.add_field(name=q, value=a[:1024] or "*No answer*", inline=False)

                if interaction.user.joined_at:
                    embed.add_field(
                        name="Server Member Since",
                        value=ts_relative(int(interaction.user.joined_at.timestamp())),
                        inline=True,
                    )
                embed.add_field(
                    name="Account Created",
                    value=ts_relative(int(interaction.user.created_at.timestamp())),
                    inline=True,
                )
                embed.set_footer(text=f"Application ID: {sub_id}")

                view = ReviewView(self, sub_id)
                msg = await review_ch.send(embed=embed, view=view)

                async with self.app_config.guild(guild).submissions() as subs:
                    if sub_id in subs:
                        subs[sub_id]["review_msg_id"] = msg.id

                if type_data.get("auto_thread"):
                    try:
                        await msg.create_thread(name=f"Review — {interaction.user.name}")
                    except discord.HTTPException:
                        pass

        log_ch_id = data.get("log_channel")
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(title="📋 Application Submitted", colour=Clr.APP)
                le.add_field(name="User", value=interaction.user.mention, inline=True)
                le.add_field(name="Type", value=type_name.title(), inline=True)
                le.add_field(name="ID", value=sub_id, inline=True)
                await safe_send(log_ch, embed=le)

    async def _review_application(self, interaction: discord.Interaction, sub_id: str, status: str):
        guild = interaction.guild
        data = await self.app_config.guild(guild).all()
        sub = data["submissions"].get(sub_id)
        if not sub:
            return await interaction.response.send_message("Application not found.", ephemeral=True)
        if sub["status"] != "pending" and status != "interview":
            return await interaction.response.send_message(f"Already {sub['status']}.", ephemeral=True)

        async with self.app_config.guild(guild).submissions() as subs:
            if sub_id in subs:
                subs[sub_id]["status"] = status
                subs[sub_id]["reviewed_by"] = interaction.user.id
                subs[sub_id]["reviewed_at"] = ts_now()

        type_data = data["types"].get(sub["type"], {})

        status_emojis = {"accepted": "✅", "denied": "❌", "interview": "🎙️"}
        status_colours = {"accepted": Clr.SUCCESS, "denied": Clr.ERROR, "interview": Clr.INFO}

        embed = discord.Embed(
            title=f"{status_emojis.get(status, '❓')} Application {status.title()}",
            description=f"**Applicant:** <@{sub['user_id']}>\n**Type:** {sub['type'].title()}\n**Reviewed by:** {interaction.user.mention}",
            colour=status_colours.get(status, Clr.INFO),
        )
        await interaction.response.send_message(embed=embed)

        member = guild.get_member(sub["user_id"])
        if member:
            if status == "accepted" and type_data.get("role_on_accept"):
                role = guild.get_role(type_data["role_on_accept"])
                if role:
                    try:
                        await member.add_roles(role, reason=f"Application {sub_id} accepted")
                    except discord.HTTPException:
                        pass

            if status == "denied" and type_data.get("role_on_deny"):
                role = guild.get_role(type_data["role_on_deny"])
                if role:
                    try:
                        await member.add_roles(role, reason=f"Application {sub_id} denied")
                    except discord.HTTPException:
                        pass

            if data["dm_results"]:
                if status == "accepted":
                    msg_text = type_data.get("accept_msg") or f"Your **{sub['type'].title()}** application in **{guild.name}** has been **accepted**! 🎉"
                elif status == "denied":
                    msg_text = type_data.get("deny_msg") or f"Your **{sub['type'].title()}** application in **{guild.name}** has been **denied**."
                else:
                    msg_text = f"You've been selected for an **interview** regarding your **{sub['type'].title()}** application in **{guild.name}**!"

                await safe_dm(member, embed=discord.Embed(description=msg_text, colour=status_colours.get(status, Clr.INFO)))

        # Disable buttons on review message
        if sub.get("review_msg_id"):
            review_ch_id = type_data.get("review_channel") or data["review_channel"]
            if review_ch_id:
                review_ch = guild.get_channel(review_ch_id)
                if review_ch:
                    try:
                        review_msg = await review_ch.fetch_message(sub["review_msg_id"])
                        await review_msg.edit(view=None)
                    except discord.HTTPException:
                        pass
