"""NexusCore — Giveaway system with requirements, bonus entries, scheduling, recurring, drops."""

from __future__ import annotations

import asyncio
import datetime
import random
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    ts_full, duration_str, parse_duration, safe_send, safe_dm, Paginator,
)

# ── Defaults ───────────────────────────────────────────────────────────────
GIVE_DEFAULTS_GUILD = {
    "enabled": True,
    "giveaways": {},
    # gw_id -> {
    #   channel_id, message_id, prize, description, winners_count, host_id,
    #   ends_at, started_at, ended, entries: [user_id],
    #   require_role, blacklist_role, require_account_days, require_server_days,
    #   bonus_roles: {role_id: extra_entries},
    #   dm_winner, dm_host, ping_role, image_url,
    #   recurring_interval, recurring_count,
    #   drop_mode (first N to click win), won_by: [user_id],
    # }
    "log_channel": None,
    "dm_winners": True,
    "dm_hosts": True,
    "default_colour": Clr.GIVE.value,
    "end_message": "🎉 Congratulations {winners}! You won **{prize}**!",
    "manager_roles": [],
    "blacklisted": [],
}


# ── Views ──────────────────────────────────────────────────────────────────
class GiveawayView(discord.ui.View):
    def __init__(self, cog: "GiveawaysMixin", gw_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.gw_id = gw_id

    @discord.ui.button(label="🎉 Enter", style=discord.ButtonStyle.primary, custom_id="nexus_gw_enter")
    async def enter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._enter_giveaway(interaction, self.gw_id)

    @discord.ui.button(label="Entries: 0", style=discord.ButtonStyle.secondary, custom_id="nexus_gw_count", disabled=True)
    async def count_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="ℹ️ Info", style=discord.ButtonStyle.secondary, custom_id="nexus_gw_info")
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._giveaway_info(interaction, self.gw_id)


class GiveawayEndedView(discord.ui.View):
    def __init__(self, cog: "GiveawaysMixin", gw_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.gw_id = gw_id

    @discord.ui.button(label="🔁 Reroll", style=discord.ButtonStyle.secondary, custom_id="nexus_gw_reroll")
    async def reroll_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            gdata = await self.cog.give_config.guild(interaction.guild).all()
            manager_roles = gdata.get("manager_roles", [])
            if not any(r.id in manager_roles for r in interaction.user.roles):
                return await interaction.response.send_message("No permission.", ephemeral=True)
        await self.cog._reroll_giveaway(interaction, self.gw_id)


# ── Mixin ──────────────────────────────────────────────────────────────────
class GiveawaysMixin:
    """Giveaway system mixin."""

    def _init_giveaways(self, bot):
        self.give_config = Config.get_conf(
            None, identifier=900005, cog_name="NexusCoreGiveaways"
        )
        self.give_config.register_guild(**GIVE_DEFAULTS_GUILD)
        self._gw_tasks = {}  # gw_id -> asyncio.Task
        self.bot = bot

    async def _load_giveaways(self):
        """Restart timers for active giveaways."""
        all_guilds = await self.give_config.all_guilds()
        for guild_id, gdata in all_guilds.items():
            for gw_id, gw in gdata.get("giveaways", {}).items():
                if not gw.get("ended"):
                    self._schedule_gw_end(guild_id, gw_id, gw["ends_at"])

    def _schedule_gw_end(self, guild_id: int, gw_id: str, ends_at: int):
        delay = max(0, ends_at - ts_now())

        async def end_task():
            await asyncio.sleep(delay)
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._end_giveaway(guild, gw_id)

        task = asyncio.create_task(end_task())
        self._gw_tasks[gw_id] = task

    async def _create_giveaway(
        self, ctx: commands.Context, channel: discord.TextChannel,
        prize: str, duration_sec: int, winners: int = 1, *,
        description: str = "", host: discord.Member | None = None,
        require_role: discord.Role | None = None,
        blacklist_role: discord.Role | None = None,
        require_account_days: int = 0,
        require_server_days: int = 0,
        bonus_roles: dict | None = None,
        ping_role: discord.Role | None = None,
        image_url: str | None = None,
        drop_mode: bool = False,
        recurring_interval: int = 0,
    ) -> str:
        gw_id = short_id(10)
        ends_at = ts_now() + duration_sec
        host = host or ctx.author

        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"**{prize}**\n\n{description}" if description else f"**{prize}**",
            colour=Clr.GIVE,
            timestamp=datetime.datetime.fromtimestamp(ends_at, tz=datetime.timezone.utc),
        )
        embed.add_field(name="Ends", value=ts_relative(ends_at), inline=True)
        embed.add_field(name="Winners", value=str(winners), inline=True)
        embed.add_field(name="Hosted by", value=host.mention, inline=True)
        embed.add_field(name="Entries", value="0", inline=True)

        if require_role:
            embed.add_field(name="Required Role", value=require_role.mention, inline=True)
        if bonus_roles:
            bonus_text = "\n".join(f"<@&{rid}>: +{extra}" for rid, extra in bonus_roles.items())
            embed.add_field(name="Bonus Entries", value=bonus_text, inline=False)
        if image_url:
            embed.set_image(url=image_url)

        embed.set_footer(text=f"ID: {gw_id} · Ends at")

        if drop_mode:
            embed.title = "🎁 DROP GIVEAWAY 🎁"
            embed.description = f"**{prize}**\n\nFirst {winners} to click win!"

        view = GiveawayView(self, gw_id)
        ping_text = ping_role.mention if ping_role else None
        msg = await channel.send(content=ping_text, embed=embed, view=view)

        gw_data = {
            "channel_id": channel.id,
            "message_id": msg.id,
            "prize": prize,
            "description": description,
            "winners_count": winners,
            "host_id": host.id,
            "ends_at": ends_at,
            "started_at": ts_now(),
            "ended": False,
            "entries": [],
            "require_role": require_role.id if require_role else None,
            "blacklist_role": blacklist_role.id if blacklist_role else None,
            "require_account_days": require_account_days,
            "require_server_days": require_server_days,
            "bonus_roles": bonus_roles or {},
            "dm_winner": True,
            "dm_host": True,
            "ping_role": ping_role.id if ping_role else None,
            "image_url": image_url,
            "recurring_interval": recurring_interval,
            "recurring_count": 0,
            "drop_mode": drop_mode,
            "won_by": [],
        }

        async with self.give_config.guild(ctx.guild).giveaways() as gws:
            gws[gw_id] = gw_data

        if not drop_mode:
            self._schedule_gw_end(ctx.guild.id, gw_id, ends_at)

        return gw_id

    async def _enter_giveaway(self, interaction: discord.Interaction, gw_id: str):
        guild = interaction.guild
        user = interaction.user
        conf = self.give_config.guild(guild)
        data = await conf.all()
        gw = data["giveaways"].get(gw_id)

        if not gw:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)
        if gw["ended"]:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        if user.id in gw["entries"]:
            return await interaction.response.send_message("You're already entered!", ephemeral=True)
        if str(user.id) in [str(x) for x in data["blacklisted"]]:
            return await interaction.response.send_message("You're blacklisted from giveaways.", ephemeral=True)

        # Requirement checks
        if gw["require_role"]:
            role = guild.get_role(gw["require_role"])
            if role and role not in user.roles:
                return await interaction.response.send_message(f"You need {role.mention} to enter.", ephemeral=True)

        if gw["blacklist_role"]:
            bl_role = guild.get_role(gw["blacklist_role"])
            if bl_role and bl_role in user.roles:
                return await interaction.response.send_message("You can't enter this giveaway.", ephemeral=True)

        if gw["require_account_days"]:
            age = (datetime.datetime.now(datetime.timezone.utc) - user.created_at).days
            if age < gw["require_account_days"]:
                return await interaction.response.send_message(
                    f"Account must be {gw['require_account_days']}+ days old.", ephemeral=True
                )

        if gw["require_server_days"] and user.joined_at:
            days = (datetime.datetime.now(datetime.timezone.utc) - user.joined_at).days
            if days < gw["require_server_days"]:
                return await interaction.response.send_message(
                    f"Must be in server {gw['require_server_days']}+ days.", ephemeral=True
                )

        # Drop mode — instant win
        if gw.get("drop_mode"):
            async with conf.giveaways() as gws:
                g = gws.get(gw_id)
                if g and len(g.get("won_by", [])) < g["winners_count"]:
                    g["won_by"].append(user.id)
                    g["entries"].append(user.id)
                    if len(g["won_by"]) >= g["winners_count"]:
                        g["ended"] = True
                    gws[gw_id] = g

            if len(gw.get("won_by", [])) + 1 <= gw["winners_count"]:
                await interaction.response.send_message(f"🎁 You won **{gw['prize']}**!", ephemeral=True)
                ch = guild.get_channel(gw["channel_id"])
                if ch:
                    await safe_send(ch, f"🎁 {user.mention} claimed **{gw['prize']}**!")
            else:
                await interaction.response.send_message("Too late! All prizes claimed.", ephemeral=True)
            return

        async with conf.giveaways() as gws:
            g = gws.get(gw_id)
            if g:
                g["entries"].append(user.id)
                gws[gw_id] = g

        # Calculate effective entries with bonus
        entries_count = len(gw["entries"]) + 1
        await interaction.response.send_message(
            f"🎉 You've entered! ({entries_count} total entries)", ephemeral=True
        )

        # Update embed entry count
        ch = guild.get_channel(gw["channel_id"])
        if ch:
            try:
                msg = await ch.fetch_message(gw["message_id"])
                if msg.embeds:
                    embed = msg.embeds[0]
                    for i, f in enumerate(embed.fields):
                        if f.name == "Entries":
                            embed.set_field_at(i, name="Entries", value=str(entries_count), inline=True)
                    await msg.edit(embed=embed)
            except discord.HTTPException:
                pass

    async def _end_giveaway(self, guild: discord.Guild, gw_id: str):
        data = await self.give_config.guild(guild).all()
        gw = data["giveaways"].get(gw_id)
        if not gw or gw["ended"]:
            return

        async with self.give_config.guild(guild).giveaways() as gws:
            if gw_id in gws:
                gws[gw_id]["ended"] = True

        channel = guild.get_channel(gw["channel_id"])
        if not channel:
            return

        # Build weighted entries (bonus roles)
        weighted = []
        for uid in gw["entries"]:
            weight = 1
            member = guild.get_member(uid)
            if member:
                for role_id_str, extra in gw.get("bonus_roles", {}).items():
                    role = guild.get_role(int(role_id_str))
                    if role and role in member.roles:
                        weight += extra
            weighted.extend([uid] * weight)

        winners_count = min(gw["winners_count"], len(set(gw["entries"])))
        winners = []
        pool = list(set(weighted))
        if pool:
            # Weighted selection without replacement
            selected = set()
            attempts = 0
            while len(winners) < winners_count and attempts < 1000:
                pick = random.choice(weighted)
                if pick not in selected:
                    selected.add(pick)
                    winners.append(pick)
                attempts += 1

        async with self.give_config.guild(guild).giveaways() as gws:
            if gw_id in gws:
                gws[gw_id]["won_by"] = winners

        if winners:
            winner_mentions = ", ".join(f"<@{w}>" for w in winners)
            end_msg = data.get("end_message", "🎉 Congratulations {winners}! You won **{prize}**!")
            end_msg = end_msg.replace("{winners}", winner_mentions).replace("{prize}", gw["prize"])
        else:
            end_msg = "No valid entries — no winner."
            winner_mentions = "None"

        # Update embed
        try:
            msg = await channel.fetch_message(gw["message_id"])
            if msg.embeds:
                embed = msg.embeds[0]
                embed.title = "🎉 GIVEAWAY ENDED 🎉"
                embed.colour = discord.Colour(0x2F3136)
                embed.description = f"**{gw['prize']}**\n\nWinner(s): {winner_mentions}"
                embed.set_footer(text=f"Ended · {len(gw['entries'])} entries")
                embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
                view = GiveawayEndedView(self, gw_id)
                await msg.edit(embed=embed, view=view)
        except discord.HTTPException:
            pass

        await safe_send(channel, end_msg)

        # DM winners
        if gw.get("dm_winner", True) or data.get("dm_winners", True):
            for w in winners:
                user = guild.get_member(w)
                if user:
                    await safe_dm(user, embed=discord.Embed(
                        title="🎉 You Won!",
                        description=f"You won **{gw['prize']}** in **{guild.name}**!",
                        colour=Clr.GIVE,
                    ))

        # DM host
        if gw.get("dm_host", True) or data.get("dm_hosts", True):
            host = guild.get_member(gw["host_id"])
            if host:
                await safe_dm(host, embed=discord.Embed(
                    title="🎉 Giveaway Ended",
                    description=f"Your giveaway for **{gw['prize']}** ended.\nWinner(s): {winner_mentions}\nEntries: {len(gw['entries'])}",
                    colour=Clr.GIVE,
                ))

        # Recurring
        if gw.get("recurring_interval", 0) > 0:
            new_gw_id = short_id(10)
            new_ends = ts_now() + gw["recurring_interval"]
            new_gw = dict(gw)
            new_gw["ended"] = False
            new_gw["entries"] = []
            new_gw["won_by"] = []
            new_gw["ends_at"] = new_ends
            new_gw["started_at"] = ts_now()
            new_gw["recurring_count"] = gw.get("recurring_count", 0) + 1

            embed = discord.Embed(
                title="🎉 GIVEAWAY 🎉",
                description=f"**{gw['prize']}**\n\n{gw.get('description', '')}",
                colour=Clr.GIVE,
                timestamp=datetime.datetime.fromtimestamp(new_ends, tz=datetime.timezone.utc),
            )
            embed.add_field(name="Ends", value=ts_relative(new_ends), inline=True)
            embed.add_field(name="Winners", value=str(gw["winners_count"]), inline=True)
            embed.add_field(name="Hosted by", value=f"<@{gw['host_id']}>", inline=True)
            embed.add_field(name="Entries", value="0", inline=True)
            embed.set_footer(text=f"ID: {new_gw_id} · Recurring #{new_gw['recurring_count']} · Ends at")

            view = GiveawayView(self, new_gw_id)
            new_msg = await channel.send(embed=embed, view=view)
            new_gw["message_id"] = new_msg.id

            async with self.give_config.guild(guild).giveaways() as gws:
                gws[new_gw_id] = new_gw

            self._schedule_gw_end(guild.id, new_gw_id, new_ends)

    async def _reroll_giveaway(self, interaction: discord.Interaction, gw_id: str):
        guild = interaction.guild
        data = await self.give_config.guild(guild).all()
        gw = data["giveaways"].get(gw_id)
        if not gw:
            return await interaction.response.send_message("Not found.", ephemeral=True)
        if not gw["ended"]:
            return await interaction.response.send_message("Giveaway hasn't ended yet.", ephemeral=True)

        pool = [uid for uid in gw["entries"] if uid not in gw.get("won_by", [])]
        if not pool:
            return await interaction.response.send_message("No eligible entries for reroll.", ephemeral=True)

        new_winner = random.choice(pool)
        async with self.give_config.guild(guild).giveaways() as gws:
            if gw_id in gws:
                gws[gw_id]["won_by"].append(new_winner)

        await interaction.response.send_message(f"🎉 New winner: <@{new_winner}> — **{gw['prize']}**!")

        user = guild.get_member(new_winner)
        if user:
            await safe_dm(user, embed=discord.Embed(
                title="🎉 You Won (Reroll)!",
                description=f"You won **{gw['prize']}** in **{guild.name}** from a reroll!",
                colour=Clr.GIVE,
            ))

    async def _giveaway_info(self, interaction: discord.Interaction, gw_id: str):
        data = await self.give_config.guild(interaction.guild).all()
        gw = data["giveaways"].get(gw_id)
        if not gw:
            return await interaction.response.send_message("Not found.", ephemeral=True)

        embed = discord.Embed(title=f"🎉 {gw['prize']}", colour=Clr.GIVE)
        embed.add_field(name="Entries", value=str(len(gw["entries"])), inline=True)
        embed.add_field(name="Winners", value=str(gw["winners_count"]), inline=True)
        embed.add_field(name="Ends", value=ts_relative(gw["ends_at"]) if not gw["ended"] else "Ended", inline=True)
        embed.add_field(name="Host", value=f"<@{gw['host_id']}>", inline=True)

        reqs = []
        if gw.get("require_role"):
            reqs.append(f"Role: <@&{gw['require_role']}>")
        if gw.get("require_account_days"):
            reqs.append(f"Account age: {gw['require_account_days']}d+")
        if gw.get("require_server_days"):
            reqs.append(f"Server age: {gw['require_server_days']}d+")
        if reqs:
            embed.add_field(name="Requirements", value="\n".join(reqs), inline=False)

        if gw.get("bonus_roles"):
            bonus = "\n".join(f"<@&{rid}>: +{extra}" for rid, extra in gw["bonus_roles"].items())
            embed.add_field(name="Bonus Entries", value=bonus, inline=False)

        in_gw = interaction.user.id in gw["entries"]
        embed.set_footer(text=f"{'✅ You are entered' if in_gw else '❌ Not entered'} · ID: {gw_id}")

        await interaction.response.send_message(embed=embed, ephemeral=True)
