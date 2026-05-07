"""NexusCore — Reaction roles with buttons, select menus, reactions, exclusive groups, requirements."""

from __future__ import annotations

import datetime
from typing import Optional

import discord
from redbot.core import Config, commands

from .utils import (
    Clr, ok_embed, err_embed, info_embed, short_id, ts_now,
    safe_send, safe_dm,
)

# ── Defaults ───────────────────────────────────────────────────────────────
RR_DEFAULTS_GUILD = {
    "enabled": True,
    "panels": {},
    # panel_id -> {
    #   channel_id, message_id, title, description, colour, image, thumbnail,
    #   mode: "button" | "select" | "reaction",
    #   roles: [{role_id, label, emoji, description, style, group, required_role, blacklisted_role}],
    #   exclusive_groups: {group_name: max_picks},
    #   max_roles: 0,  # 0 = unlimited
    #   dm_confirm: True,
    #   require_role: None,
    #   blacklist_role: None,
    #   sticky: False,
    #   temp_minutes: 0,
    # }
    "log_channel": None,
    "dm_confirm": True,
}


# ── Dynamic view builders ─────────────────────────────────────────────────
def build_button_view(cog, panel_id: str, panel_data: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)

    for i, role_entry in enumerate(panel_data.get("roles", [])[:25]):
        style_map = {
            "primary": discord.ButtonStyle.primary,
            "secondary": discord.ButtonStyle.secondary,
            "success": discord.ButtonStyle.success,
            "danger": discord.ButtonStyle.danger,
        }
        style = style_map.get(role_entry.get("style", "primary"), discord.ButtonStyle.primary)
        emoji = role_entry.get("emoji")

        button = discord.ui.Button(
            label=role_entry.get("label", "Role"),
            style=style,
            emoji=emoji,
            custom_id=f"nexus_rr_{panel_id}_{i}",
        )

        async def callback(interaction, idx=i, pid=panel_id):
            await cog._handle_role_toggle(interaction, pid, idx)
        button.callback = callback
        view.add_item(button)

    return view


def build_select_view(cog, panel_id: str, panel_data: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    max_roles = panel_data.get("max_roles", 0)

    options = []
    for i, role_entry in enumerate(panel_data.get("roles", [])[:25]):
        options.append(discord.SelectOption(
            label=role_entry.get("label", "Role"),
            value=str(i),
            description=(role_entry.get("description", "") or "")[:100],
            emoji=role_entry.get("emoji"),
        ))

    select = discord.ui.Select(
        placeholder="Select roles...",
        options=options,
        min_values=0,
        max_values=min(len(options), max_roles) if max_roles else len(options),
        custom_id=f"nexus_rr_sel_{panel_id}",
    )

    async def callback(interaction):
        await cog._handle_select_roles(interaction, panel_id, [int(v) for v in select.values])
    select.callback = callback
    view.add_item(select)
    return view


# ── Mixin ──────────────────────────────────────────────────────────────────
class ReactionRolesMixin:
    """Reaction roles mixin."""

    def _init_reaction_roles(self, bot):
        self.rr_config = Config.get_conf(
            None, identifier=900004, cog_name="NexusCoreRR"
        )
        self.rr_config.register_guild(**RR_DEFAULTS_GUILD)
        self._rr_views = {}  # panel_id -> View
        self._rr_temp_tasks = {}  # (user_id, role_id) -> asyncio.Task
        self.bot = bot

    async def _load_rr_panels(self):
        """Re-register persistent views on cog load."""
        all_guilds = await self.rr_config.all_guilds()
        for guild_id, gdata in all_guilds.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            for panel_id, panel in gdata.get("panels", {}).items():
                mode = panel.get("mode", "button")
                if mode == "button":
                    view = build_button_view(self, panel_id, panel)
                elif mode == "select":
                    view = build_select_view(self, panel_id, panel)
                else:
                    continue
                self._rr_views[panel_id] = view
                self.bot.add_view(view, message_id=panel.get("message_id"))

    async def _create_rr_panel(
        self, ctx: commands.Context, channel: discord.TextChannel,
        title: str, description: str, mode: str, colour: discord.Colour | None = None,
        image: str | None = None, thumbnail: str | None = None,
    ) -> str:
        panel_id = short_id(10)
        panel_data = {
            "channel_id": channel.id,
            "message_id": None,
            "title": title,
            "description": description,
            "colour": (colour or Clr.ROLES).value,
            "image": image,
            "thumbnail": thumbnail,
            "mode": mode,
            "roles": [],
            "exclusive_groups": {},
            "max_roles": 0,
            "dm_confirm": True,
            "require_role": None,
            "blacklist_role": None,
            "sticky": False,
            "temp_minutes": 0,
        }

        embed = discord.Embed(
            title=title, description=description,
            colour=colour or Clr.ROLES,
        )
        if image:
            embed.set_image(url=image)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text="Select your roles below")

        msg = await channel.send(embed=embed)
        panel_data["message_id"] = msg.id

        async with self.rr_config.guild(ctx.guild).panels() as panels:
            panels[panel_id] = panel_data

        return panel_id

    async def _add_role_to_panel(
        self, guild: discord.Guild, panel_id: str,
        role: discord.Role, label: str | None = None, emoji: str | None = None,
        description: str | None = None, style: str = "primary",
        group: str | None = None, required_role: int | None = None,
        blacklisted_role: int | None = None,
    ):
        async with self.rr_config.guild(guild).panels() as panels:
            panel = panels.get(panel_id)
            if not panel:
                return False

            panel["roles"].append({
                "role_id": role.id,
                "label": label or role.name,
                "emoji": emoji,
                "description": description,
                "style": style,
                "group": group,
                "required_role": required_role,
                "blacklisted_role": blacklisted_role,
            })
            panels[panel_id] = panel

        await self._refresh_rr_panel(guild, panel_id)
        return True

    async def _refresh_rr_panel(self, guild: discord.Guild, panel_id: str):
        data = await self.rr_config.guild(guild).panels()
        panel = data.get(panel_id)
        if not panel:
            return

        channel = guild.get_channel(panel["channel_id"])
        if not channel:
            return

        mode = panel.get("mode", "button")
        if mode == "button":
            view = build_button_view(self, panel_id, panel)
        elif mode == "select":
            view = build_select_view(self, panel_id, panel)
        else:
            view = None

        if view:
            self._rr_views[panel_id] = view
            self.bot.add_view(view, message_id=panel.get("message_id"))

        embed = discord.Embed(
            title=panel["title"],
            description=panel["description"],
            colour=discord.Colour(panel["colour"]),
        )
        if panel.get("image"):
            embed.set_image(url=panel["image"])
        if panel.get("thumbnail"):
            embed.set_thumbnail(url=panel["thumbnail"])

        role_lines = []
        for r in panel.get("roles", []):
            emoji_str = f"{r['emoji']} " if r.get("emoji") else ""
            role = guild.get_role(r["role_id"])
            role_mention = role.mention if role else f"<@&{r['role_id']}>"
            role_lines.append(f"{emoji_str}{role_mention} — {r.get('description', r.get('label', ''))}")

        if role_lines:
            embed.add_field(name="Available Roles", value="\n".join(role_lines), inline=False)

        embed.set_footer(text="Select your roles below")

        try:
            msg = await channel.fetch_message(panel["message_id"])
            await msg.edit(embed=embed, view=view)
        except discord.HTTPException:
            pass

    async def _handle_role_toggle(self, interaction: discord.Interaction, panel_id: str, role_idx: int):
        guild = interaction.guild
        member = interaction.user
        data = await self.rr_config.guild(guild).panels()
        panel = data.get(panel_id)
        if not panel:
            return await interaction.response.send_message("Panel not found.", ephemeral=True)

        roles_list = panel.get("roles", [])
        if role_idx >= len(roles_list):
            return await interaction.response.send_message("Role not found.", ephemeral=True)

        role_entry = roles_list[role_idx]
        role = guild.get_role(role_entry["role_id"])
        if not role:
            return await interaction.response.send_message("Role no longer exists.", ephemeral=True)

        # Requirement checks
        if panel.get("require_role"):
            req = guild.get_role(panel["require_role"])
            if req and req not in member.roles:
                return await interaction.response.send_message(f"You need {req.mention} first.", ephemeral=True)

        if panel.get("blacklist_role"):
            bl = guild.get_role(panel["blacklist_role"])
            if bl and bl in member.roles:
                return await interaction.response.send_message(f"You can't use this with {bl.mention}.", ephemeral=True)

        if role_entry.get("required_role"):
            rr = guild.get_role(role_entry["required_role"])
            if rr and rr not in member.roles:
                return await interaction.response.send_message(f"You need {rr.mention} first.", ephemeral=True)

        if role_entry.get("blacklisted_role"):
            br = guild.get_role(role_entry["blacklisted_role"])
            if br and br in member.roles:
                return await interaction.response.send_message(f"Incompatible with {br.mention}.", ephemeral=True)

        try:
            if role in member.roles:
                if panel.get("sticky"):
                    return await interaction.response.send_message("This role is sticky and can't be removed.", ephemeral=True)
                await member.remove_roles(role, reason="NexusCore reaction roles")
                action = "removed"
                emoji = "➖"
            else:
                # Exclusive group check
                group = role_entry.get("group")
                if group and group in panel.get("exclusive_groups", {}):
                    max_picks = panel["exclusive_groups"][group]
                    group_roles = [r for r in roles_list if r.get("group") == group]
                    member_group_roles = [guild.get_role(r["role_id"]) for r in group_roles if guild.get_role(r["role_id"]) in member.roles]
                    if len(member_group_roles) >= max_picks:
                        for old_role in member_group_roles:
                            await member.remove_roles(old_role, reason="NexusCore exclusive group swap")

                # Max roles check
                if panel.get("max_roles", 0) > 0:
                    current_panel_roles = [guild.get_role(r["role_id"]) for r in roles_list if guild.get_role(r["role_id"]) in member.roles]
                    if len(current_panel_roles) >= panel["max_roles"]:
                        return await interaction.response.send_message(
                            f"Max {panel['max_roles']} roles from this panel.", ephemeral=True
                        )

                await member.add_roles(role, reason="NexusCore reaction roles")
                action = "added"
                emoji = "➕"

                # Temp role
                if panel.get("temp_minutes", 0) > 0:
                    import asyncio
                    async def remove_later():
                        await asyncio.sleep(panel["temp_minutes"] * 60)
                        try:
                            await member.remove_roles(role, reason="NexusCore temp role expired")
                        except discord.HTTPException:
                            pass
                    task = asyncio.create_task(remove_later())
                    self._rr_temp_tasks[(member.id, role.id)] = task

        except discord.Forbidden:
            return await interaction.response.send_message("I don't have permission to manage that role.", ephemeral=True)
        except discord.HTTPException:
            return await interaction.response.send_message("Failed to update role.", ephemeral=True)

        await interaction.response.send_message(f"{emoji} **{role.name}** {action}!", ephemeral=True)

        # DM confirm
        dm_confirm = panel.get("dm_confirm", True)
        if dm_confirm:
            await safe_dm(member, embed=discord.Embed(
                description=f"{emoji} Role **{role.name}** has been {action} in **{guild.name}**.",
                colour=Clr.ROLES,
            ))

        # Log
        log_ch_id = await self.rr_config.guild(guild).log_channel()
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)
            if log_ch:
                le = discord.Embed(
                    description=f"{emoji} {member.mention} — **{role.name}** {action}",
                    colour=Clr.ROLES,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                await safe_send(log_ch, embed=le)

    async def _handle_select_roles(self, interaction: discord.Interaction, panel_id: str, selected: list[int]):
        guild = interaction.guild
        member = interaction.user
        data = await self.rr_config.guild(guild).panels()
        panel = data.get(panel_id)
        if not panel:
            return await interaction.response.send_message("Panel not found.", ephemeral=True)

        roles_list = panel.get("roles", [])
        added, removed = [], []

        for i, role_entry in enumerate(roles_list):
            role = guild.get_role(role_entry["role_id"])
            if not role:
                continue
            if i in selected:
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason="NexusCore select roles")
                        added.append(role.name)
                    except discord.HTTPException:
                        pass
            else:
                if role in member.roles and not panel.get("sticky"):
                    try:
                        await member.remove_roles(role, reason="NexusCore select roles")
                        removed.append(role.name)
                    except discord.HTTPException:
                        pass

        parts = []
        if added:
            parts.append(f"➕ Added: {', '.join(added)}")
        if removed:
            parts.append(f"➖ Removed: {', '.join(removed)}")
        if not parts:
            parts.append("No changes.")

        await interaction.response.send_message("\n".join(parts), ephemeral=True)

    # ── Reaction-based handling (on_raw_reaction_add / remove) ─────────────
    async def _handle_reaction_add(self, payload: discord.RawReactionActionEvent):
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        data = await self.rr_config.guild(guild).panels()
        for panel_id, panel in data.items():
            if panel.get("mode") != "reaction":
                continue
            if panel.get("message_id") != payload.message_id:
                continue
            for role_entry in panel.get("roles", []):
                if str(payload.emoji) == role_entry.get("emoji") or payload.emoji.name == role_entry.get("emoji"):
                    role = guild.get_role(role_entry["role_id"])
                    member = guild.get_member(payload.user_id)
                    if role and member and not member.bot:
                        try:
                            await member.add_roles(role, reason="NexusCore reaction role")
                        except discord.HTTPException:
                            pass

    async def _handle_reaction_remove(self, payload: discord.RawReactionActionEvent):
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        data = await self.rr_config.guild(guild).panels()
        for panel_id, panel in data.items():
            if panel.get("mode") != "reaction":
                continue
            if panel.get("message_id") != payload.message_id:
                continue
            for role_entry in panel.get("roles", []):
                if str(payload.emoji) == role_entry.get("emoji") or payload.emoji.name == role_entry.get("emoji"):
                    role = guild.get_role(role_entry["role_id"])
                    member = guild.get_member(payload.user_id)
                    if role and member and not member.bot:
                        try:
                            await member.remove_roles(role, reason="NexusCore reaction role removed")
                        except discord.HTTPException:
                            pass
