"""VoiceMeister — Persistent views, buttons, modals, and select menus."""

from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

import discord
from discord import ui

from .utils import (
    Clr, ok_embed, err_embed, info_embed, warn_embed,
    is_channel_owner, can_manage, ts_relative, ts_now,
)

if TYPE_CHECKING:
    from .voicemeister import VoiceMeister


# ══════════════════════════════════════════════════════════════════════════════
# HELPER — get the cog + validate the interaction
# ══════════════════════════════════════════════════════════════════════════════

async def _get_context(interaction: discord.Interaction):
    """Return (cog, member, voice_channel, owner_id) or send error and return None tuple."""
    cog: VoiceMeister | None = interaction.client.get_cog("VoiceMeister")
    if cog is None:
        await interaction.response.send_message(
            embed=err_embed("VoiceMeister cog is not loaded."), ephemeral=True,
        )
        return None, None, None, None

    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            embed=err_embed("Could not resolve you as a guild member."), ephemeral=True,
        )
        return None, None, None, None

    vc = member.voice.channel if member.voice else None
    if vc is None:
        await interaction.response.send_message(
            embed=err_embed("You must be **in a voice channel** to use this."), ephemeral=True,
        )
        return None, None, None, None

    owner_id = cog.temp_channels.get(vc.id)
    if owner_id is None:
        await interaction.response.send_message(
            embed=err_embed("Your current voice channel is **not** a VoiceMeister channel."),
            ephemeral=True,
        )
        return None, None, None, None

    return cog, member, vc, owner_id


async def _require_owner(interaction: discord.Interaction):
    """Like _get_context but also requires ownership or Manage Channels."""
    cog, member, vc, owner_id = await _get_context(interaction)
    if cog is None:
        return None, None, None, None

    if not can_manage(member, owner_id):
        await interaction.response.send_message(
            embed=err_embed("Only the channel **owner** (or a moderator) can do this."),
            ephemeral=True,
        )
        return None, None, None, None

    return cog, member, vc, owner_id


# ══════════════════════════════════════════════════════════════════════════════
# MODALS
# ══════════════════════════════════════════════════════════════════════════════

class RenameModal(ui.Modal, title="✏️ Rename Channel"):
    new_name = ui.TextInput(
        label="New channel name",
        placeholder="e.g. Gaming Lounge",
        max_length=100,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return

        try:
            await vc.edit(name=str(self.new_name), reason=f"VoiceMeister: renamed by {member}")
            await interaction.response.send_message(
                embed=ok_embed(f"Channel renamed to **{self.new_name}**."), ephemeral=True,
            )
            await cog._log_action(vc.guild, "✏️ Channel Renamed", member=member, channel=vc,
                                  detail=f"New name: `{self.new_name}`")
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=err_embed(f"Failed to rename: {e}"), ephemeral=True,
            )


class LimitModal(ui.Modal, title="👥 Set User Limit"):
    limit = ui.TextInput(
        label="User limit (0 = unlimited)",
        placeholder="e.g. 5",
        max_length=3,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return

        try:
            val = int(str(self.limit))
            if val < 0 or val > 99:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                embed=err_embed("Enter a number between **0** and **99**."), ephemeral=True,
            )
            return

        try:
            await vc.edit(user_limit=val, reason=f"VoiceMeister: limit set by {member}")
            label = f"**{val}**" if val > 0 else "**unlimited**"
            await interaction.response.send_message(
                embed=ok_embed(f"User limit set to {label}."), ephemeral=True,
            )
            await cog._log_action(vc.guild, "👥 Limit Changed", member=member, channel=vc,
                                  detail=f"New limit: {label}")
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=err_embed(f"Failed to set limit: {e}"), ephemeral=True,
            )


class BitrateModal(ui.Modal, title="📡 Set Bitrate"):
    bitrate = ui.TextInput(
        label="Bitrate in kbps (8–384)",
        placeholder="e.g. 96",
        max_length=3,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return

        try:
            val = int(str(self.bitrate))
            max_br = interaction.guild.bitrate_limit // 1000
            if val < 8 or val > max_br:
                raise ValueError
        except (ValueError, AttributeError):
            max_br = interaction.guild.bitrate_limit // 1000 if interaction.guild else 96
            await interaction.response.send_message(
                embed=err_embed(f"Enter a number between **8** and **{max_br}** kbps."),
                ephemeral=True,
            )
            return

        try:
            await vc.edit(bitrate=val * 1000, reason=f"VoiceMeister: bitrate set by {member}")
            await interaction.response.send_message(
                embed=ok_embed(f"Bitrate set to **{val} kbps**."), ephemeral=True,
            )
            await cog._log_action(vc.guild, "📡 Bitrate Changed", member=member, channel=vc,
                                  detail=f"New bitrate: {val} kbps")
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=err_embed(f"Failed to set bitrate: {e}"), ephemeral=True,
            )


class RegionModal(ui.Modal, title="🌍 Set Voice Region"):
    region = ui.TextInput(
        label="Region (e.g. us-east, eu-west, auto)",
        placeholder="auto",
        max_length=30,
        style=discord.TextStyle.short,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return

        region_str = str(self.region).strip().lower() if self.region else ""
        rtc_region = None if region_str in ("auto", "") else region_str

        try:
            await vc.edit(rtc_region=rtc_region, reason=f"VoiceMeister: region set by {member}")
            label = rtc_region or "Automatic"
            await interaction.response.send_message(
                embed=ok_embed(f"Voice region set to **{label}**."), ephemeral=True,
            )
            await cog._log_action(vc.guild, "🌍 Region Changed", member=member, channel=vc,
                                  detail=f"New region: {label}")
        except discord.HTTPException as e:
            await interaction.response.send_message(
                embed=err_embed(f"Failed to set region: {e}"), ephemeral=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# USER SELECT MENUS (for Kick, Ban, Permit, Reject, Transfer)
# ══════════════════════════════════════════════════════════════════════════════

class UserActionView(ui.View):
    """Ephemeral view with a user select for a specific action."""

    def __init__(self, action: str):
        super().__init__(timeout=60)
        self.action = action
        select = UserActionSelect(action=action)
        self.add_item(select)


class UserActionSelect(ui.UserSelect):
    def __init__(self, action: str):
        labels = {
            "kick": "Select user to kick",
            "ban": "Select user to ban",
            "permit": "Select user to permit",
            "reject": "Select user to reject",
            "transfer": "Select new owner",
        }
        super().__init__(
            placeholder=labels.get(action, "Select a user"),
            min_values=1,
            max_values=1,
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return

        target = self.values[0]
        if not isinstance(target, discord.Member):
            target = interaction.guild.get_member(target.id)
        if target is None:
            await interaction.response.send_message(
                embed=err_embed("Could not find that member."), ephemeral=True,
            )
            return

        if target.id == member.id:
            await interaction.response.send_message(
                embed=err_embed("You can't target yourself."), ephemeral=True,
            )
            return

        if self.action == "kick":
            if target.voice and target.voice.channel == vc:
                await target.move_to(None, reason=f"VoiceMeister: kicked by {member}")
                await interaction.response.send_message(
                    embed=ok_embed(f"Kicked {target.mention} from the channel."), ephemeral=True,
                )
                await cog._log_action(vc.guild, "👢 User Kicked", member=member, channel=vc,
                                      detail=f"Target: {target} ({target.id})")
            else:
                await interaction.response.send_message(
                    embed=err_embed(f"{target.mention} is not in your channel."), ephemeral=True,
                )

        elif self.action == "ban":
            # Set permission override to deny connect
            await vc.set_permissions(target, connect=False, view_channel=False,
                                     reason=f"VoiceMeister: banned by {member}")
            # If they're in the channel, kick them
            if target.voice and target.voice.channel == vc:
                await target.move_to(None, reason=f"VoiceMeister: banned by {member}")
            # Save to persistent ban list
            await cog._add_channel_ban(vc.guild.id, vc.id, target.id)
            await interaction.response.send_message(
                embed=ok_embed(f"Banned {target.mention} from the channel."), ephemeral=True,
            )
            await cog._log_action(vc.guild, "🔨 User Banned", member=member, channel=vc,
                                  detail=f"Target: {target} ({target.id})")

        elif self.action == "permit":
            await vc.set_permissions(target, connect=True, view_channel=True,
                                     reason=f"VoiceMeister: permitted by {member}")
            await interaction.response.send_message(
                embed=ok_embed(f"Permitted {target.mention} to join the channel."), ephemeral=True,
            )
            await cog._log_action(vc.guild, "➕ User Permitted", member=member, channel=vc,
                                  detail=f"Target: {target} ({target.id})")

        elif self.action == "reject":
            await vc.set_permissions(target, connect=False,
                                     reason=f"VoiceMeister: rejected by {member}")
            if target.voice and target.voice.channel == vc:
                await target.move_to(None, reason=f"VoiceMeister: rejected by {member}")
            await interaction.response.send_message(
                embed=ok_embed(f"Rejected {target.mention} from the channel."), ephemeral=True,
            )
            await cog._log_action(vc.guild, "➖ User Rejected", member=member, channel=vc,
                                  detail=f"Target: {target} ({target.id})")

        elif self.action == "transfer":
            if target.voice and target.voice.channel == vc:
                cog.temp_channels[vc.id] = target.id
                await cog._save_temp_channels()
                await interaction.response.send_message(
                    embed=ok_embed(f"Ownership transferred to {target.mention}."), ephemeral=True,
                )
                await cog._log_action(vc.guild, "🔄 Ownership Transferred", member=member,
                                      channel=vc, detail=f"New owner: {target} ({target.id})")
            else:
                await interaction.response.send_message(
                    embed=err_embed(f"{target.mention} must be in the channel to receive ownership."),
                    ephemeral=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CONTROL PANEL — PERSISTENT VIEW
# ══════════════════════════════════════════════════════════════════════════════

class VoiceMeisterPanel(ui.View):
    """The main persistent control panel. All buttons use custom_ids so the
    view survives restarts. This is registered once in cog_load."""

    def __init__(self):
        super().__init__(timeout=None)

    # ── Row 1: Access Controls ─────────────────────────────────────────────

    @ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary,
               custom_id="vm:lock", row=0)
    async def lock_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        overwrite = vc.overwrites_for(vc.guild.default_role)
        overwrite.connect = False
        await vc.set_permissions(
            vc.guild.default_role, overwrite=overwrite,
            reason=f"VoiceMeister: locked by {member}",
        )
        await interaction.response.send_message(
            embed=ok_embed("Channel **locked** 🔒 — no one else can join."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "🔒 Channel Locked", member=member, channel=vc)

    @ui.button(label="Unlock", emoji="🔓", style=discord.ButtonStyle.secondary,
               custom_id="vm:unlock", row=0)
    async def unlock_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        overwrite = vc.overwrites_for(vc.guild.default_role)
        overwrite.connect = None
        await vc.set_permissions(
            vc.guild.default_role, overwrite=overwrite,
            reason=f"VoiceMeister: unlocked by {member}",
        )
        await interaction.response.send_message(
            embed=ok_embed("Channel **unlocked** 🔓 — anyone can join."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "🔓 Channel Unlocked", member=member, channel=vc)

    @ui.button(label="Ghost", emoji="👻", style=discord.ButtonStyle.secondary,
               custom_id="vm:ghost", row=0)
    async def ghost_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        overwrite = vc.overwrites_for(vc.guild.default_role)
        overwrite.connect = False
        overwrite.view_channel = False
        await vc.set_permissions(
            vc.guild.default_role, overwrite=overwrite,
            reason=f"VoiceMeister: ghosted by {member}",
        )
        await interaction.response.send_message(
            embed=ok_embed("Channel is now **ghosted** 👻 — hidden and locked."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "👻 Channel Ghosted", member=member, channel=vc)

    @ui.button(label="Reveal", emoji="👁️", style=discord.ButtonStyle.secondary,
               custom_id="vm:reveal", row=0)
    async def reveal_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        overwrite = vc.overwrites_for(vc.guild.default_role)
        overwrite.connect = None
        overwrite.view_channel = None
        await vc.set_permissions(
            vc.guild.default_role, overwrite=overwrite,
            reason=f"VoiceMeister: revealed by {member}",
        )
        await interaction.response.send_message(
            embed=ok_embed("Channel is now **revealed** 👁️ — visible and unlocked."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "👁️ Channel Revealed", member=member, channel=vc)

    @ui.button(label="Hide", emoji="👤", style=discord.ButtonStyle.secondary,
               custom_id="vm:hide", row=0)
    async def hide_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        overwrite = vc.overwrites_for(vc.guild.default_role)
        overwrite.view_channel = False
        await vc.set_permissions(
            vc.guild.default_role, overwrite=overwrite,
            reason=f"VoiceMeister: hidden by {member}",
        )
        await interaction.response.send_message(
            embed=ok_embed("Channel is now **hidden** 👤 — invisible to others."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "👤 Channel Hidden", member=member, channel=vc)

    # ── Row 2: User Management ─────────────────────────────────────────────

    @ui.button(label="Permit", emoji="➕", style=discord.ButtonStyle.success,
               custom_id="vm:permit", row=1)
    async def permit_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_message(
            embed=info_embed("Select a user to **permit** into your channel:"),
            view=UserActionView("permit"), ephemeral=True,
        )

    @ui.button(label="Reject", emoji="➖", style=discord.ButtonStyle.danger,
               custom_id="vm:reject", row=1)
    async def reject_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_message(
            embed=info_embed("Select a user to **reject** from your channel:"),
            view=UserActionView("reject"), ephemeral=True,
        )

    @ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.danger,
               custom_id="vm:kick", row=1)
    async def kick_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_message(
            embed=info_embed("Select a user to **kick** from your channel:"),
            view=UserActionView("kick"), ephemeral=True,
        )

    @ui.button(label="Ban", emoji="🔨", style=discord.ButtonStyle.danger,
               custom_id="vm:ban", row=1)
    async def ban_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_message(
            embed=info_embed("Select a user to **ban** from your channel:"),
            view=UserActionView("ban"), ephemeral=True,
        )

    @ui.button(label="Unhide", emoji="👁️‍🗨️", style=discord.ButtonStyle.secondary,
               custom_id="vm:unhide", row=1)
    async def unhide_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        overwrite = vc.overwrites_for(vc.guild.default_role)
        overwrite.view_channel = None
        await vc.set_permissions(
            vc.guild.default_role, overwrite=overwrite,
            reason=f"VoiceMeister: unhidden by {member}",
        )
        await interaction.response.send_message(
            embed=ok_embed("Channel is now **visible** 👁️‍🗨️."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "👁️‍🗨️ Channel Unhidden", member=member, channel=vc)

    # ── Row 3: Channel Settings ────────────────────────────────────────────

    @ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.primary,
               custom_id="vm:rename", row=2)
    async def rename_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_modal(RenameModal())

    @ui.button(label="Limit", emoji="👥", style=discord.ButtonStyle.primary,
               custom_id="vm:limit", row=2)
    async def limit_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_modal(LimitModal())

    @ui.button(label="Bitrate", emoji="📡", style=discord.ButtonStyle.primary,
               custom_id="vm:bitrate", row=2)
    async def bitrate_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_modal(BitrateModal())

    @ui.button(label="Region", emoji="🌍", style=discord.ButtonStyle.primary,
               custom_id="vm:region", row=2)
    async def region_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_modal(RegionModal())

    @ui.button(label="Mute All", emoji="🔇", style=discord.ButtonStyle.secondary,
               custom_id="vm:muteall", row=2)
    async def muteall_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        count = 0
        for m in vc.members:
            if m.id != member.id and not m.voice.mute:
                try:
                    await m.edit(mute=True, reason=f"VoiceMeister: muted by {member}")
                    count += 1
                except discord.HTTPException:
                    pass
        await interaction.response.send_message(
            embed=ok_embed(f"Server-muted **{count}** user(s) 🔇."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "🔇 All Muted", member=member, channel=vc,
                              detail=f"Muted {count} user(s)")

    # ── Row 4: Ownership & Meta ────────────────────────────────────────────

    @ui.button(label="Claim", emoji="👑", style=discord.ButtonStyle.success,
               custom_id="vm:claim", row=3)
    async def claim_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _get_context(interaction)
        if cog is None:
            return

        # Check if owner is still in the channel
        owner_in_channel = any(m.id == owner_id for m in vc.members)
        if owner_in_channel and member.id != owner_id:
            await interaction.response.send_message(
                embed=err_embed("The channel owner is still in the channel. You can't claim it."),
                ephemeral=True,
            )
            return

        if member.id == owner_id:
            await interaction.response.send_message(
                embed=info_embed("You already own this channel."), ephemeral=True,
            )
            return

        cog.temp_channels[vc.id] = member.id
        await cog._save_temp_channels()
        await interaction.response.send_message(
            embed=ok_embed(f"You are now the **owner** of this channel 👑."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "👑 Channel Claimed", member=member, channel=vc)

    @ui.button(label="Transfer", emoji="🔄", style=discord.ButtonStyle.success,
               custom_id="vm:transfer", row=3)
    async def transfer_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        await interaction.response.send_message(
            embed=info_embed("Select the user to **transfer ownership** to:"),
            view=UserActionView("transfer"), ephemeral=True,
        )

    @ui.button(label="Info", emoji="ℹ️", style=discord.ButtonStyle.secondary,
               custom_id="vm:info", row=3)
    async def info_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _get_context(interaction)
        if cog is None:
            return

        owner = vc.guild.get_member(owner_id)
        owner_str = owner.mention if owner else f"Unknown (`{owner_id}`)"

        # Channel state
        overwrites = vc.overwrites_for(vc.guild.default_role)
        locked = overwrites.connect is False
        hidden = overwrites.view_channel is False

        status_parts = []
        if locked:
            status_parts.append("🔒 Locked")
        else:
            status_parts.append("🔓 Unlocked")
        if hidden:
            status_parts.append("👤 Hidden")
        else:
            status_parts.append("👁️ Visible")

        embed = discord.Embed(
            title=f"ℹ️ {vc.name}",
            colour=Clr.VOICE,
        )
        embed.add_field(name="👑 Owner", value=owner_str, inline=True)
        embed.add_field(name="👥 Members", value=f"{len(vc.members)}/{vc.user_limit or '∞'}",
                        inline=True)
        embed.add_field(name="📡 Bitrate", value=f"{vc.bitrate // 1000} kbps", inline=True)
        embed.add_field(name="🔐 Status", value=" • ".join(status_parts), inline=False)
        embed.add_field(name="🌍 Region", value=vc.rtc_region or "Automatic", inline=True)
        embed.add_field(name="📅 Created", value=f"<t:{int(vc.created_at.timestamp())}:R>",
                        inline=True)

        # List permitted/rejected users
        permitted = []
        rejected = []
        for target, overwrite in vc.overwrites.items():
            if isinstance(target, (discord.Member, discord.User)):
                if target.id == owner_id:
                    continue
                if overwrite.connect is True:
                    permitted.append(target.mention)
                elif overwrite.connect is False:
                    rejected.append(target.mention)

        if permitted:
            embed.add_field(name="✅ Permitted", value=", ".join(permitted[:10]), inline=False)
        if rejected:
            embed.add_field(name="🚫 Rejected/Banned", value=", ".join(rejected[:10]), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Unmute All", emoji="🔊", style=discord.ButtonStyle.secondary,
               custom_id="vm:unmuteall", row=3)
    async def unmuteall_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return
        count = 0
        for m in vc.members:
            if m.voice.mute:
                try:
                    await m.edit(mute=False, reason=f"VoiceMeister: unmuted by {member}")
                    count += 1
                except discord.HTTPException:
                    pass
        await interaction.response.send_message(
            embed=ok_embed(f"Unmuted **{count}** user(s) 🔊."), ephemeral=True,
        )
        await cog._log_action(vc.guild, "🔊 All Unmuted", member=member, channel=vc,
                              detail=f"Unmuted {count} user(s)")

    # ── Row 4 continued ───────────────────────────────────────────────────

    @ui.button(label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger,
               custom_id="vm:delete", row=4)
    async def delete_btn(self, interaction: discord.Interaction, button: ui.Button):
        cog, member, vc, owner_id = await _require_owner(interaction)
        if cog is None:
            return

        # Confirmation
        confirm_view = DeleteConfirmView(member.id, vc.id)
        await interaction.response.send_message(
            embed=warn_embed(f"Are you sure you want to **delete** `{vc.name}`? This cannot be undone."),
            view=confirm_view, ephemeral=True,
        )


class DeleteConfirmView(ui.View):
    def __init__(self, author_id: int, channel_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your confirmation.", ephemeral=True)
            return False
        return True

    @ui.button(label="Yes, Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        cog: VoiceMeister | None = interaction.client.get_cog("VoiceMeister")
        channel = interaction.guild.get_channel(self.channel_id)
        if channel and cog:
            await cog._log_action(interaction.guild, "🗑️ Channel Deleted",
                                  member=interaction.user, channel=channel)
            cog.temp_channels.pop(channel.id, None)
            await cog._save_temp_channels()
            try:
                await channel.delete(reason=f"VoiceMeister: deleted by {interaction.user}")
            except discord.HTTPException:
                pass
        await interaction.response.edit_message(
            embed=ok_embed("Channel deleted."), view=None,
        )
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.edit_message(
            embed=info_embed("Deletion cancelled."), view=None,
        )
        self.stop()
