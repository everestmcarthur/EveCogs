"""NexusCore — Suggestion system with voting, statuses, threads, anonymous mode."""

from __future__ import annotations

import datetime
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    safe_send, safe_dm, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
SUGGEST_DEFAULTS_GUILD = {
    "enabled": False,
    "channel": None,
    "log_channel": None,
    "approved_channel": None,
    "denied_channel": None,
    "implemented_channel": None,
    "counter": 0,
    "suggestions": {},
    # id -> {user_id, content, status, upvotes, downvotes, submitted_at,
    #        message_id, staff_response, anonymous, image_url, category, thread_id}
    "categories": [],
    "anonymous_allowed": True,
    "auto_thread": True,
    "auto_upvote": True,
    "auto_downvote": True,
    "upvote_emoji": "👍",
    "downvote_emoji": "👎",
    "dm_on_status": True,
    "cooldown": 60,
    "min_length": 10,
    "max_length": 2000,
    "blacklisted": [],
    "require_category": False,
    "allow_images": True,
    "voting_buttons": True,
    "staff_roles": [],
}

STATUS_MAP = {
    "pending": ("⏳", "Pending", Clr.SUGGEST),
    "approved": ("✅", "Approved", Clr.SUCCESS),
    "denied": ("❌", "Denied", Clr.ERROR),
    "considered": ("🤔", "Under Consideration", Clr.INFO),
    "implemented": ("🚀", "Implemented", discord.Colour(0x9B59B6)),
    "in_progress": ("🔨", "In Progress", discord.Colour(0xE67E22)),
    "duplicate": ("♻️", "Duplicate", discord.Colour(0x95A5A6)),
    "invalid": ("🚫", "Invalid", discord.Colour(0x7F8C8D)),
}


# ── Views ──────────────────────────────────────────────────────────────────
class SuggestionVoteView(discord.ui.View):
    def __init__(self, cog: "SuggestionsMixin", suggestion_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.suggestion_id = suggestion_id

    @discord.ui.button(label="0", style=discord.ButtonStyle.success, emoji="👍", custom_id="nexus_suggest_up")
    async def upvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._handle_vote(interaction, self.suggestion_id, "up")

    @discord.ui.button(label="0", style=discord.ButtonStyle.danger, emoji="👎", custom_id="nexus_suggest_down")
    async def downvote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._handle_vote(interaction, self.suggestion_id, "down")


class SuggestModal(discord.ui.Modal):
    def __init__(self, cog, category: str | None = None, anonymous: bool = False):
        super().__init__(title="Submit a Suggestion")
        self.cog = cog
        self.category = category
        self.anonymous = anonymous
        self.suggestion_input = discord.ui.TextInput(
            label="Your Suggestion",
            style=discord.TextStyle.paragraph,
            placeholder="Describe your idea in detail...",
            min_length=10,
            max_length=2000,
            required=True,
        )
        self.image_input = discord.ui.TextInput(
            label="Image URL (optional)",
            style=discord.TextStyle.short,
            placeholder="https://...",
            required=False,
            max_length=500,
        )
        self.add_item(self.suggestion_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog._create_suggestion(
            interaction,
            self.suggestion_input.value,
            category=self.category,
            anonymous=self.anonymous,
            image_url=self.image_input.value or None,
        )
        await interaction.followup.send("✅ Suggestion submitted!", ephemeral=True)


class SuggestPanelView(discord.ui.View):
    def __init__(self, cog: "SuggestionsMixin"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="💡 Suggest", style=discord.ButtonStyle.primary, custom_id="nexus_suggest_panel")
    async def suggest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.cog.suggest_config.guild(interaction.guild).all()
        if not data["enabled"]:
            return await interaction.response.send_message("Suggestions are disabled.", ephemeral=True)

        if str(interaction.user.id) in [str(x) for x in data["blacklisted"]]:
            return await interaction.response.send_message("You are blacklisted from suggestions.", ephemeral=True)

        cats = data["categories"]
        if cats and data["require_category"]:
            view = SuggestCategoryView(self.cog, cats)
            return await interaction.response.send_message("Choose a category:", view=view, ephemeral=True)

        modal = SuggestModal(self.cog)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🕵️ Anonymous", style=discord.ButtonStyle.secondary, custom_id="nexus_suggest_anon")
    async def anon_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.cog.suggest_config.guild(interaction.guild).all()
        if not data["anonymous_allowed"]:
            return await interaction.response.send_message("Anonymous suggestions are disabled.", ephemeral=True)
        modal = SuggestModal(self.cog, anonymous=True)
        await interaction.response.send_modal(modal)


class SuggestCategoryView(discord.ui.View):
    def __init__(self, cog, categories: list[str]):
        super().__init__(timeout=60)
        self.cog = cog
        options = [discord.SelectOption(label=c.title(), value=c) for c in categories[:25]]
        self.sel = discord.ui.Select(placeholder="Category...", options=options)
        self.sel.callback = self.on_select
        self.add_item(self.sel)

    async def on_select(self, interaction: discord.Interaction):
        modal = SuggestModal(self.cog, category=self.sel.values[0])
        await interaction.response.send_modal(modal)


class StatusSelectView(discord.ui.View):
    def __init__(self, cog, suggestion_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        options = [
            discord.SelectOption(label=v[1], value=k, emoji=v[0])
            for k, v in STATUS_MAP.items()
        ]
        self.sel = discord.ui.Select(placeholder="Set status...", options=options)
        self.sel.callback = self.on_select
        self.add_item(self.sel)
        self.suggestion_id = suggestion_id

    async def on_select(self, interaction: discord.Interaction):
        await self.cog._set_status(interaction, self.suggestion_id, self.sel.values[0])


# ── Mixin ──────────────────────────────────────────────────────────────────
class SuggestionsMixin:
    """Suggestion system mixin."""

    def _init_suggestions(self, bot):
        self.suggest_config = Config.get_conf(
            None, identifier=900003, cog_name="NexusCoreSuggestions"
        )
        self.suggest_config.register_guild(**SUGGEST_DEFAULTS_GUILD)

        self._suggest_panel_view = SuggestPanelView(self)
        bot.add_view(self._suggest_panel_view)

    async def _create_suggestion(
        self, interaction: discord.Interaction, content: str, *,
        category: str | None = None, anonymous: bool = False, image_url: str | None = None,
    ):
        guild = interaction.guild
        conf = self.suggest_config.guild(guild)
        data = await conf.all()

        counter = data["counter"] + 1
        await conf.counter.set(counter)

        channel = guild.get_channel(data["channel"])
        if not channel:
            return

        s_id = str(counter)
        emoji, label, colour = STATUS_MAP["pending"]

        embed = discord.Embed(
            title=f"Suggestion #{counter}",
            description=content,
            colour=colour,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        if anonymous:
            embed.set_author(name="Anonymous")
        else:
            embed.set_author(
                name=str(interaction.user),
                icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            )

        if category:
            embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Status", value=f"{emoji} {label}", inline=True)
        embed.add_field(name="Votes", value="👍 0 | 👎 0", inline=True)

        if image_url:
            embed.set_image(url=image_url)

        embed.set_footer(text=f"ID: {s_id}")

        if data["voting_buttons"]:
            view = SuggestionVoteView(self, s_id)
            msg = await channel.send(embed=embed, view=view)
        else:
            msg = await channel.send(embed=embed)
            if data["auto_upvote"]:
                await msg.add_reaction(data["upvote_emoji"])
            if data["auto_downvote"]:
                await msg.add_reaction(data["downvote_emoji"])

        thread_id = None
        if data["auto_thread"]:
            try:
                thread = await msg.create_thread(name=f"Discussion — Suggestion #{counter}")
                thread_id = thread.id
            except discord.HTTPException:
                pass

        suggestion = {
            "user_id": interaction.user.id,
            "content": content,
            "status": "pending",
            "upvotes": [],
            "downvotes": [],
            "submitted_at": ts_now(),
            "message_id": msg.id,
            "staff_response": None,
            "anonymous": anonymous,
            "image_url": image_url,
            "category": category,
            "thread_id": thread_id,
        }
        async with conf.suggestions() as subs:
            subs[s_id] = suggestion

    async def _handle_vote(self, interaction: discord.Interaction, suggestion_id: str, direction: str):
        conf = self.suggest_config.guild(interaction.guild)
        async with conf.suggestions() as subs:
            s = subs.get(suggestion_id)
            if not s:
                return await interaction.response.send_message("Suggestion not found.", ephemeral=True)

            uid = interaction.user.id
            ups = s.get("upvotes", [])
            downs = s.get("downvotes", [])

            if direction == "up":
                if uid in ups:
                    ups.remove(uid)
                else:
                    ups.append(uid)
                    if uid in downs:
                        downs.remove(uid)
            else:
                if uid in downs:
                    downs.remove(uid)
                else:
                    downs.append(uid)
                    if uid in ups:
                        ups.remove(uid)

            s["upvotes"] = ups
            s["downvotes"] = downs
            subs[suggestion_id] = s

        await interaction.response.send_message(
            f"Vote recorded! 👍 {len(ups)} | 👎 {len(downs)}", ephemeral=True
        )

        # Update the embed
        data = await conf.all()
        channel = interaction.guild.get_channel(data["channel"])
        if channel and s.get("message_id"):
            try:
                msg = await channel.fetch_message(s["message_id"])
                if msg.embeds:
                    embed = msg.embeds[0]
                    for i, field in enumerate(embed.fields):
                        if field.name == "Votes":
                            embed.set_field_at(i, name="Votes", value=f"👍 {len(ups)} | 👎 {len(downs)}", inline=True)
                    await msg.edit(embed=embed)
            except discord.HTTPException:
                pass

    async def _set_status(self, interaction: discord.Interaction, suggestion_id: str, status: str):
        guild = interaction.guild
        conf = self.suggest_config.guild(guild)
        data = await conf.all()

        s = data["suggestions"].get(suggestion_id)
        if not s:
            return await interaction.response.send_message("Not found.", ephemeral=True)

        async with conf.suggestions() as subs:
            if suggestion_id in subs:
                subs[suggestion_id]["status"] = status

        emoji, label, colour = STATUS_MAP.get(status, ("❓", status, Clr.INFO))

        channel = guild.get_channel(data["channel"])
        if channel and s.get("message_id"):
            try:
                msg = await channel.fetch_message(s["message_id"])
                if msg.embeds:
                    embed = msg.embeds[0]
                    embed.colour = colour
                    for i, field in enumerate(embed.fields):
                        if field.name == "Status":
                            embed.set_field_at(i, name="Status", value=f"{emoji} {label}", inline=True)
                    await msg.edit(embed=embed)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            embed=ok_embed(f"Suggestion #{suggestion_id} → **{emoji} {label}**")
        )

        # Move to status-specific channel if set
        move_map = {
            "approved": data.get("approved_channel"),
            "denied": data.get("denied_channel"),
            "implemented": data.get("implemented_channel"),
        }
        move_ch_id = move_map.get(status)
        if move_ch_id:
            move_ch = guild.get_channel(move_ch_id)
            if move_ch and channel and s.get("message_id"):
                try:
                    old_msg = await channel.fetch_message(s["message_id"])
                    new_embed = old_msg.embeds[0] if old_msg.embeds else discord.Embed(description=s["content"])
                    new_msg = await move_ch.send(embed=new_embed)
                    async with conf.suggestions() as subs:
                        if suggestion_id in subs:
                            subs[suggestion_id]["message_id"] = new_msg.id
                except discord.HTTPException:
                    pass

        # DM user
        if data["dm_on_status"] and not s.get("anonymous"):
            user = guild.get_member(s["user_id"])
            if user:
                await safe_dm(user, embed=discord.Embed(
                    description=f"Your suggestion **#{suggestion_id}** in **{guild.name}** has been updated to: {emoji} **{label}**",
                    colour=colour,
                ))
