"""NexusCore — Embed Builder: webhook-based embed creation, templates, scheduling, JSON import/export."""

from __future__ import annotations

import asyncio
import datetime
import json
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    parse_duration, duration_str, safe_send, Paginator, chunk_list,
)

# ── Defaults ───────────────────────────────────────────────────────────────
EMBED_DEFAULTS_GUILD = {
    "webhooks": {},         # channel_id -> {webhook_id, webhook_url, name, avatar}
    "templates": {},        # name -> {embeds: [...], content, webhook_name, saved_by, saved_at}
    "scheduled": {},        # id -> {channel_id, embeds, content, send_at, interval, webhook_name, active}
    "history": [],          # last 100 sent embeds [{channel_id, embeds, sent_at, sent_by}]
}


# ── Variables ──────────────────────────────────────────────────────────────
VARIABLES = {
    "{server}": "Server name",
    "{server_name}": "Server name",
    "{server_icon}": "Server icon URL",
    "{member_count}": "Total members",
    "{channel_count}": "Total channels",
    "{role_count}": "Total roles",
    "{boost_count}": "Boost count",
    "{boost_level}": "Boost tier",
    "{date}": "Current date (YYYY-MM-DD)",
    "{time}": "Current time (HH:MM UTC)",
    "{datetime}": "Full datetime",
    "{nl}": "New line",
    "{user}": "Command user's mention",
    "{user_name}": "Command user's name",
    "{user_avatar}": "Command user's avatar URL",
    "{user_id}": "Command user's ID",
}


def replace_variables(text: str, guild: discord.Guild = None, user: discord.Member = None) -> str:
    """Replace all placeholders in text."""
    if not text:
        return text
    now = datetime.datetime.now(datetime.timezone.utc)
    replacements = {
        "{server}": guild.name if guild else "Server",
        "{server_name}": guild.name if guild else "Server",
        "{server_icon}": str(guild.icon.url) if guild and guild.icon else "",
        "{member_count}": str(guild.member_count) if guild else "0",
        "{channel_count}": str(len(guild.channels)) if guild else "0",
        "{role_count}": str(len(guild.roles)) if guild else "0",
        "{boost_count}": str(guild.premium_subscription_count or 0) if guild else "0",
        "{boost_level}": str(guild.premium_tier) if guild else "0",
        "{date}": now.strftime("%Y-%m-%d"),
        "{time}": now.strftime("%H:%M UTC"),
        "{datetime}": now.strftime("%Y-%m-%d %H:%M UTC"),
        "{nl}": "\n",
        "{user}": user.mention if user else "",
        "{user_name}": str(user) if user else "",
        "{user_avatar}": str(user.display_avatar.url) if user and user.display_avatar else "",
        "{user_id}": str(user.id) if user else "",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def embed_from_dict(data: dict, guild=None, user=None) -> discord.Embed:
    """Build a discord.Embed from a dict with variable replacement."""
    embed = discord.Embed()
    if data.get("title"):
        embed.title = replace_variables(data["title"], guild, user)[:256]
    if data.get("description"):
        embed.description = replace_variables(data["description"], guild, user)[:4096]
    if data.get("url"):
        embed.url = data["url"]
    if data.get("color") or data.get("colour"):
        c = data.get("color") or data.get("colour")
        if isinstance(c, str):
            c = int(c.lstrip("#"), 16)
        embed.colour = discord.Colour(c)
    if data.get("timestamp"):
        if data["timestamp"] is True:
            embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        else:
            try:
                embed.timestamp = datetime.datetime.fromisoformat(data["timestamp"])
            except (ValueError, TypeError):
                embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    if data.get("author"):
        a = data["author"]
        embed.set_author(
            name=replace_variables(a.get("name", ""), guild, user)[:256],
            url=a.get("url") or None,
            icon_url=a.get("icon_url") or None,
        )
    if data.get("footer"):
        f = data["footer"]
        embed.set_footer(
            text=replace_variables(f.get("text", ""), guild, user)[:2048],
            icon_url=f.get("icon_url") or None,
        )
    if data.get("image"):
        embed.set_image(url=data["image"])
    if data.get("thumbnail"):
        embed.set_thumbnail(url=data["thumbnail"])
    for field in data.get("fields", [])[:25]:
        embed.add_field(
            name=replace_variables(field.get("name", "\u200b"), guild, user)[:256],
            value=replace_variables(field.get("value", "\u200b"), guild, user)[:1024],
            inline=field.get("inline", True),
        )
    return embed


def embed_to_dict(embed: discord.Embed) -> dict:
    """Convert a discord.Embed to a JSON-serializable dict (Discohook compatible)."""
    data = {}
    if embed.title:
        data["title"] = embed.title
    if embed.description:
        data["description"] = embed.description
    if embed.url:
        data["url"] = embed.url
    if embed.colour:
        data["color"] = embed.colour.value
    if embed.timestamp:
        data["timestamp"] = embed.timestamp.isoformat()
    if embed.author:
        data["author"] = {}
        if embed.author.name:
            data["author"]["name"] = embed.author.name
        if embed.author.url:
            data["author"]["url"] = embed.author.url
        if embed.author.icon_url:
            data["author"]["icon_url"] = embed.author.icon_url
    if embed.footer:
        data["footer"] = {}
        if embed.footer.text:
            data["footer"]["text"] = embed.footer.text
        if embed.footer.icon_url:
            data["footer"]["icon_url"] = embed.footer.icon_url
    if embed.image:
        data["image"] = embed.image.url
    if embed.thumbnail:
        data["thumbnail"] = embed.thumbnail.url
    if embed.fields:
        data["fields"] = [
            {"name": f.name, "value": f.value, "inline": f.inline}
            for f in embed.fields
        ]
    return data


# ── Modals ─────────────────────────────────────────────────────────────────

class EmbedTitleModal(discord.ui.Modal, title="Embed — Title & Description"):
    embed_title = discord.ui.TextInput(
        label="Title", max_length=256, required=False,
        placeholder="My awesome embed",
    )
    description = discord.ui.TextInput(
        label="Description", style=discord.TextStyle.paragraph,
        max_length=4000, required=False,
        placeholder="Supports **markdown** and {variables}",
    )
    url = discord.ui.TextInput(
        label="Title URL", max_length=500, required=False,
        placeholder="https://example.com",
    )
    colour = discord.ui.TextInput(
        label="Colour (hex)", max_length=7, required=False,
        placeholder="#5865F2",
    )

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, {
            "title": self.embed_title.value,
            "description": self.description.value,
            "url": self.url.value,
            "colour": self.colour.value,
        })


class EmbedAuthorFooterModal(discord.ui.Modal, title="Embed — Author & Footer"):
    author_name = discord.ui.TextInput(label="Author Name", max_length=256, required=False)
    author_icon = discord.ui.TextInput(label="Author Icon URL", max_length=500, required=False)
    author_url = discord.ui.TextInput(label="Author URL", max_length=500, required=False)
    footer_text = discord.ui.TextInput(label="Footer Text", max_length=2048, required=False)
    footer_icon = discord.ui.TextInput(label="Footer Icon URL", max_length=500, required=False)

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, {
            "author": {"name": self.author_name.value, "icon_url": self.author_icon.value, "url": self.author_url.value},
            "footer": {"text": self.footer_text.value, "icon_url": self.footer_icon.value},
        })


class EmbedImagesModal(discord.ui.Modal, title="Embed — Images"):
    image = discord.ui.TextInput(label="Image URL", max_length=500, required=False, placeholder="https://i.imgur.com/...")
    thumbnail = discord.ui.TextInput(label="Thumbnail URL", max_length=500, required=False)

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, {
            "image": self.image.value,
            "thumbnail": self.thumbnail.value,
        })


class EmbedFieldModal(discord.ui.Modal, title="Add Field"):
    field_name = discord.ui.TextInput(label="Field Name", max_length=256)
    field_value = discord.ui.TextInput(label="Field Value", style=discord.TextStyle.paragraph, max_length=1024)
    inline = discord.ui.TextInput(label="Inline? (yes/no)", max_length=3, required=False, default="yes")

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, {
            "name": self.field_name.value,
            "value": self.field_value.value,
            "inline": self.inline.value.lower() in ("yes", "y", "true", "1"),
        })


class EmbedWebhookModal(discord.ui.Modal, title="Webhook Settings"):
    wh_name = discord.ui.TextInput(label="Webhook Name", max_length=80, default="NexusCore")
    wh_avatar = discord.ui.TextInput(label="Avatar URL", max_length=500, required=False)
    content = discord.ui.TextInput(label="Message Content (outside embed)", style=discord.TextStyle.paragraph, max_length=2000, required=False)

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, {
            "webhook_name": self.wh_name.value,
            "webhook_avatar": self.wh_avatar.value,
            "content": self.content.value,
        })


# ── Builder View ───────────────────────────────────────────────────────────

class EmbedBuilderView(discord.ui.View):
    """Interactive embed builder with buttons for each section."""

    def __init__(self, cog, author: discord.Member, channel: discord.TextChannel = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.author = author
        self.target_channel = channel
        self.embed_data = {}
        self.fields = []
        self.webhook_name = "NexusCore"
        self.webhook_avatar = ""
        self.content = ""

    def _build_preview(self) -> discord.Embed:
        data = dict(self.embed_data)
        data["fields"] = self.fields
        if data or self.fields:
            embed = embed_from_dict(data, self.author.guild, self.author)
            if not embed.title and not embed.description and not embed.fields:
                embed.description = "*Empty embed — use the buttons below to add content*"
            return embed
        return discord.Embed(description="*Empty embed — use the buttons below to add content*", colour=Clr.INFO)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Not your builder.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Title & Desc", style=discord.ButtonStyle.primary, emoji="📝", row=0)
    async def title_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async def cb(inter, data):
            if data.get("title"):
                self.embed_data["title"] = data["title"]
            if data.get("description"):
                self.embed_data["description"] = data["description"]
            if data.get("url"):
                self.embed_data["url"] = data["url"]
            if data.get("colour"):
                try:
                    self.embed_data["colour"] = data["colour"]
                except ValueError:
                    pass
            await inter.response.edit_message(embed=self._build_preview(), view=self)
        await interaction.response.send_modal(EmbedTitleModal(cb))

    @discord.ui.button(label="Author & Footer", style=discord.ButtonStyle.primary, emoji="👤", row=0)
    async def author_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async def cb(inter, data):
            if data.get("author") and any(data["author"].values()):
                self.embed_data["author"] = data["author"]
            if data.get("footer") and any(data["footer"].values()):
                self.embed_data["footer"] = data["footer"]
            await inter.response.edit_message(embed=self._build_preview(), view=self)
        await interaction.response.send_modal(EmbedAuthorFooterModal(cb))

    @discord.ui.button(label="Images", style=discord.ButtonStyle.primary, emoji="🖼️", row=0)
    async def images_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async def cb(inter, data):
            if data.get("image"):
                self.embed_data["image"] = data["image"]
            if data.get("thumbnail"):
                self.embed_data["thumbnail"] = data["thumbnail"]
            await inter.response.edit_message(embed=self._build_preview(), view=self)
        await interaction.response.send_modal(EmbedImagesModal(cb))

    @discord.ui.button(label="Add Field", style=discord.ButtonStyle.secondary, emoji="➕", row=0)
    async def field_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.fields) >= 25:
            return await interaction.response.send_message("Max 25 fields.", ephemeral=True)

        async def cb(inter, data):
            self.fields.append(data)
            await inter.response.edit_message(embed=self._build_preview(), view=self)
        await interaction.response.send_modal(EmbedFieldModal(cb))

    @discord.ui.button(label="Timestamp", style=discord.ButtonStyle.secondary, emoji="🕐", row=1)
    async def timestamp_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.embed_data["timestamp"] = True
        await interaction.response.edit_message(embed=self._build_preview(), view=self)

    @discord.ui.button(label="Webhook Settings", style=discord.ButtonStyle.secondary, emoji="🔗", row=1)
    async def webhook_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async def cb(inter, data):
            if data.get("webhook_name"):
                self.webhook_name = data["webhook_name"]
            if data.get("webhook_avatar"):
                self.webhook_avatar = data["webhook_avatar"]
            if data.get("content"):
                self.content = data["content"]
            await inter.response.send_message(
                f"✅ Webhook: **{self.webhook_name}**" + (f"\nContent: {self.content[:100]}" if self.content else ""),
                ephemeral=True,
            )
        await interaction.response.send_modal(EmbedWebhookModal(cb))

    @discord.ui.button(label="Clear Fields", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def clear_fields_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.fields.clear()
        await interaction.response.edit_message(embed=self._build_preview(), view=self)

    @discord.ui.button(label="Reset All", style=discord.ButtonStyle.danger, emoji="♻️", row=1)
    async def reset_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.embed_data.clear()
        self.fields.clear()
        self.content = ""
        await interaction.response.edit_message(embed=self._build_preview(), view=self)

    @discord.ui.button(label="📤 Send", style=discord.ButtonStyle.success, emoji=None, row=2)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.target_channel:
            return await interaction.response.send_message("No target channel set. Use `[p]embed send #channel`", ephemeral=True)

        data = dict(self.embed_data)
        data["fields"] = self.fields
        embed = embed_from_dict(data, interaction.guild, interaction.user)

        webhook = None
        for wh in await self.target_channel.webhooks():
            if wh.name == self.webhook_name:
                webhook = wh
                break
        if not webhook:
            webhook = await self.target_channel.create_webhook(name=self.webhook_name)

        await webhook.send(
            content=self.content or None,
            embed=embed,
            username=self.webhook_name,
            avatar_url=self.webhook_avatar or None,
        )
        await interaction.response.send_message(f"✅ Embed sent to {self.target_channel.mention}!", ephemeral=True)

        # Log to history
        async with self.cog.embed_config.guild(interaction.guild).history() as hist:
            hist.append({
                "channel_id": self.target_channel.id,
                "embed": data,
                "content": self.content,
                "sent_at": ts_now(),
                "sent_by": interaction.user.id,
            })
            if len(hist) > 100:
                hist.pop(0)

    @discord.ui.button(label="💾 Export JSON", style=discord.ButtonStyle.secondary, emoji=None, row=2)
    async def export_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        import io
        data = dict(self.embed_data)
        data["fields"] = self.fields
        # Discohook-compatible format
        export = {
            "content": self.content,
            "embeds": [data],
        }
        raw = json.dumps(export, indent=2)
        file = discord.File(io.BytesIO(raw.encode()), filename="embed.json")
        await interaction.response.send_message("📋 JSON export (Discohook compatible):", file=file, ephemeral=True)

    @discord.ui.button(label="💾 Save Template", style=discord.ButtonStyle.secondary, emoji=None, row=2)
    async def save_template_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        class NameModal(discord.ui.Modal, title="Save Template"):
            tname = discord.ui.TextInput(label="Template Name", max_length=50)

            async def on_submit(modal_self, inter: discord.Interaction):
                data = dict(self.embed_data)
                data["fields"] = self.fields
                async with self.cog.embed_config.guild(inter.guild).templates() as templates:
                    templates[modal_self.tname.value] = {
                        "embeds": [data],
                        "content": self.content,
                        "webhook_name": self.webhook_name,
                        "saved_by": inter.user.id,
                        "saved_at": ts_now(),
                    }
                await inter.response.send_message(f"✅ Template **{modal_self.tname.value}** saved!", ephemeral=True)

        await interaction.response.send_modal(NameModal())


# ── Mixin ──────────────────────────────────────────────────────────────────
class EmbedBuilderMixin:
    """Embed builder system mixin."""

    def _init_embed_builder(self, bot):
        self.embed_config = Config.get_conf(
            None, identifier=900009, cog_name="NexusCoreEmbed"
        )
        self.embed_config.register_guild(**EMBED_DEFAULTS_GUILD)
        self._scheduled_embed_tasks = {}

    async def _load_scheduled_embeds(self):
        """Load and schedule pending embed sends."""
        for guild in self.bot.guilds:
            scheduled = await self.embed_config.guild(guild).scheduled()
            for sid, sched in scheduled.items():
                if sched.get("active"):
                    self._schedule_embed_send(guild, sid, sched)

    def _schedule_embed_send(self, guild, sched_id, sched_data):
        async def _task():
            try:
                send_at = sched_data.get("send_at", 0)
                now = ts_now()
                if send_at > now:
                    await asyncio.sleep(send_at - now)

                channel = guild.get_channel(sched_data.get("channel_id"))
                if not channel:
                    return

                embeds = [embed_from_dict(e, guild) for e in sched_data.get("embeds", [])[:10]]
                content = sched_data.get("content")
                wh_name = sched_data.get("webhook_name", "NexusCore")

                webhook = None
                for wh in await channel.webhooks():
                    if wh.name == wh_name:
                        webhook = wh
                        break
                if not webhook:
                    webhook = await channel.create_webhook(name=wh_name)

                await webhook.send(content=content or None, embeds=embeds or None, username=wh_name)

                interval = sched_data.get("interval", 0)
                if interval > 0:
                    # Recurring — reschedule
                    async with self.embed_config.guild(guild).scheduled() as scheds:
                        if sched_id in scheds:
                            scheds[sched_id]["send_at"] = ts_now() + interval
                    self._schedule_embed_send(guild, sched_id, {**sched_data, "send_at": ts_now() + interval})
                else:
                    async with self.embed_config.guild(guild).scheduled() as scheds:
                        if sched_id in scheds:
                            scheds[sched_id]["active"] = False
            except Exception:
                pass

        task = asyncio.create_task(_task())
        self._scheduled_embed_tasks[sched_id] = task
