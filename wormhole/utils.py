"""Utility helpers for Wormhole cog."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Optional

import discord

# ── Colour palette ──────────────────────────────────────────────────────────

COLOUR_OK = discord.Colour.from_rgb(87, 242, 135)  # green
COLOUR_WARN = discord.Colour.from_rgb(254, 231, 92)  # yellow
COLOUR_ERR = discord.Colour.from_rgb(237, 66, 69)  # red
COLOUR_INFO = discord.Colour.from_rgb(88, 101, 242)  # blurple
COLOUR_NEUTRAL = discord.Colour.from_rgb(114, 137, 218)  # light blurple


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
        bucket = self._buckets[key]
        # Purge old timestamps
        self._buckets[key] = [t for t in bucket if now - t < self.per]
        if len(self._buckets[key]) >= self.rate:
            return True
        self._buckets[key].append(now)
        return False

    def update(self, rate: int, per: float):
        self.rate = rate
        self.per = per


# ── Filter helpers ──────────────────────────────────────────────────────────

def check_filters(content: str, word_filters: list[str], regex_filters: list[str]) -> Optional[str]:
    """Return the first matched filter pattern, or None if clean."""
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


# ── Embed builders ──────────────────────────────────────────────────────────

def make_embed(
    title: str = "",
    description: str = "",
    colour: discord.Colour = COLOUR_INFO,
    **kwargs,
) -> discord.Embed:
    em = discord.Embed(title=title, description=description, colour=colour, **kwargs)
    return em


def ok_embed(description: str, title: str = "✅ Success") -> discord.Embed:
    return make_embed(title=title, description=description, colour=COLOUR_OK)


def err_embed(description: str, title: str = "❌ Error") -> discord.Embed:
    return make_embed(title=title, description=description, colour=COLOUR_ERR)


def warn_embed(description: str, title: str = "⚠️ Warning") -> discord.Embed:
    return make_embed(title=title, description=description, colour=COLOUR_WARN)


def info_embed(description: str, title: str = "ℹ️ Info") -> discord.Embed:
    return make_embed(title=title, description=description, colour=COLOUR_INFO)


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
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)
