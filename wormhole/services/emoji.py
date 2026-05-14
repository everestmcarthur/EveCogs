"""
Foreign emoji relay — resolve custom emojis the bot can't see.

Unknown emojis are replaced with ``:name:`` in text and their images
are downloaded from the CDN, then shown as embed thumbnails (~80×80 px)
via the ``attachment://`` scheme.
"""

from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from redbot.core.bot import Red

_CUSTOM_EMOJI_RE = re.compile(r"<(a?):(\w+):(\d+)>")
_EMOJI_IMAGE_LIMIT = 5  # max emoji thumbnails per message


async def resolve_foreign_emojis(
    bot: Red, content: str
) -> tuple[str, list[tuple[str, bytes]]]:
    """Replace unknown custom emojis with ``:name:`` and fetch small images.

    Returns ``(new_content, [(filename, image_bytes), ...])``.
    """
    unknown: list[tuple[str, int, str]] = []

    def _check(m: re.Match) -> str:
        animated, name, eid = m.group(1), m.group(2), int(m.group(3))
        if bot.get_emoji(eid):
            return m.group(0)
        ext = "gif" if animated else "png"
        unknown.append((name, eid, ext))
        return f":{name}:"

    new_content = _CUSTOM_EMOJI_RE.sub(_check, content)

    emoji_data: list[tuple[str, bytes]] = []
    if unknown:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            for name, eid, ext in unknown[:_EMOJI_IMAGE_LIMIT]:
                try:
                    url = f"https://cdn.discordapp.com/emojis/{eid}.{ext}?size=48"
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        if resp.status == 200:
                            emoji_data.append((f"{name}.{ext}", await resp.read()))
                except Exception:
                    pass

    return new_content, emoji_data


def build_emoji_embeds_and_files(
    emoji_data: list[tuple[str, bytes]],
) -> tuple[list[discord.Embed], list[discord.File]]:
    """Build embed-thumbnail pairs for foreign emoji images.

    Each unknown emoji gets a tiny embed whose thumbnail references the
    attached file via ``attachment://``.  Thumbnails render at ~80×80 px.
    """
    embeds: list[discord.Embed] = []
    files: list[discord.File] = []
    for fname, fdata in emoji_data:
        f = discord.File(io.BytesIO(fdata), filename=fname)
        em = discord.Embed()
        em.set_thumbnail(url=f"attachment://{fname}")
        files.append(f)
        embeds.append(em)
    return embeds, files
