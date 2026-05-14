"""
Sync listeners — edit, delete, reaction add/remove, starboard, karma.
"""

from __future__ import annotations

import logging

import discord
from redbot.core import commands

from ..utils import build_star_embed, truncate, warn_embed

log = logging.getLogger("red.evecogs.wormhole")


class SyncListener:
    """Mixin — edit/delete/reaction sync listeners."""

    # ── Edit sync ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        await self._ready.wait()
        if not after.guild or after.author.bot or before.content == after.content:
            return
        eff = after.channel.id
        if isinstance(after.channel, discord.Thread):
            eff = after.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net:
            return
        nd = await self._net(net)
        if not nd or not nd.get("sync_edits"):
            return
        mapping = self.msg_map.get_relayed(net, after.id)
        if not mapping:
            return
        mode = nd.get("relay_mode", "webhook")
        for ch_id, mid in mapping.items():
            ch = self.bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                cm = self._get_override(nd, ch_id, "relay_mode") or mode
                if cm == "webhook":
                    wh = await self._wh(ch)
                    await wh.edit_message(mid, content=after.content or "")
                elif cm == "embed":
                    msg = await ch.fetch_message(mid)
                    if msg.embeds:
                        e = msg.embeds[0]
                        e.description = after.content or "*[no text]*"
                        await msg.edit(embed=e)
                else:
                    msg = await ch.fetch_message(mid)
                    cp = msg.content.find(":** ")
                    if cp != -1:
                        await msg.edit(content=truncate(msg.content[: cp + 4] + after.content, 2000))
            except Exception:
                pass

    # ── Delete sync ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        await self._ready.wait()
        if not message.guild or message.author.bot:
            return
        eff = message.channel.id
        if isinstance(message.channel, discord.Thread):
            eff = message.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net:
            return
        nd = await self._net(net)
        if not nd or not nd.get("sync_deletes"):
            return
        mapping = self.msg_map.get_relayed(net, message.id)
        if not mapping:
            return
        mode = nd.get("relay_mode", "webhook")
        for ch_id, mid in mapping.items():
            ch = self.bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                cm = self._get_override(nd, ch_id, "relay_mode") or mode
                if cm == "webhook":
                    wh = await self._wh(ch)
                    await wh.delete_message(mid)
                else:
                    msg = await ch.fetch_message(mid)
                    await msg.delete()
            except Exception:
                pass

    # ── Reaction add — sync + karma + starboard ───────────────────────────

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        await self._ready.wait()
        if user.bot:
            return
        msg = reaction.message
        if not msg.guild:
            return
        eff = msg.channel.id
        if isinstance(msg.channel, discord.Thread):
            eff = msg.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net:
            return
        nd = await self._net(net)
        if not nd:
            return

        # Reaction sync
        if nd.get("sync_reactions"):
            mapping = self.msg_map.get_relayed(net, msg.id)
            if mapping:
                for ch_id, mid in mapping.items():
                    ch = self.bot.get_channel(ch_id)
                    if not ch:
                        continue
                    try:
                        rm = await ch.fetch_message(mid)
                        await rm.add_reaction(reaction.emoji)
                    except Exception:
                        pass

        # Karma
        if nd.get("karma_enabled") and str(reaction.emoji) == nd.get("karma_emoji", "👍"):
            target_msg = msg
            if target_msg.author.id != user.id:
                uid = str(target_msg.author.id)
                async with self.config.networks() as ns:
                    if net in ns:
                        ns[net].setdefault("karma_scores", {})
                        ns[net]["karma_scores"][uid] = ns[net]["karma_scores"].get(uid, 0) + 1

        # Starboard
        if nd.get("starboard_enabled") and str(reaction.emoji) == "⭐":
            threshold = nd.get("starboard_threshold", 3)
            star_ch_id = nd.get("starboard_channel")
            if not star_ch_id:
                return
            star_ch = self.bot.get_channel(star_ch_id)
            if not star_ch:
                return

            total_stars = 0
            for r in msg.reactions:
                if str(r.emoji) == "⭐":
                    total_stars += r.count

            if total_stars >= threshold:
                starred = nd.get("starred_messages", {})
                msg_key = str(msg.id)
                img_url = None
                if msg.attachments:
                    for a in msg.attachments:
                        if a.content_type and a.content_type.startswith("image/"):
                            img_url = a.url
                            break
                em = build_star_embed(
                    msg.author.display_name,
                    msg.author.display_avatar.url,
                    msg.content or "*[no text]*",
                    total_stars,
                    msg.guild.name,
                    msg.channel.name,
                    img_url,
                )

                if msg_key in starred:
                    try:
                        board_msg = await star_ch.fetch_message(starred[msg_key]["board_msg_id"])
                        await board_msg.edit(embed=em)
                        async with self.config.networks() as ns:
                            if net in ns:
                                ns[net]["starred_messages"][msg_key]["stars"] = total_stars
                    except Exception:
                        pass
                else:
                    try:
                        board_msg = await star_ch.send(embed=em)
                        async with self.config.networks() as ns:
                            if net in ns:
                                ns[net].setdefault("starred_messages", {})[msg_key] = {
                                    "stars": total_stars,
                                    "board_msg_id": board_msg.id,
                                }
                    except Exception:
                        pass

    # ── Reaction remove sync ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User) -> None:
        await self._ready.wait()
        if user.bot:
            return
        msg = reaction.message
        if not msg.guild:
            return
        eff = msg.channel.id
        if isinstance(msg.channel, discord.Thread):
            eff = msg.channel.parent_id
        net = await self._net_for_ch(eff)
        if not net:
            return
        nd = await self._net(net)
        if not nd or not nd.get("sync_reactions"):
            return
        mapping = self.msg_map.get_relayed(net, msg.id)
        if not mapping:
            return
        for ch_id, mid in mapping.items():
            ch = self.bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                rm = await ch.fetch_message(mid)
                await rm.remove_reaction(reaction.emoji, self.bot.user)
            except Exception:
                pass
