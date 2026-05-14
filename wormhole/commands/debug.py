"""Debug and diagnostic commands — health, trace, test, backup/restore."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

import discord
from redbot.core import checks, commands

from ..models.permissions import Role, has_role, requires_role
from ..utils import ok_embed, err_embed, info_embed, warn_embed, COLOUR_INFO, human_timedelta


class DebugCommands:
    """Mixin — debug, diagnostics, backup/restore."""

    @commands.group(name="wh-debug", aliases=["whdebug"], invoke_without_command=True)
    async def wh_debug(self, ctx: commands.Context) -> None:
        """Debug and diagnostic tools."""
        await ctx.send_help(ctx.command)

    @wh_debug.command(name="health")
    @requires_role(Role.HELPER)
    async def wh_debug_health(self, ctx: commands.Context, name: str) -> None:
        """Check network health — permissions, webhooks, channel status."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        channels = nd.get("channels", [])
        lines = []
        healthy = 0
        for ch_id in channels:
            ch = self.bot.get_channel(ch_id)
            if not ch:
                lines.append(f"❌ `{ch_id}` — channel not found")
                continue
            perms = ch.permissions_for(ch.guild.me)
            issues = []
            if not perms.send_messages:
                issues.append("no send_messages")
            if not perms.manage_webhooks:
                issues.append("no manage_webhooks")
            if not perms.embed_links:
                issues.append("no embed_links")
            if not perms.attach_files:
                issues.append("no attach_files")
            if not perms.read_message_history:
                issues.append("no read_history")
            if issues:
                lines.append(f"⚠️ {ch.mention} — {', '.join(issues)}")
            else:
                lines.append(f"✅ {ch.mention}")
                healthy += 1
        em = discord.Embed(
            title=f"🏥 Health — {name}",
            description="\n".join(lines) or "No channels",
            colour=COLOUR_INFO,
        )
        em.set_footer(text=f"{healthy}/{len(channels)} healthy · Last check: {nd.get('last_health_check', 'never')[:16]}")
        await ctx.send(embed=em)

    @wh_debug.command(name="trace")
    @requires_role(Role.ADMIN)
    async def wh_debug_trace(self, ctx: commands.Context) -> None:
        """Toggle trace mode for this channel — logs all relay decisions."""
        if ctx.channel.id in self._trace_channels:
            self._trace_channels.discard(ctx.channel.id)
            await ctx.send(embed=ok_embed("Trace mode **disabled** for this channel."))
        else:
            self._trace_channels.add(ctx.channel.id)
            await ctx.send(embed=ok_embed("Trace mode **enabled** — relay decisions will be logged here."))

    @wh_debug.command(name="testsend")
    @requires_role(Role.ADMIN)
    async def wh_debug_testsend(self, ctx: commands.Context, name: str) -> None:
        """Send a test message through the relay."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        em = info_embed(
            f"🧪 Test relay from {ctx.author} in {ctx.guild.name if ctx.guild else 'DM'}",
            title=f"Test — {name}",
        )
        sent = 0
        for ch_id in nd.get("channels", []):
            if ch_id == ctx.channel.id:
                continue
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    await ch.send(embed=em)
                    sent += 1
                except Exception as exc:
                    await ctx.send(embed=warn_embed(f"Failed to send to {ch.mention}: {exc}"))
        await ctx.send(embed=ok_embed(f"Test message sent to {sent} channels."))

    @wh_debug.command(name="relaydebug")
    @requires_role(Role.ADMIN)
    async def wh_debug_relaydebug(self, ctx: commands.Context, name: str) -> None:
        """Show detailed relay pipeline state for diagnostics."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        em = discord.Embed(title=f"🔬 Relay Debug — {name}", colour=COLOUR_INFO)
        em.add_field(name="Relay Mode", value=nd.get("relay_mode", "webhook"), inline=True)
        em.add_field(name="Frozen", value=str(nd.get("frozen", False)), inline=True)
        em.add_field(name="Silent", value=str(nd.get("silent", False)), inline=True)
        em.add_field(name="Channels", value=str(len(nd.get("channels", []))), inline=True)
        em.add_field(name="Banned Users", value=str(len(nd.get("banned_users", []))), inline=True)
        em.add_field(name="Muted Users", value=str(len(nd.get("muted_users", []))), inline=True)
        em.add_field(name="Msg Map Size", value=str(len(self.msg_map.forward.get(name, {}))), inline=True)
        em.add_field(name="WH Cache Size", value=str(len(self._wh_cache)), inline=True)
        am = nd.get("automod", {})
        active_am = [k.replace("anti_", "") for k, v in am.items() if k.startswith("anti_") and v]
        em.add_field(name="Automod Active", value=", ".join(active_am) or "None", inline=False)
        await ctx.send(embed=em)

    # ── Backup / Restore ───────────────────────────────────────────────────

    @wh_debug.command(name="backup")
    @requires_role(Role.OWNER)
    async def wh_debug_backup(self, ctx: commands.Context, name: str) -> None:
        """Export network config as a JSON file."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        data = deepcopy(nd)
        # Sanitise sensitive bits
        data.pop("audit_log", None)
        data.pop("reports", None)
        import io
        buf = io.BytesIO(json.dumps(data, indent=2, default=str).encode())
        buf.seek(0)
        await ctx.send(
            embed=ok_embed(f"Backup for `{name}`:"),
            file=discord.File(buf, filename=f"wormhole_{name}_backup.json"),
        )

    @wh_debug.command(name="restore")
    @checks.is_owner()
    async def wh_debug_restore(self, ctx: commands.Context, name: str) -> None:
        """Restore a network from a JSON backup (attach file to message)."""
        if not ctx.message.attachments:
            return await ctx.send(embed=err_embed("Attach a backup JSON file."))
        att = ctx.message.attachments[0]
        if not att.filename.endswith(".json"):
            return await ctx.send(embed=err_embed("File must be .json"))
        raw = await att.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return await ctx.send(embed=err_embed("Invalid JSON."))
        async with self.config.networks() as ns:
            ns[name] = data
        await ctx.send(embed=ok_embed(f"Network `{name}` restored from backup."))

    # ── Version ────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="wh-version")
    async def wh_version(self, ctx: commands.Context) -> None:
        """Show Wormhole cog version."""
        nets = await self.config.networks()
        total_ch = sum(len(d.get("channels", [])) for d in nets.values())
        total_msg = sum(d.get("total_messages", 0) for d in nets.values())
        em = discord.Embed(
            title="🌀 Wormhole",
            description=(
                f"**Version:** {self.__version__}\n"
                f"**Networks:** {len(nets)}\n"
                f"**Channels:** {total_ch}\n"
                f"**Messages relayed:** {total_msg:,}"
            ),
            colour=COLOUR_INFO,
        )
        await ctx.send(embed=em)
