"""Support — Modernized DM/contact system with categories, channels, and customization.

Overrides Red's built-in `contact` and `dm` commands with a more feature-rich system.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Optional, Literal

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify


# ── Config Defaults ──────────────────────────────────────────────────────────
DEFAULT_GUILD = {
    "enabled": False,
    "categories": {},  # category_name -> {channel_id, description, emoji, roles, greeting}
    "default_category": None,
    "log_channel": None,
    "mod_roles": [],
    "reply_with_embed": True,
    "show_author_info": True,
    "anonymous_mode": False,
    "thread_mode": False,
    "dm_on_reply": True,
    "active_threads": {},  # channel_id -> {user_id, category, started_at, message_count}
    "thread_timeout": 3600,  # Close thread after 1hr inactivity
    "custom_greeting": "",
    "require_category": False,
}

DEFAULT_USER = {
    "blocked": False,
    "preference_category": None,
    "last_contact": 0,
}


# ── Utilities ────────────────────────────────────────────────────────────────
def success_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=f"✅ {msg}", color=0x43B581)

def error_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=f"❌ {msg}", color=0xF04747)

def info_embed(msg: str) -> discord.Embed:
    return discord.Embed(description=f"ℹ️ {msg}", color=0x5865F2)

def timestamp_now() -> int:
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


# ── Views ────────────────────────────────────────────────────────────────────
class CategorySelectView(discord.ui.View):
    """Category selection dropdown for support messages."""

    def __init__(self, categories: dict, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.selected_category: Optional[str] = None

        options = []
        for name, data in list(categories.items())[:25]:
            emoji = data.get("emoji", "📂")
            description = data.get("description", "")[:100] or "Support category"
            options.append(discord.SelectOption(
                label=name.title(),
                value=name,
                description=description,
                emoji=emoji,
            ))

        select = discord.ui.Select(
            placeholder="Choose a category...",
            options=options,
            custom_id="support_category_select"
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        self.selected_category = interaction.data["values"][0]
        await interaction.response.send_message(
            embed=success_embed(f"Category selected: **{self.selected_category.title()}**"),
            ephemeral=True
        )
        self.stop()


class SupportControlView(discord.ui.View):
    """Control buttons for staff managing support threads."""

    def __init__(self, cog: "Support"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close Thread", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="support_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._close_thread(interaction)

    @discord.ui.button(label="Block User", style=discord.ButtonStyle.secondary, emoji="🚫", custom_id="support_block")
    async def block_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._block_user_from_thread(interaction)


class ReplyModal(discord.ui.Modal):
    """Modal for staff to reply to support messages."""

    def __init__(self, cog: "Support", user: discord.User, category: str):
        super().__init__(title=f"Reply to {user.name}")
        self.cog = cog
        self.user = user
        self.category = category

        self.message_input = discord.ui.TextInput(
            label="Your Reply",
            style=discord.TextStyle.paragraph,
            placeholder="Type your response here...",
            required=True,
            max_length=1900,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog._send_reply_to_user(
            interaction.guild,
            interaction.user,
            self.user,
            self.message_input.value,
            self.category
        )
        await interaction.followup.send(
            embed=success_embed(f"Reply sent to {self.user.mention}"),
            ephemeral=True
        )


# ── Main Cog ─────────────────────────────────────────────────────────────────
class Support(commands.Cog):
    """Modernized support/contact system with categories and customization."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=900010, force_registration=True)
        self.config.register_guild(**DEFAULT_GUILD)
        self.config.register_user(**DEFAULT_USER)

        self._control_view = SupportControlView(self)
        self.bot.add_view(self._control_view)

        self._cleanup_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        """Start background tasks on cog load."""
        self._cleanup_task = asyncio.create_task(self._thread_cleanup_loop())

    async def cog_unload(self):
        """Clean up on unload."""
        if self._cleanup_task:
            self._cleanup_task.cancel()

    # ── Data Management ──────────────────────────────────────────────────────
    async def red_delete_data_for_user(self, *, requester: Literal["discord", "owner", "user", "user_strict"], user_id: int):
        """Handle data deletion requests."""
        await self.config.user_from_id(user_id).clear()

    # ── User Commands ────────────────────────────────────────────────────────
    @commands.command(name="contact")
    @commands.dm_only()
    async def contact(self, ctx: commands.Context, *, message: str):
        """Contact server staff with a message.

        Usage: `[p]contact <message>`
        This replaces Red's built-in contact command with enhanced features.
        """
        user_conf = await self.config.user(ctx.author).all()

        if user_conf["blocked"]:
            return await ctx.send(embed=error_embed("You are blocked from contacting staff."))

        guilds_data = await self.config.all_guilds()
        available_guilds = []

        for guild_id, gdata in guilds_data.items():
            if not gdata["enabled"]:
                continue
            guild = self.bot.get_guild(guild_id)
            if guild and guild.get_member(ctx.author.id):
                available_guilds.append((guild, gdata))

        if not available_guilds:
            return await ctx.send(embed=error_embed("No servers have support enabled where you are a member."))

        if len(available_guilds) == 1:
            guild, gdata = available_guilds[0]
            await self._process_contact(ctx, guild, gdata, message, user_conf)
        else:
            embed = discord.Embed(
                title="Multiple Servers Available",
                description="Please use the server's contact command directly or specify which server.",
                color=0x5865F2
            )
            for guild, _ in available_guilds:
                embed.add_field(name=guild.name, value=f"ID: `{guild.id}`", inline=False)
            await ctx.send(embed=embed)

    async def _process_contact(self, ctx: commands.Context, guild: discord.Guild, gdata: dict, message: str, user_conf: dict):
        """Process a contact message."""
        categories = gdata["categories"]
        selected_category = user_conf.get("preference_category") or gdata.get("default_category")

        if gdata["require_category"] and not selected_category and categories:
            view = CategorySelectView(categories)
            prompt = await ctx.send(
                embed=info_embed("Please select a category for your message:"),
                view=view
            )
            await view.wait()
            if view.selected_category:
                selected_category = view.selected_category
            try:
                await prompt.delete()
            except discord.HTTPException:
                pass

        category_data = categories.get(selected_category, {}) if selected_category else {}
        channel_id = category_data.get("channel_id") or (list(categories.values())[0]["channel_id"] if categories else None)

        if not channel_id:
            return await ctx.send(embed=error_embed("No support channel configured. Contact an administrator."))

        channel = guild.get_channel(channel_id)
        if not channel:
            return await ctx.send(embed=error_embed("Support channel not found. Contact an administrator."))

        await self._send_to_staff(ctx.author, guild, channel, message, selected_category, gdata)

        greeting = category_data.get("greeting") or gdata.get("custom_greeting") or \
                   "Your message has been sent to staff. They will respond shortly."
        await ctx.send(embed=success_embed(greeting))

        async with self.config.user(ctx.author).all() as user_data:
            user_data["last_contact"] = timestamp_now()

    @commands.command(name="dm")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def dm_command(self, ctx: commands.Context, user: discord.User, *, message: str):
        """Send a DM to a user from the server.

        Usage: `[p]dm <user> <message>`
        This replaces Red's built-in dm command with enhanced features.
        """
        gdata = await self.config.guild(ctx.guild).all()

        if not gdata["enabled"]:
            return await ctx.send(embed=error_embed("Support system is not enabled."))

        try:
            if gdata["reply_with_embed"]:
                embed = discord.Embed(
                    title=f"Message from {ctx.guild.name}",
                    description=message,
                    color=0x5865F2,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                if gdata["show_author_info"] and not gdata["anonymous_mode"]:
                    embed.set_footer(text=f"From: {ctx.author}", icon_url=ctx.author.display_avatar.url)
                else:
                    embed.set_footer(text=f"From: {ctx.guild.name} Staff")
                await user.send(embed=embed)
            else:
                prefix = f"**Message from {ctx.guild.name}**\n" if gdata["anonymous_mode"] else \
                        f"**{ctx.author}** from **{ctx.guild.name}**:\n"
                await user.send(f"{prefix}{message}")

            await ctx.send(embed=success_embed(f"Message sent to {user.mention}"))

            log_channel_id = gdata["log_channel"]
            if log_channel_id:
                log_channel = ctx.guild.get_channel(log_channel_id)
                if log_channel:
                    log_embed = discord.Embed(
                        title="📤 Staff DM Sent",
                        color=0x43B581,
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    log_embed.add_field(name="Staff", value=ctx.author.mention, inline=True)
                    log_embed.add_field(name="User", value=user.mention, inline=True)
                    log_embed.add_field(name="Message", value=message[:1024], inline=False)
                    await log_channel.send(embed=log_embed)

        except discord.Forbidden:
            await ctx.send(embed=error_embed(f"Cannot send DM to {user.mention}. They may have DMs disabled."))
        except discord.HTTPException as e:
            await ctx.send(embed=error_embed(f"Failed to send DM: {e}"))

    # ── Admin Commands ───────────────────────────────────────────────────────
    @commands.group(name="supportset", aliases=["sset"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def supportset(self, ctx: commands.Context):
        """Configure the support system."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @supportset.command(name="enable")
    async def supportset_enable(self, ctx: commands.Context):
        """Enable the support system for this server."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send(embed=success_embed("Support system enabled!"))

    @supportset.command(name="disable")
    async def supportset_disable(self, ctx: commands.Context):
        """Disable the support system for this server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send(embed=success_embed("Support system disabled."))

    @supportset.command(name="addcategory", aliases=["addcat"])
    async def supportset_addcategory(self, ctx: commands.Context, name: str, channel: discord.TextChannel, *, description: str = ""):
        """Add a support category.

        Usage: `[p]supportset addcategory <name> <channel> [description]`
        """
        async with self.config.guild(ctx.guild).categories() as categories:
            categories[name.lower()] = {
                "channel_id": channel.id,
                "description": description,
                "emoji": "📂",
                "roles": [],
                "greeting": "",
            }
        await ctx.send(embed=success_embed(f"Category **{name}** created with channel {channel.mention}"))

    @supportset.command(name="removecategory", aliases=["removecat", "delcat"])
    async def supportset_removecategory(self, ctx: commands.Context, name: str):
        """Remove a support category."""
        async with self.config.guild(ctx.guild).categories() as categories:
            if name.lower() in categories:
                del categories[name.lower()]
                await ctx.send(embed=success_embed(f"Category **{name}** removed."))
            else:
                await ctx.send(embed=error_embed(f"Category **{name}** not found."))

    @supportset.command(name="setemoji")
    async def supportset_setemoji(self, ctx: commands.Context, category: str, emoji: str):
        """Set an emoji for a category."""
        async with self.config.guild(ctx.guild).categories() as categories:
            if category.lower() not in categories:
                return await ctx.send(embed=error_embed(f"Category **{category}** not found."))
            categories[category.lower()]["emoji"] = emoji
        await ctx.send(embed=success_embed(f"Emoji for **{category}** set to {emoji}"))

    @supportset.command(name="setgreeting")
    async def supportset_setgreeting(self, ctx: commands.Context, category: str, *, greeting: str):
        """Set a custom greeting for a category."""
        async with self.config.guild(ctx.guild).categories() as categories:
            if category.lower() not in categories:
                return await ctx.send(embed=error_embed(f"Category **{category}** not found."))
            categories[category.lower()]["greeting"] = greeting
        await ctx.send(embed=success_embed(f"Greeting set for **{category}**"))

    @supportset.command(name="defaultcategory", aliases=["defaultcat"])
    async def supportset_defaultcategory(self, ctx: commands.Context, name: str):
        """Set the default category for support messages."""
        categories = await self.config.guild(ctx.guild).categories()
        if name.lower() not in categories:
            return await ctx.send(embed=error_embed(f"Category **{name}** not found."))
        await self.config.guild(ctx.guild).default_category.set(name.lower())
        await ctx.send(embed=success_embed(f"Default category set to **{name}**"))

    @supportset.command(name="logchannel")
    async def supportset_logchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Set or clear the log channel for support messages."""
        if channel:
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            await ctx.send(embed=success_embed(f"Log channel set to {channel.mention}"))
        else:
            await self.config.guild(ctx.guild).log_channel.set(None)
            await ctx.send(embed=success_embed("Log channel cleared."))

    @supportset.command(name="anonymous")
    async def supportset_anonymous(self, ctx: commands.Context, enabled: bool):
        """Toggle anonymous mode for staff replies."""
        await self.config.guild(ctx.guild).anonymous_mode.set(enabled)
        status = "enabled" if enabled else "disabled"
        await ctx.send(embed=success_embed(f"Anonymous mode {status}."))

    @supportset.command(name="requirecategory")
    async def supportset_requirecategory(self, ctx: commands.Context, enabled: bool):
        """Toggle whether users must select a category."""
        await self.config.guild(ctx.guild).require_category.set(enabled)
        status = "enabled" if enabled else "disabled"
        await ctx.send(embed=success_embed(f"Category requirement {status}."))

    @supportset.command(name="embed")
    async def supportset_embed(self, ctx: commands.Context, enabled: bool):
        """Toggle using embeds for replies."""
        await self.config.guild(ctx.guild).reply_with_embed.set(enabled)
        status = "enabled" if enabled else "disabled"
        await ctx.send(embed=success_embed(f"Embed replies {status}."))

    @supportset.command(name="showinfo")
    async def supportset_showinfo(self, ctx: commands.Context, enabled: bool):
        """Toggle showing author info in replies."""
        await self.config.guild(ctx.guild).show_author_info.set(enabled)
        status = "enabled" if enabled else "disabled"
        await ctx.send(embed=success_embed(f"Author info {status}."))

    @supportset.command(name="list")
    async def supportset_list(self, ctx: commands.Context):
        """List all support categories and settings."""
        gdata = await self.config.guild(ctx.guild).all()

        embed = discord.Embed(
            title=f"Support System — {ctx.guild.name}",
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        status = "✅ Enabled" if gdata["enabled"] else "❌ Disabled"
        embed.add_field(name="Status", value=status, inline=True)

        if gdata["default_category"]:
            embed.add_field(name="Default Category", value=gdata["default_category"].title(), inline=True)

        if gdata["log_channel"]:
            log_ch = ctx.guild.get_channel(gdata["log_channel"])
            embed.add_field(name="Log Channel", value=log_ch.mention if log_ch else "Not found", inline=True)

        settings = []
        if gdata["anonymous_mode"]:
            settings.append("🔒 Anonymous Mode")
        if gdata["require_category"]:
            settings.append("📋 Require Category")
        if gdata["reply_with_embed"]:
            settings.append("📝 Embed Replies")
        if gdata["show_author_info"]:
            settings.append("👤 Show Author Info")

        if settings:
            embed.add_field(name="Settings", value="\n".join(settings), inline=False)

        categories = gdata["categories"]
        if categories:
            cat_list = []
            for name, data in categories.items():
                channel = ctx.guild.get_channel(data["channel_id"])
                emoji = data.get("emoji", "📂")
                cat_list.append(f"{emoji} **{name.title()}** → {channel.mention if channel else 'Missing'}")
            embed.add_field(name="Categories", value="\n".join(cat_list[:10]), inline=False)
        else:
            embed.add_field(name="Categories", value="None configured", inline=False)

        await ctx.send(embed=embed)

    @supportset.command(name="block")
    async def supportset_block(self, ctx: commands.Context, user: discord.User):
        """Block a user from using the support system."""
        await self.config.user(user).blocked.set(True)
        await ctx.send(embed=success_embed(f"{user.mention} has been blocked from support."))

    @supportset.command(name="unblock")
    async def supportset_unblock(self, ctx: commands.Context, user: discord.User):
        """Unblock a user from using the support system."""
        await self.config.user(user).blocked.set(False)
        await ctx.send(embed=success_embed(f"{user.mention} has been unblocked from support."))

    # ── Internal Methods ─────────────────────────────────────────────────────
    async def _send_to_staff(self, user: discord.User, guild: discord.Guild, channel: discord.TextChannel,
                            message: str, category: Optional[str], gdata: dict):
        """Send a user's message to the staff channel."""
        embed = discord.Embed(
            title=f"📨 Support Message",
            description=message,
            color=0x5865F2,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)

        if category:
            embed.add_field(name="Category", value=category.title(), inline=True)

        member = guild.get_member(user.id)
        if member:
            embed.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=True)
            roles = [r.mention for r in member.roles if r != guild.default_role]
            if roles:
                embed.add_field(name="Roles", value=", ".join(roles[:5]), inline=False)

        embed.set_footer(text=f"User ID: {user.id}")

        await channel.send(embed=embed)

        log_channel_id = gdata["log_channel"]
        if log_channel_id and log_channel_id != channel.id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="📥 Support Message Received",
                    color=0x5865F2,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                log_embed.add_field(name="User", value=user.mention, inline=True)
                log_embed.add_field(name="Channel", value=channel.mention, inline=True)
                if category:
                    log_embed.add_field(name="Category", value=category.title(), inline=True)
                log_embed.add_field(name="Message", value=message[:1024], inline=False)
                await log_channel.send(embed=log_embed)

    async def _send_reply_to_user(self, guild: discord.Guild, staff_member: discord.Member,
                                  user: discord.User, message: str, category: Optional[str]):
        """Send a staff reply to a user."""
        gdata = await self.config.guild(guild).all()

        try:
            if gdata["reply_with_embed"]:
                embed = discord.Embed(
                    title=f"Reply from {guild.name}",
                    description=message,
                    color=0x43B581,
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                if gdata["show_author_info"] and not gdata["anonymous_mode"]:
                    embed.set_footer(text=f"From: {staff_member}", icon_url=staff_member.display_avatar.url)
                else:
                    embed.set_footer(text=f"From: {guild.name} Staff")
                await user.send(embed=embed)
            else:
                prefix = f"**Reply from {guild.name}**\n" if gdata["anonymous_mode"] else \
                        f"**{staff_member}** from **{guild.name}**:\n"
                await user.send(f"{prefix}{message}")
        except discord.Forbidden:
            pass

    async def _close_thread(self, interaction: discord.Interaction):
        """Close an active support thread."""
        ch_id = str(interaction.channel.id)
        async with self.config.guild(interaction.guild).active_threads() as threads:
            if ch_id in threads:
                del threads[ch_id]
        await interaction.response.send_message(
            embed=success_embed("Support thread closed."),
            ephemeral=True
        )

    async def _block_user_from_thread(self, interaction: discord.Interaction):
        """Block a user from an active thread."""
        ch_id = str(interaction.channel.id)
        threads = await self.config.guild(interaction.guild).active_threads()
        thread = threads.get(ch_id)

        if not thread:
            return await interaction.response.send_message(
                embed=error_embed("No active thread in this channel."),
                ephemeral=True
            )

        user_id = thread.get("user_id")
        if user_id:
            await self.config.user_from_id(user_id).blocked.set(True)
            await interaction.response.send_message(
                embed=success_embed(f"User <@{user_id}> blocked from support."),
                ephemeral=True
            )

    async def _thread_cleanup_loop(self):
        """Background task to clean up inactive threads."""
        await self.bot.wait_until_ready()
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes

                for guild in self.bot.guilds:
                    gdata = await self.config.guild(guild).all()
                    if not gdata["enabled"]:
                        continue

                    timeout = gdata["thread_timeout"]
                    now = timestamp_now()

                    async with self.config.guild(guild).active_threads() as threads:
                        to_remove = []
                        for ch_id, thread in threads.items():
                            started = thread.get("started_at", now)
                            if now - started > timeout:
                                to_remove.append(ch_id)

                        for ch_id in to_remove:
                            del threads[ch_id]

            except asyncio.CancelledError:
                break
            except Exception:
                pass
