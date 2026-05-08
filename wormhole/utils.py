"""
Utility helpers for Wormhole v3.2.0 — the ultimate cross-server relay cog.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import string
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import discord

# ── Colour palette ──────────────────────────────────────────────────────────

COLOUR_OK = discord.Colour.from_rgb(87, 242, 135)
COLOUR_WARN = discord.Colour.from_rgb(254, 231, 92)
COLOUR_ERR = discord.Colour.from_rgb(237, 66, 69)
COLOUR_INFO = discord.Colour.from_rgb(88, 101, 242)
COLOUR_NEUTRAL = discord.Colour.from_rgb(114, 137, 218)
COLOUR_ANNOUNCE = discord.Colour.from_rgb(255, 163, 26)
COLOUR_STAR = discord.Colour.from_rgb(255, 172, 51)
COLOUR_DM = discord.Colour.from_rgb(87, 165, 242)

_SERVER_COLOURS = [
    discord.Colour.from_rgb(231, 76, 60),
    discord.Colour.from_rgb(46, 204, 113),
    discord.Colour.from_rgb(52, 152, 219),
    discord.Colour.from_rgb(155, 89, 182),
    discord.Colour.from_rgb(241, 196, 15),
    discord.Colour.from_rgb(26, 188, 156),
    discord.Colour.from_rgb(230, 126, 34),
    discord.Colour.from_rgb(233, 30, 99),
    discord.Colour.from_rgb(0, 188, 212),
    discord.Colour.from_rgb(139, 195, 74),
    discord.Colour.from_rgb(255, 87, 34),
    discord.Colour.from_rgb(121, 85, 72),
]


def server_colour(guild_id: int) -> discord.Colour:
    return _SERVER_COLOURS[guild_id % len(_SERVER_COLOURS)]


# ── Cooldown bucket ────────────────────────────────────────────────────────

class CooldownBucket:
    """Per-user per-network token-bucket rate limiter."""

    def __init__(self, rate: int = 5, per: float = 10.0):
        self.rate = rate
        self.per = per
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(self, user_id: int, network: str) -> bool:
        key = f"{network}:{user_id}"
        now = time.monotonic()
        self._buckets[key] = [t for t in self._buckets[key] if now - t < self.per]
        if len(self._buckets[key]) >= self.rate:
            return True
        self._buckets[key].append(now)
        return False

    def update(self, rate: int, per: float):
        self.rate = rate
        self.per = per


# ── Filter helpers ──────────────────────────────────────────────────────────

def check_filters(content: str, word_filters: list[str], regex_filters: list[str]) -> Optional[str]:
    lowered = content.lower()
    for word in word_filters:
        if word.lower() in lowered:
            return word
    for pattern in regex_filters:
        try:
            if re.search(pattern, content, re.IGNORECASE):
                return pattern
        except re.error:
            continue
    return None


# ── Auto-moderation helpers ─────────────────────────────────────────────────

INVITE_PATTERN = re.compile(
    r"(discord\.gg|discord\.com/invite|discordapp\.com/invite|dsc\.gg)/[\w-]+",
    re.IGNORECASE,
)
LINK_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"<@!?\d+>|<@&\d+>|@everyone|@here")

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".scr", ".pif", ".msi", ".com",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".ps1",
}


def check_automod(content: str, automod_config: dict) -> Optional[str]:
    if not automod_config:
        return None
    if automod_config.get("anti_invite") and INVITE_PATTERN.search(content):
        return "Discord invite link detected"
    if automod_config.get("anti_link") and LINK_PATTERN.search(content):
        return "Link detected"
    if automod_config.get("anti_mention_spam"):
        max_mentions = automod_config.get("max_mentions", 5)
        if len(MENTION_PATTERN.findall(content)) > max_mentions:
            return f"Too many mentions"
    if automod_config.get("anti_caps"):
        threshold = automod_config.get("caps_threshold", 0.7)
        alpha = [c for c in content if c.isalpha()]
        if len(alpha) >= 10:
            ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
            if ratio >= threshold:
                return f"Excessive caps ({ratio:.0%})"
    if automod_config.get("anti_zalgo"):
        # Detect zalgo text (combining characters)
        combining = sum(1 for c in content if '\u0300' <= c <= '\u036f' or '\u0489' <= c <= '\u0489')
        if combining > 10:
            return "Zalgo text detected"
    if automod_config.get("anti_spoiler"):
        spoiler_count = content.count("||")
        if spoiler_count >= 6:  # 3+ spoiler blocks
            return "Excessive spoiler tags"
    if automod_config.get("anti_emote_spam"):
        max_emotes = automod_config.get("max_emotes", 10)
        emote_count = len(re.findall(r"<a?:\w+:\d+>", content))
        if emote_count > max_emotes:
            return f"Too many custom emotes ({emote_count})"
    if automod_config.get("anti_newline_spam"):
        max_newlines = automod_config.get("max_newlines", 15)
        if content.count("\n") > max_newlines:
            return "Too many newlines"
    return None


def check_attachment_filters(
    attachments: list,
    blocked_exts: Optional[set] = None,
    max_filesize: Optional[int] = None,
) -> Optional[str]:
    """Check attachments against extension and size filters."""
    exts = blocked_exts or set()
    for att in attachments:
        name_lower = att.filename.lower()
        for ext in exts:
            if name_lower.endswith(ext):
                return f"Blocked file type: {ext}"
        if max_filesize and att.size > max_filesize:
            mb = max_filesize / (1024 * 1024)
            return f"File too large (max {mb:.1f} MB)"
    return None


class DuplicateDetector:
    """Detects duplicate/spam messages per user per network."""

    def __init__(self, window: float = 30.0, threshold: int = 3):
        self.window = window
        self.threshold = threshold
        self._history: Dict[Tuple[str, int], List[Tuple[str, float]]] = defaultdict(list)

    def is_duplicate(self, network: str, user_id: int, content: str) -> bool:
        key = (network, user_id)
        now = time.monotonic()
        content_hash = hashlib.md5(content.lower().strip().encode()).hexdigest()
        self._history[key] = [(h, t) for h, t in self._history[key] if now - t < self.window]
        dup_count = sum(1 for h, _ in self._history[key] if h == content_hash)
        self._history[key].append((content_hash, now))
        if len(self._history[key]) > 50:
            self._history[key] = self._history[key][-25:]
        return dup_count >= self.threshold

    def update(self, window: float, threshold: int):
        self.window = window
        self.threshold = threshold


class RaidDetector:
    """Detects raid patterns: many new unique users posting in short window."""

    def __init__(self, window: float = 60.0, user_threshold: int = 10):
        self.window = window
        self.user_threshold = user_threshold
        # {network: [(user_id, timestamp), ...]}
        self._activity: Dict[str, List[Tuple[int, float]]] = defaultdict(list)

    def record(self, network: str, user_id: int) -> bool:
        """Record activity. Returns True if raid detected."""
        now = time.monotonic()
        self._activity[network] = [
            (uid, t) for uid, t in self._activity[network] if now - t < self.window
        ]
        self._activity[network].append((user_id, now))
        unique = len(set(uid for uid, _ in self._activity[network]))
        return unique >= self.user_threshold


# ── Invite code generation ──────────────────────────────────────────────────

def generate_invite_code(length: int = 8) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


# ── Mention sanitisation ───────────────────────────────────────────────────

def sanitise_mentions(content: str, config: dict) -> str:
    """Legacy mention control — kept for backwards compatibility."""
    if config.get("strip_everyone"):
        content = content.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")
    if config.get("strip_role_mentions"):
        content = re.sub(r"<@&(\d+)>", r"@role", content)
    if config.get("strip_user_mentions"):
        content = re.sub(r"<@!?(\d+)>", r"@user", content)
    return content


def apply_mention_policy(content: str, policy: dict, author_id: int, exempt_users: list) -> str:
    """Apply granular mention policy. If the user is exempt, mentions pass through."""
    if author_id in exempt_users:
        return content
    if not policy.get("allow_everyone", False):
        content = content.replace("@everyone", "@\u200beveryone")
    if not policy.get("allow_here", False):
        content = content.replace("@here", "@\u200bhere")
    if not policy.get("allow_role_mentions", False):
        content = re.sub(r"<@&(\d+)>", r"@\u200brole", content)
    if not policy.get("allow_user_mentions", True):
        content = re.sub(r"<@!?(\d+)>", r"@\u200buser", content)
    return content


# ── Embed builders ──────────────────────────────────────────────────────────

def make_embed(title: str = "", description: str = "", colour: discord.Colour = COLOUR_INFO, **kw) -> discord.Embed:
    return discord.Embed(title=title, description=description, colour=colour, **kw)

def ok_embed(desc: str, title: str = "✅ Success") -> discord.Embed:
    return make_embed(title=title, description=desc, colour=COLOUR_OK)

def err_embed(desc: str, title: str = "❌ Error") -> discord.Embed:
    return make_embed(title=title, description=desc, colour=COLOUR_ERR)

def warn_embed(desc: str, title: str = "⚠️ Warning") -> discord.Embed:
    return make_embed(title=title, description=desc, colour=COLOUR_WARN)

def info_embed(desc: str, title: str = "ℹ️ Info") -> discord.Embed:
    return make_embed(title=title, description=desc, colour=COLOUR_INFO)

def announce_embed(desc: str, title: str = "📢 Announcement") -> discord.Embed:
    return make_embed(title=title, description=desc, colour=COLOUR_ANNOUNCE)

def star_embed(desc: str, title: str = "⭐ Starred") -> discord.Embed:
    return make_embed(title=title, description=desc, colour=COLOUR_STAR)

def dm_embed(desc: str, title: str = "✉️ DM Relay") -> discord.Embed:
    return make_embed(title=title, description=desc, colour=COLOUR_DM)


# ── Embed relay builder ────────────────────────────────────────────────────

def build_relay_embed(
    message: discord.Message,
    server_nick: Optional[str] = None,
    net_colour: Optional[int] = None,
) -> discord.Embed:
    guild_label = server_nick or message.guild.name
    colour = discord.Colour(net_colour) if net_colour else server_colour(message.guild.id)

    em = discord.Embed(description=message.content or "*[no text]*", colour=colour, timestamp=message.created_at)
    em.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    if message.guild.icon:
        em.set_footer(text=f"🌐 {guild_label} • #{message.channel.name}", icon_url=message.guild.icon.url)
    else:
        em.set_footer(text=f"🌐 {guild_label} • #{message.channel.name}")

    if message.attachments:
        img_set = False
        file_lines = []
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/") and not img_set:
                em.set_image(url=att.url)
                img_set = True
            else:
                file_lines.append(f"[{att.filename}]({att.url})")
        if file_lines:
            em.add_field(name="📎 Attachments", value="\n".join(file_lines), inline=False)

    if message.stickers:
        em.add_field(name="🎨 Stickers", value=", ".join(f"[{s.name}]({s.url})" for s in message.stickers), inline=False)

    return em


def build_dm_relay_embed(
    user: discord.User,
    content: str,
    network_name: str,
) -> discord.Embed:
    """Build an embed for messages sent from DM to the network."""
    em = discord.Embed(description=content, colour=COLOUR_DM, timestamp=datetime.now(timezone.utc))
    em.set_author(name=f"{user.display_name} (via DM)", icon_url=user.display_avatar.url)
    em.set_footer(text=f"✉️ DM → {network_name}")
    return em


def build_dm_incoming_embed(
    author_name: str,
    author_avatar: str,
    server_name: str,
    channel_name: str,
    content: str,
    network_name: str,
    net_colour: Optional[int] = None,
) -> discord.Embed:
    """Build an embed for network messages forwarded to DM subscribers."""
    colour = discord.Colour(net_colour) if net_colour else COLOUR_INFO
    em = discord.Embed(description=content or "*[no text]*", colour=colour, timestamp=datetime.now(timezone.utc))
    em.set_author(name=author_name, icon_url=author_avatar)
    em.set_footer(text=f"🌐 {server_name} • #{channel_name} • {network_name}")
    return em


# ── Portal embed builder ───────────────────────────────────────────────────

def build_portal_embed(
    network_name: str, data: dict, channel_count: int, total_messages: int,
) -> discord.Embed:
    colour = discord.Colour(data["colour"]) if data.get("colour") else COLOUR_INFO
    desc = data.get("description") or "*A wormhole network.*"
    status = "❄️ Frozen" if data.get("frozen") else "🟢 Active"

    em = discord.Embed(title=f"🌀 Wormhole — {network_name}", description=desc, colour=colour)
    em.add_field(name="Status", value=status, inline=True)
    em.add_field(name="Channels", value=str(channel_count), inline=True)
    em.add_field(name="Messages", value=f"{total_messages:,}", inline=True)

    dm_count = len(data.get("dm_subscribers", []))
    if dm_count:
        em.add_field(name="DM Subscribers", value=str(dm_count), inline=True)

    features = []
    for key, label in [
        ("use_webhooks", "Webhooks"), ("sync_edits", "Edit sync"),
        ("sync_deletes", "Delete sync"), ("sync_reactions", "Reaction sync"),
        ("sync_replies", "Reply sync"), ("dm_enabled", "DM relay"),
    ]:
        if data.get(key):
            features.append(f"✅ {label}")
    if features:
        em.add_field(name="Features", value=" • ".join(features), inline=False)

    if data.get("motd"):
        em.add_field(name="📋 MOTD", value=data["motd"][:256], inline=False)
    if data.get("custom_icon"):
        em.set_thumbnail(url=data["custom_icon"])
    em.set_footer(text="Portal auto-updates • Wormhole v3.2.0")
    em.timestamp = datetime.now(timezone.utc)
    return em


# ── Starboard embed ────────────────────────────────────────────────────────

def build_star_embed(
    author_name: str,
    author_avatar: str,
    content: str,
    stars: int,
    server_name: str,
    channel_name: str,
    image_url: Optional[str] = None,
) -> discord.Embed:
    em = discord.Embed(description=content, colour=COLOUR_STAR, timestamp=datetime.now(timezone.utc))
    em.set_author(name=author_name, icon_url=author_avatar)
    em.add_field(name="⭐ Stars", value=str(stars), inline=True)
    em.set_footer(text=f"{server_name} • #{channel_name}")
    if image_url:
        em.set_image(url=image_url)
    return em


# ── Formatting helpers ──────────────────────────────────────────────────────

def truncate(text: str, length: int = 2000) -> str:
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."

def human_timedelta(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)

def compact_format(server_name: str, user_name: str, content: str) -> str:
    return truncate(f"**[{server_name}] {user_name}:** {content}", 2000)

def format_audit_entry(action: str, user: str, target: str = "", details: str = "") -> dict:
    """Create an audit log entry."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "user": user,
        "target": target,
        "details": details,
    }
