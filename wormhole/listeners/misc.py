"""Misc listeners — typing indicator sync, pin sync."""

from __future__ import annotations

import logging

import discord
from redbot.core import commands

log = logging.getLogger("red.evecogs.wormhole")


class MiscListener:
    """Mixin — typing and pin sync."""

    @commands.Cog.listener()
    async def on_typing(self, channel, user, when) -> None:
        await self._ready.wait()
        if user.bot or not hasattr(channel, "guild") or not channel.guild:
            return
        net = await self._net_for_ch(channel.id)
        if not net:
            return
        nd = await self._net(net)
        if not nd or not nd.get("sync_typing"):
            return
        for ch_id in nd["channels"]:
            if ch_id == channel.id:
                continue
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.typing()
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel, last_pin) -> None:
        await self._ready.wait()
        if not hasattr(channel, "guild"):
            return
        net = await self._net_for_ch(channel.id)
        if not net:
            return
        nd = await self._net(net)
        if not nd or not nd.get("sync_pins"):
            return
        try:
            pins = await channel.pins()
            if not pins:
                return
            latest = pins[0]
            mapping = self.msg_map.get_relayed(net, latest.id)
            if not mapping:
                return
            for ch_id, mid in mapping.items():
                ch = self.bot.get_channel(ch_id)
                if not ch:
                    continue
                try:
                    m = await ch.fetch_message(mid)
                    await m.pin()
                except Exception:
                    pass
        except Exception:
            pass
