"""VoiceMeister — shared utilities, embed builders, helpers."""

from __future__ import annotations

import datetime
from typing import Optional

import discord


# ── Colour palette ─────────────────────────────────────────────────────────
class Clr:
    PRIMARY = discord.Colour(0x5865F2)    # blurple
    SUCCESS = discord.Colour(0x57F287)    # green
    WARNING = discord.Colour(0xFEE75C)    # yellow
    ERROR = discord.Colour(0xED4245)      # red
    INFO = discord.Colour(0x3498DB)       # light blue
    VOICE = discord.Colour(0x9B59B6)      # purple — main theme
    PANEL = discord.Colour(0x2F3136)      # dark — panel background


# ── Quick embeds ───────────────────────────────────────────────────────────
def ok_embed(desc: str, *, title: str | None = None) -> discord.Embed:
    e = discord.Embed(description=f"✅ {desc}", colour=Clr.SUCCESS)
    if title:
        e.title = title
    return e


def err_embed(desc: str, *, title: str | None = None) -> discord.Embed:
    e = discord.Embed(description=f"❌ {desc}", colour=Clr.ERROR)
    if title:
        e.title = title
    return e


def info_embed(desc: str, *, title: str | None = None) -> discord.Embed:
    e = discord.Embed(description=desc, colour=Clr.INFO)
    if title:
        e.title = title
    return e


def warn_embed(desc: str, *, title: str | None = None) -> discord.Embed:
    e = discord.Embed(description=f"⚠️ {desc}", colour=Clr.WARNING)
    if title:
        e.title = title
    return e


# ── Timestamp helpers ──────────────────────────────────────────────────────
def ts_now() -> int:
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


def ts_relative(ts: int) -> str:
    return f"<t:{ts}:R>"


# ── Name template renderer ────────────────────────────────────────────────
def render_name(
    template: str,
    *,
    member: discord.Member,
    count: int = 1,
    custom: str = "",
) -> str:
    """Render a channel name template with variable substitution."""
    game = None
    for activity in member.activities:
        if activity.type == discord.ActivityType.playing:
            game = activity.name
            break

    name = template.replace("{user}", member.display_name)
    name = name.replace("{game}", game or "Chilling")
    name = name.replace("{count}", str(count))
    name = name.replace("{custom}", custom or member.display_name)

    # Discord channel name limit is 100 chars
    return name[:100]


# ── Permission helpers ─────────────────────────────────────────────────────
def is_channel_owner(member: discord.Member, owner_id: int) -> bool:
    return member.id == owner_id


def can_manage(member: discord.Member, owner_id: int) -> bool:
    """Check if member is channel owner or has Manage Channels."""
    return member.id == owner_id or member.guild_permissions.manage_channels


async def safe_send(dest, content=None, **kwargs) -> discord.Message | None:
    try:
        return await dest.send(content, **kwargs)
    except (discord.HTTPException, discord.Forbidden):
        return None


async def safe_dm(user: discord.User, content=None, **kwargs) -> discord.Message | None:
    try:
        return await user.send(content, **kwargs)
    except (discord.HTTPException, discord.Forbidden):
        return None


# ── Panel embed builder ───────────────────────────────────────────────────
def build_panel_embed(guild: discord.Guild) -> discord.Embed:
    """Build the main control panel embed."""
    embed = discord.Embed(
        title="🎙️ VoiceMeister — Channel Control Panel",
        description=(
            "Click any button below to manage your temporary voice channel.\n"
            "You must be *in* a VoiceMeister channel and be its *owner* (or have Manage Channels).\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        colour=Clr.VOICE,
    )

    embed.add_field(
        name="🔐 Access Controls",
        value=(
            "🔒 **Lock** — Prevent others from joining\n"
            "🔓 **Unlock** — Allow anyone to join\n"
            "👻 **Ghost** — Hide + Lock combined\n"
            "👁️ **Reveal** — Unhide + Unlock combined\n"
            "👤 **Hide** — Make invisible in channel list\n"
            "👁️‍🗨️ **Unhide** — Make visible again"
        ),
        inline=True,
    )

    embed.add_field(
        name="👥 User Management",
        value=(
            "➕ **Permit** — Allow a specific user\n"
            "➖ **Reject** — Block a specific user\n"
            "👢 **Kick** — Kick a user from channel\n"
            "🔨 **Ban** — Permanently block a user\n"
            "🔇 **Mute All** — Server-mute everyone\n"
            "🔊 **Unmute All** — Remove server-mute"
        ),
        inline=True,
    )

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    embed.add_field(
        name="⚙️ Channel Settings",
        value=(
            "✏️ **Rename** — Change channel name\n"
            "👥 **Limit** — Set user limit (0 = ∞)\n"
            "📡 **Bitrate** — Change audio quality\n"
            "🌍 **Region** — Set voice region"
        ),
        inline=True,
    )

    embed.add_field(
        name="👑 Ownership",
        value=(
            "👑 **Claim** — Claim if owner left\n"
            "🔄 **Transfer** — Give ownership to another\n"
            "ℹ️ **Info** — View channel details\n"
            "🗑️ **Delete** — Destroy the channel"
        ),
        inline=True,
    )

    embed.set_footer(text="VoiceMeister v1.0.0 • Buttons persist across restarts")
    return embed


# ── Log embed builder ─────────────────────────────────────────────────────
def log_embed(
    action: str,
    *,
    member: discord.Member,
    channel: discord.VoiceChannel | None = None,
    detail: str = "",
) -> discord.Embed:
    """Build a log embed for voice actions."""
    embed = discord.Embed(
        description=f"**{action}**\n{detail}" if detail else f"**{action}**",
        colour=Clr.VOICE,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
    if channel:
        embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.set_footer(text=f"User ID: {member.id}")
    return embed
