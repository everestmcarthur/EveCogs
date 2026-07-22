"""Settings commands — all `wh set` sub-commands for network configuration."""

from __future__ import annotations

from typing import Optional

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role
from ..utils import ok_embed, err_embed, info_embed, COLOUR_INFO, COLOUR_OK
from ._base import WormholeBase


class SettingsCommands(WormholeBase):
    """Mixin — network settings management."""

    # ── Relay mode ─────────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="relaymode")
    @requires_role(Role.ADMIN)
    async def wh_set_relaymode(self, ctx: commands.Context, name: str, mode: str) -> None:
        """Set relay mode: ``webhook``, ``embed``, or ``compact``."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if mode not in ("webhook", "embed", "compact"):
            return await ctx.send(embed=err_embed("Mode must be `webhook`, `embed`, or `compact`."))
        async with self.config.networks() as ns:
            ns[name]["relay_mode"] = mode
        await ctx.send(embed=ok_embed(f"Relay mode for `{name}` set to **{mode}**."))
        await self._audit(name, "set_relaymode", str(ctx.author), details=mode)
        await self._log(nd, info_embed(f"Relay mode changed to **{mode}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Webhooks ──────────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="webhooks")
    @requires_role(Role.ADMIN)
    async def wh_set_webhooks(self, ctx: commands.Context, name: str, enabled: bool) -> None:
        """Enable or disable webhook relay."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["use_webhooks"] = enabled
        await ctx.send(embed=ok_embed(f"Webhooks {'enabled' if enabled else 'disabled'} for `{name}`."))
        await self._audit(name, "set_webhooks", str(ctx.author), details=str(enabled))
        await self._log(nd, info_embed(f"Webhooks **{'enabled' if enabled else 'disabled'}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Sync toggles ──────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="sync")
    @requires_role(Role.ADMIN)
    async def wh_set_sync(self, ctx: commands.Context, name: str, feature: str, enabled: bool) -> None:
        """Toggle sync features: ``edits``, ``deletes``, ``reactions``, ``replies``, ``stickers``, ``pins``, ``threads``, ``typing``."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        key_map = {
            "edits": "sync_edits", "deletes": "sync_deletes",
            "reactions": "sync_reactions", "replies": "sync_replies",
            "stickers": "sync_stickers", "pins": "sync_pins",
            "threads": "sync_threads", "typing": "sync_typing",
        }
        if feature not in key_map:
            return await ctx.send(embed=err_embed(f"Unknown feature. Options: {', '.join(key_map)}"))
        async with self.config.networks() as ns:
            ns[name][key_map[feature]] = enabled
        await ctx.send(embed=ok_embed(f"`{feature}` sync {'enabled' if enabled else 'disabled'} for `{name}`."))
        await self._audit(name, f"set_{feature}", str(ctx.author), details=str(enabled))
        await self._log(nd, info_embed(f"`{feature}` sync **{'enabled' if enabled else 'disabled'}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Identity ──────────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="imagemode")
    @requires_role(Role.ADMIN)
    async def wh_set_imagemode(self, ctx: commands.Context, name: str, mode: str) -> None:
        """Set avatar mode: ``user``, ``server``, ``custom``."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if mode not in ("user", "server", "custom"):
            return await ctx.send(embed=err_embed("Mode must be `user`, `server`, or `custom`."))
        async with self.config.networks() as ns:
            ns[name]["image_mode"] = mode
        await ctx.send(embed=ok_embed(f"Image mode for `{name}` set to **{mode}**."))
        await self._log(nd, info_embed(f"Image mode set to **{mode}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="namemode")
    @requires_role(Role.ADMIN)
    async def wh_set_namemode(self, ctx: commands.Context, name: str, mode: str) -> None:
        """Set name mode: ``user``, ``server``, ``both``, ``custom``."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if mode not in ("user", "server", "both", "custom"):
            return await ctx.send(embed=err_embed("Mode must be `user`, `server`, `both`, or `custom`."))
        async with self.config.networks() as ns:
            ns[name]["name_mode"] = mode
        await ctx.send(embed=ok_embed(f"Name mode for `{name}` set to **{mode}**."))
        await self._log(nd, info_embed(f"Name mode set to **{mode}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="icon")
    @requires_role(Role.ADMIN)
    async def wh_set_icon(self, ctx: commands.Context, name: str, url: str = None) -> None:
        """Set a custom network icon URL."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["custom_icon"] = url
        await ctx.send(embed=ok_embed(f"Custom icon {'set' if url else 'cleared'} for `{name}`."))
        await self._log(nd, info_embed(f"Custom icon **{'set' if url else 'cleared'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="customname")
    @requires_role(Role.ADMIN)
    async def wh_set_customname(self, ctx: commands.Context, name: str, *, value: str = None) -> None:
        """Set a custom display name for relayed messages."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["custom_name"] = value
        await ctx.send(embed=ok_embed(f"Custom name {'set' if value else 'cleared'} for `{name}`."))
        await self._log(nd, info_embed(f"Custom name **{'set' if value else 'cleared'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="colour", aliases=["color"])
    @requires_role(Role.ADMIN)
    async def wh_set_colour(self, ctx: commands.Context, name: str, hex_code: str = None) -> None:
        """Set the network embed colour (hex, e.g. ``#ff5733``)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if hex_code:
            try:
                colour = int(hex_code.lstrip("#"), 16)
            except ValueError:
                return await ctx.send(embed=err_embed("Invalid hex colour."))
        else:
            colour = None
        async with self.config.networks() as ns:
            ns[name]["colour"] = colour
        await ctx.send(embed=ok_embed(f"Colour {'set' if colour else 'cleared'} for `{name}`."))
        await self._log(nd, info_embed(f"Colour **{'set' if colour else 'cleared'}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Description / MOTD / rules ─────────────────────────────────────────

    @WormholeBase.wh_set.command(name="description", aliases=["desc"])
    @requires_role(Role.ADMIN)
    async def wh_set_desc(self, ctx: commands.Context, name: str, *, text: str) -> None:
        """Set the network description."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["description"] = text
        await ctx.send(embed=ok_embed(f"Description updated for `{name}`."))
        await self._log(nd, info_embed(f"Description updated by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="motd")
    @requires_role(Role.ADMIN)
    async def wh_set_motd(self, ctx: commands.Context, name: str, *, text: str = "") -> None:
        """Set or clear the Message of the Day."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["motd"] = text
        await ctx.send(embed=ok_embed(f"MOTD {'set' if text else 'cleared'} for `{name}`."))
        await self._log(nd, info_embed(f"MOTD **{'set' if text else 'cleared'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="welcome")
    @requires_role(Role.ADMIN)
    async def wh_set_welcome(self, ctx: commands.Context, name: str, *, text: str = "") -> None:
        """Set or clear the welcome message for new servers."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["welcome_message"] = text
        await ctx.send(embed=ok_embed(f"Welcome message {'set' if text else 'cleared'} for `{name}`."))
        await self._log(nd, info_embed(f"Welcome message **{'set' if text else 'cleared'}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Network behaviour ──────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="freeze")
    @requires_role(Role.ADMIN)
    async def wh_set_freeze(self, ctx: commands.Context, name: str) -> None:
        """Freeze the network — relay paused."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["frozen"] = True
        await ctx.send(embed=ok_embed(f"`{name}` is now ❄️ frozen. Messages won't relay."))
        await self._audit(name, "freeze", str(ctx.author))
        await self._log(nd, info_embed(f"Network frozen by {ctx.author}", title="❄️ Network Frozen"))

    @WormholeBase.wh_set.command(name="unfreeze")
    @requires_role(Role.ADMIN)
    async def wh_set_unfreeze(self, ctx: commands.Context, name: str) -> None:
        """Unfreeze the network — resume relay."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["frozen"] = False
        await ctx.send(embed=ok_embed(f"`{name}` is now 🟢 active."))
        await self._audit(name, "unfreeze", str(ctx.author))
        await self._log(nd, info_embed(f"Network unfrozen by {ctx.author}", title="🟢 Network Active"))

    @WormholeBase.wh_set.command(name="anonymous", aliases=["anon"])
    @requires_role(Role.ADMIN)
    async def wh_set_anonymous(self, ctx: commands.Context, name: str, enabled: bool) -> None:
        """Toggle anonymous mode."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        import secrets
        async with self.config.networks() as ns:
            ns[name]["anonymous"] = enabled
            if enabled and not ns[name].get("anon_salt"):
                ns[name]["anon_salt"] = secrets.token_hex(8)
        await ctx.send(embed=ok_embed(f"Anonymous mode {'enabled' if enabled else 'disabled'} for `{name}`."))
        await self._log(nd, info_embed(f"Anonymous mode **{'enabled' if enabled else 'disabled'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="nsfw")
    @requires_role(Role.ADMIN)
    async def wh_set_nsfw(self, ctx: commands.Context, name: str, gate: bool) -> None:
        """Toggle NSFW gate (only relay to NSFW channels if source is NSFW)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["nsfw_gate"] = gate
        await ctx.send(embed=ok_embed(f"NSFW gate {'enabled' if gate else 'disabled'} for `{name}`."))
        await self._log(nd, info_embed(f"NSFW gate **{'enabled' if gate else 'disabled'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="mediaonly")
    @requires_role(Role.ADMIN)
    async def wh_set_mediaonly(self, ctx: commands.Context, name: str, enabled: bool) -> None:
        """Toggle media-only mode (only relay messages with attachments)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["media_only"] = enabled
        await ctx.send(embed=ok_embed(f"Media-only mode {'enabled' if enabled else 'disabled'} for `{name}`."))
        await self._log(nd, info_embed(f"Media-only mode **{'enabled' if enabled else 'disabled'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="silent")
    @requires_role(Role.ADMIN)
    async def wh_set_silent(self, ctx: commands.Context, name: str, enabled: bool) -> None:
        """Toggle silent mode (suppress status messages)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["silent"] = enabled
        await ctx.send(embed=ok_embed(f"Silent mode {'enabled' if enabled else 'disabled'} for `{name}`."))
        await self._log(nd, info_embed(f"Silent mode **{'enabled' if enabled else 'disabled'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="embeds")
    @requires_role(Role.ADMIN)
    async def wh_set_embeds(self, ctx: commands.Context, name: str, enabled: bool) -> None:
        """Toggle forwarding embeds from relayed messages."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["forward_embeds"] = enabled
        await ctx.send(embed=ok_embed(f"Embed forwarding {'enabled' if enabled else 'disabled'} for `{name}`."))
        await self._log(nd, info_embed(f"Embed forwarding **{'enabled' if enabled else 'disabled'}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Rate limiting ──────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="ratelimit")
    @requires_role(Role.ADMIN)
    async def wh_set_ratelimit(self, ctx: commands.Context, name: str, rate: int = 5, per: float = 10.0) -> None:
        """Set rate limit: *rate* messages per *per* seconds."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["rate_limit_rate"] = rate
            ns[name]["rate_limit_per"] = per
        if name in self.cooldowns:
            self.cooldowns[name].update(rate, per)
        else:
            from ..utils import CooldownBucket
            self.cooldowns[name] = CooldownBucket(rate, per)
        await ctx.send(embed=ok_embed(f"Rate limit: {rate} msgs per {per}s for `{name}`."))
        await self._log(nd, info_embed(f"Rate limit set to **{rate}** msgs/**{per}**s by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="slowmode")
    @requires_role(Role.ADMIN)
    async def wh_set_slowmode(self, ctx: commands.Context, name: str, seconds: int = 0) -> None:
        """Set slowmode (seconds between messages per user, 0 to disable)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["slowmode"] = max(0, seconds)
        await ctx.send(embed=ok_embed(f"Slowmode set to {seconds}s for `{name}`."))
        await self._log(nd, info_embed(f"Slowmode set to **{seconds}**s by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Log channel ────────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="logchannel", aliases=["log"])
    @requires_role(Role.ADMIN)
    async def wh_set_logchannel(self, ctx: commands.Context, name: str, channel: discord.TextChannel = None) -> None:
        """Set (or clear) the mod log channel."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["log_channel"] = channel.id if channel else None
        await ctx.send(embed=ok_embed(f"Log channel {'set to ' + channel.mention if channel else 'cleared'} for `{name}`."))
        if channel:
            await self._log(nd, info_embed(f"Log channel set to {channel.mention} by {ctx.author}", title="⚙️ Logging Configured"))

    # ── Server nicknames ───────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="servernick")
    @requires_role(Role.ADMIN)
    async def wh_set_servernick(self, ctx: commands.Context, name: str, guild_id: int, *, nick: str = None) -> None:
        """Set or clear a nickname for a server in relay messages."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            nicks = ns[name].setdefault("server_nicknames", {})
            if nick:
                nicks[str(guild_id)] = nick
            else:
                nicks.pop(str(guild_id), None)
        await ctx.send(embed=ok_embed(f"Server nickname {'set' if nick else 'cleared'}."))
        await self._log(nd, info_embed(f"Server nickname **{'set to ' + nick if nick else 'cleared'}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Relay delay ────────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="delay")
    @requires_role(Role.ADMIN)
    async def wh_set_delay(self, ctx: commands.Context, name: str, seconds: int = 0) -> None:
        """Set relay delay (seconds before messages are relayed, 0 to disable)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["relay_delay"] = max(0, seconds)
        await ctx.send(embed=ok_embed(f"Relay delay set to {seconds}s for `{name}`."))
        await self._log(nd, info_embed(f"Relay delay set to **{seconds}**s by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Ephemeral auto-delete ──────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="ephemeral")
    @requires_role(Role.ADMIN)
    async def wh_set_ephemeral(self, ctx: commands.Context, name: str, seconds: int = 0) -> None:
        """Auto-delete relayed messages after N seconds (0 to disable)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["ephemeral_delay"] = max(0, seconds)
        await ctx.send(embed=ok_embed(f"Ephemeral delay set to {seconds}s for `{name}`."))
        await self._log(nd, info_embed(f"Ephemeral delay set to **{seconds}**s by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Discovery ──────────────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="public")
    @requires_role(Role.OWNER)
    async def wh_set_public(self, ctx: commands.Context, name: str, enabled: bool) -> None:
        """Make network publicly discoverable."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["public"] = enabled
        await ctx.send(embed=ok_embed(f"`{name}` is now {'public' if enabled else 'private'}."))
        await self._log(nd, info_embed(f"Network visibility set to **{'public' if enabled else 'private'}** by {ctx.author}", title="⚙️ Setting Changed"))

    @WormholeBase.wh_set.command(name="tags")
    @requires_role(Role.ADMIN)
    async def wh_set_tags(self, ctx: commands.Context, name: str, *, tags: str) -> None:
        """Set discovery tags (comma-separated)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        async with self.config.networks() as ns:
            ns[name]["tags"] = tag_list
        await ctx.send(embed=ok_embed(f"Tags set for `{name}`: {', '.join(tag_list)}"))
        await self._log(nd, info_embed(f"Tags updated: **{', '.join(tag_list)}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── Channel overrides ──────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="override")
    @requires_role(Role.ADMIN)
    async def wh_set_override(self, ctx: commands.Context, name: str, key: str, value: str) -> None:
        """Set a per-channel config override for the current channel."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        if ctx.channel.id not in nd.get("channels", []):
            return await ctx.send(embed=err_embed("This channel isn't in the network."))
        # Try to parse value
        parsed = value
        if value.lower() in ("true", "false"):
            parsed = value.lower() == "true"
        else:
            try:
                parsed = int(value)
            except ValueError:
                try:
                    parsed = float(value)
                except ValueError:
                    pass
        async with self.config.networks() as ns:
            overrides = ns[name].setdefault("channel_overrides", {})
            overrides.setdefault(str(ctx.channel.id), {})[key] = parsed
        await ctx.send(embed=ok_embed(f"Override `{key} = {parsed}` set for this channel in `{name}`."))
        await self._log(nd, info_embed(f"Channel override set: **{key} = {parsed}** by {ctx.author}", title="⚙️ Setting Changed"))

    # ── View all settings ──────────────────────────────────────────────────

    @WormholeBase.wh_set.command(name="show")
    @requires_role(Role.HELPER)
    async def wh_set_show(self, ctx: commands.Context, name: str) -> None:
        """Show current settings for a network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        em = discord.Embed(title=f"⚙️ Settings — {name}", colour=COLOUR_INFO)
        em.add_field(name="Relay", value=(
            f"Mode: {nd.get('relay_mode', 'webhook')}\n"
            f"Image: {nd.get('image_mode', 'user')}\n"
            f"Name: {nd.get('name_mode', 'both')}\n"
            f"Frozen: {nd.get('frozen', False)}\n"
            f"Anonymous: {nd.get('anonymous', False)}"
        ), inline=True)
        em.add_field(name="Sync", value=(
            f"Edits: {nd.get('sync_edits')}\n"
            f"Deletes: {nd.get('sync_deletes')}\n"
            f"Reactions: {nd.get('sync_reactions')}\n"
            f"Replies: {nd.get('sync_replies')}\n"
            f"Typing: {nd.get('sync_typing', False)}"
        ), inline=True)
        em.add_field(name="Limits", value=(
            f"Rate: {nd.get('rate_limit_rate', 5)}/{nd.get('rate_limit_per', 10)}s\n"
            f"Slowmode: {nd.get('slowmode', 0)}s\n"
            f"Delay: {nd.get('relay_delay', 0)}s\n"
            f"Ephemeral: {nd.get('ephemeral_delay', 0)}s"
        ), inline=True)
        am = nd.get("automod", {})
        if am.get("enabled"):
            active = [k.replace("anti_", "") for k, v in am.items() if k.startswith("anti_") and v]
            em.add_field(name="Automod", value=", ".join(active) or "None active", inline=False)
        await ctx.send(embed=em)
