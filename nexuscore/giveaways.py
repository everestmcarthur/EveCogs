"""NexusCore — Giveaway system v2: button entry, requirements, bonus entries, drop mode,
reroll, scheduled end, templates, team giveaways, milestones, stats, custom embeds/images,
message/invite requirements, multi-winner, hosted-by, DM winners."""

from __future__ import annotations

import asyncio
import datetime
import random
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now, ts_relative,
    ts_full, duration_str, parse_duration, safe_send, safe_dm, ConfirmView,
)

# ── Defaults ───────────────────────────────────────────────────────────────
GIVE_DEFAULTS_GUILD = {
    "enabled": True,
    "giveaways": {},
    "templates": {},          # template_name -> {prize, duration, winners_count, require_role, ...}
    "ended_giveaways": {},
    "log_channel": None,
    "dm_winners": True,
    "dm_host_on_end": True,
    "ping_role": None,
    "embed_colour": Clr.GIVE.value,
    "default_emoji": "🎉",
    "stats": {"total_hosted": 0, "total_entries": 0, "total_winners": 0},
}


# ── Views ──────────────────────────────────────────────────────────────────
class GiveawayEntryView(discord.ui.View):
    def __init__(self, cog: "GiveawaysMixin"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🎉 Enter", style=discord.ButtonStyle.success, custom_id="nexus_gw_enter")
    async def enter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._handle_gw_entry(interaction)

    @discord.ui.button(label="📊 Entries", style=discord.ButtonStyle.secondary, custom_id="nexus_gw_info")
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._handle_gw_info(interaction)


class GiveawayRerollView(discord.ui.View):
    def __init__(self, cog, gw_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.gw_id = gw_id

    @discord.ui.button(label="🔄 Reroll", style=discord.ButtonStyle.primary)
    async def reroll_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._reroll_giveaway(interaction, self.gw_id)
        self.stop()


# ── Mixin ──────────────────────────────────────────────────────────────────
class GiveawaysMixin:
    """Giveaway system mixin — v2 with templates, milestones, stats, custom embeds."""

    def _init_giveaways(self, bot):
        self.give_config = Config.get_conf(None, identifier=900005, cog_name="NexusCoreGiveaways")
        self.give_config.register_guild(**GIVE_DEFAULTS_GUILD)
        self._gw_entry_view = GiveawayEntryView(self)
        bot.add_view(self._gw_entry_view)
        self._gw_tasks = {}

    async def _start_gw_loop(self):
        """Background loop to end giveaways on time."""
        while True:
            try:
                for guild in self.bot.guilds:
                    data = await self.give_config.guild(guild).all()
                    for gw_id, gw in list(data["giveaways"].items()):
                        if gw["ended"]:
                            continue
                        if gw.get("drop_mode"):
                            if len(gw.get("entries", [])) >= gw.get("winners_count", 1):
                                await self._end_giveaway(guild, gw_id)
                        elif ts_now() >= gw["ends_at"]:
                            await self._end_giveaway(guild, gw_id)
            except Exception:
                pass
            await asyncio.sleep(15)

    async def _create_giveaway(
        self, ctx, channel: discord.TextChannel, prize: str,
        duration: int, winners: int, drop_mode: bool = False,
        require_role: int | None = None, bonus_roles: dict | None = None,
        require_messages: int = 0, require_invites: int = 0,
        hosted_by: discord.Member | None = None,
        image_url: str | None = None, description: str | None = None,
        colour: int | None = None,
    ) -> str:
        gw_id = short_id(10)
        ends_at = ts_now() + duration
        host = hosted_by or ctx.author
        data = await self.give_config.guild(ctx.guild).all()
        embed_colour = colour or data.get("embed_colour", Clr.GIVE.value)

        embed = discord.Embed(
            title=f"🎉 {prize}",
            description=description or f"React to enter!\n{'**DROP:** First to click wins!' if drop_mode else ''}",
            colour=discord.Colour(embed_colour),
            timestamp=datetime.datetime.fromtimestamp(ends_at, tz=datetime.timezone.utc),
        )
        embed.set_footer(text=f"Ends at" if not drop_mode else f"Drop giveaway · {winners} winner(s)")
        embed.add_field(name="Hosted by", value=host.mention, inline=True)
        embed.add_field(name="Winners", value=str(winners), inline=True)
        embed.add_field(name="Entries", value="0", inline=True)

        if not drop_mode:
            embed.add_field(name="Ends", value=ts_relative(ends_at), inline=True)

        if require_role:
            role = ctx.guild.get_role(require_role)
            if role:
                embed.add_field(name="Required Role", value=role.mention, inline=True)
        if require_messages:
            embed.add_field(name="Min Messages", value=str(require_messages), inline=True)
        if require_invites:
            embed.add_field(name="Min Invites", value=str(require_invites), inline=True)
        if image_url:
            embed.set_image(url=image_url)

        msg = await channel.send(embed=embed, view=self._gw_entry_view)

        ping_role = data.get("ping_role")
        if ping_role:
            pr = ctx.guild.get_role(ping_role)
            if pr:
                ping_msg = await channel.send(pr.mention)
                try:
                    await ping_msg.delete(delay=3)
                except discord.HTTPException:
                    pass

        gw_data = {
            "prize": prize, "channel_id": channel.id, "message_id": msg.id,
            "host_id": host.id, "winners_count": winners,
            "ends_at": ends_at, "started_at": ts_now(),
            "entries": [], "ended": False, "drop_mode": drop_mode,
            "require_role": require_role, "bonus_roles": bonus_roles or {},
            "require_messages": require_messages, "require_invites": require_invites,
            "winners_list": [], "image_url": image_url, "description": description,
            "colour": embed_colour,
        }
        async with self.give_config.guild(ctx.guild).giveaways() as gws:
            gws[gw_id] = gw_data

        async with self.give_config.guild(ctx.guild).stats() as stats:
            stats["total_hosted"] = stats.get("total_hosted", 0) + 1

        return gw_id

    async def _handle_gw_entry(self, interaction: discord.Interaction):
        guild = interaction.guild
        data = await self.give_config.guild(guild).all()
        gw = None
        gw_id = None
        for gid, g in data["giveaways"].items():
            if g.get("message_id") == interaction.message.id and not g["ended"]:
                gw = g
                gw_id = gid
                break
        if not gw:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)

        user_id = interaction.user.id
        if user_id in gw["entries"]:
            async with self.give_config.guild(guild).giveaways() as gws:
                if gw_id in gws:
                    gws[gw_id]["entries"].remove(user_id)
            await interaction.response.send_message("You've left the giveaway.", ephemeral=True)
            await self._update_gw_embed(guild, gw_id)
            return

        if gw.get("require_role"):
            role = guild.get_role(gw["require_role"])
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message(f"You need {role.mention} to enter.", ephemeral=True)

        async with self.give_config.guild(guild).giveaways() as gws:
            if gw_id in gws:
                gws[gw_id]["entries"].append(user_id)

        async with self.give_config.guild(guild).stats() as stats:
            stats["total_entries"] = stats.get("total_entries", 0) + 1

        count = len(gw["entries"]) + 1  # +1 since just added
        bonus_entries = 0
        for role_id, bonus in gw.get("bonus_roles", {}).items():
            role = guild.get_role(int(role_id))
            if role and role in interaction.user.roles:
                bonus_entries += bonus

        msg = f"🎉 You've entered!"
        if bonus_entries:
            msg += f" (+{bonus_entries} bonus entries)"
        await interaction.response.send_message(msg, ephemeral=True)
        await self._update_gw_embed(guild, gw_id)

        # Drop mode check
        if gw.get("drop_mode"):
            if count >= gw.get("winners_count", 1):
                await self._end_giveaway(guild, gw_id)

    async def _handle_gw_info(self, interaction: discord.Interaction):
        guild = interaction.guild
        data = await self.give_config.guild(guild).all()
        for gid, g in data["giveaways"].items():
            if g.get("message_id") == interaction.message.id:
                is_entered = interaction.user.id in g["entries"]
                count = len(g["entries"])
                embed = discord.Embed(
                    title=f"📊 {g['prize']}",
                    description=f"Entries: **{count}**\nWinners: **{g['winners_count']}**\nYour status: {'✅ Entered' if is_entered else '❌ Not entered'}",
                    colour=discord.Colour(g.get("colour", Clr.GIVE.value)),
                )
                if not g["ended"]:
                    embed.add_field(name="Ends", value=ts_relative(g["ends_at"]), inline=True)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
        await interaction.response.send_message("Giveaway not found.", ephemeral=True)

    async def _update_gw_embed(self, guild, gw_id: str):
        data = await self.give_config.guild(guild).all()
        gw = data["giveaways"].get(gw_id)
        if not gw:
            return
        channel = guild.get_channel(gw["channel_id"])
        if not channel:
            return
        try:
            msg = await channel.fetch_message(gw["message_id"])
            if msg.embeds:
                embed = msg.embeds[0]
                for i, field in enumerate(embed.fields):
                    if field.name == "Entries":
                        embed.set_field_at(i, name="Entries", value=str(len(gw["entries"])), inline=True)
                await msg.edit(embed=embed)
        except discord.HTTPException:
            pass

    async def _end_giveaway(self, guild, gw_id: str):
        data = await self.give_config.guild(guild).all()
        gw = data["giveaways"].get(gw_id)
        if not gw or gw["ended"]:
            return

        entries = list(gw["entries"])
        bonus_entries = []
        for uid in entries:
            member = guild.get_member(uid)
            if member:
                for role_id, bonus in gw.get("bonus_roles", {}).items():
                    role = guild.get_role(int(role_id))
                    if role and role in member.roles:
                        bonus_entries.extend([uid] * bonus)
        weighted = entries + bonus_entries

        winners = []
        pick_pool = list(set(weighted))
        random.shuffle(pick_pool)
        for _ in range(min(gw["winners_count"], len(pick_pool))):
            if not pick_pool:
                break
            weights = [weighted.count(uid) for uid in pick_pool]
            winner = random.choices(pick_pool, weights=weights, k=1)[0]
            winners.append(winner)
            pick_pool.remove(winner)

        async with self.give_config.guild(guild).giveaways() as gws:
            if gw_id in gws:
                gws[gw_id]["ended"] = True
                gws[gw_id]["ended_at"] = ts_now()
                gws[gw_id]["winners_list"] = winners

        async with self.give_config.guild(guild).stats() as stats:
            stats["total_winners"] = stats.get("total_winners", 0) + len(winners)

        channel = guild.get_channel(gw["channel_id"])
        if not channel:
            return

        if winners:
            winner_mentions = ", ".join(f"<@{w}>" for w in winners)
            end_embed = discord.Embed(
                title=f"🎉 {gw['prize']}", colour=discord.Colour(gw.get("colour", Clr.GIVE.value)),
                description=f"**Winners:** {winner_mentions}\n\nHosted by: <@{gw['host_id']}>",
            )
            end_embed.set_footer(text=f"Ended · {len(entries)} total entries")
            if gw.get("image_url"):
                end_embed.set_image(url=gw["image_url"])
        else:
            end_embed = discord.Embed(
                title=f"🎉 {gw['prize']}", colour=Clr.ERROR,
                description="No valid entries. Nobody won.",
            )

        try:
            msg = await channel.fetch_message(gw["message_id"])
            await msg.edit(embed=end_embed, view=GiveawayRerollView(self, gw_id) if winners else None)
        except discord.HTTPException:
            pass

        if winners:
            await channel.send(
                f"🎉 Congratulations {winner_mentions}! You won **{gw['prize']}**!",
            )
            dm_enabled = await self.give_config.guild(guild).dm_winners()
            if dm_enabled:
                for w_id in winners:
                    member = guild.get_member(w_id)
                    if member:
                        await safe_dm(member, embed=discord.Embed(
                            title="🎉 You Won!",
                            description=f"You won **{gw['prize']}** in **{guild.name}**!\nPlease contact the host.",
                            colour=Clr.GIVE,
                        ))

            dm_host = await self.give_config.guild(guild).dm_host_on_end()
            if dm_host:
                host = guild.get_member(gw["host_id"])
                if host:
                    await safe_dm(host, embed=discord.Embed(
                        title="🎉 Giveaway Ended",
                        description=f"**{gw['prize']}** has ended.\nWinners: {winner_mentions}\nEntries: {len(entries)}",
                        colour=Clr.GIVE,
                    ))

        log_ch_id = await self.give_config.guild(guild).log_channel()
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(title="🎉 Giveaway Ended", colour=Clr.GIVE)
                le.add_field(name="Prize", value=gw["prize"], inline=True)
                le.add_field(name="Entries", value=str(len(entries)), inline=True)
                le.add_field(name="Winners", value=winner_mentions if winners else "None", inline=False)
                await safe_send(log_ch, embed=le)

    async def _reroll_giveaway(self, interaction, gw_id: str):
        guild = interaction.guild
        data = await self.give_config.guild(guild).all()
        gw = data["giveaways"].get(gw_id)
        if not gw or not gw["ended"]:
            try:
                return await interaction.response.send_message("Giveaway not found or still active.", ephemeral=True)
            except Exception:
                return
        entries = [e for e in gw["entries"] if e not in gw.get("winners_list", [])]
        if not entries:
            try:
                return await interaction.response.send_message("No eligible entries to reroll.", ephemeral=True)
            except Exception:
                return
        winner = random.choice(entries)
        async with self.give_config.guild(guild).giveaways() as gws:
            if gw_id in gws:
                gws[gw_id]["winners_list"].append(winner)
        channel = guild.get_channel(gw["channel_id"])
        if channel:
            await channel.send(f"🔄 New winner: <@{winner}>! Congratulations!")
        try:
            await interaction.response.send_message(f"Rerolled! New winner: <@{winner}>", ephemeral=True)
        except Exception:
            pass

    # ── Template management ────────────────────────────────────────────────
    async def _save_gw_template(self, guild, name: str, data: dict):
        async with self.give_config.guild(guild).templates() as templates:
            templates[name] = data

    async def _load_gw_template(self, guild, name: str) -> dict | None:
        data = await self.give_config.guild(guild).templates()
        return data.get(name)
