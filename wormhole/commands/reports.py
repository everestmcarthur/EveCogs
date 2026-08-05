"""Report system commands — create, view, resolve, dismiss reports."""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role, has_role
from ..utils import ok_embed, err_embed, info_embed, warn_embed, truncate, COLOUR_INFO
from ._base import WormholeBase
from ..ui.views import ReportActionView


class ReportCommands(WormholeBase):
    """Mixin — user report system (per-network)."""

    @WormholeBase.wh_report.command(name="msg")
    async def wh_report_msg(self, ctx: commands.Context, message_id: int, *, reason: str = "No reason provided") -> None:
        """Report a message by ID."""
        net_name = await self._net_for_ch(ctx.channel.id)
        if not net_name:
            return await ctx.send(embed=err_embed("This channel isn't in a network."))

        # Fetch the message so the report actually records who wrote it and
        # what it said, instead of just a bare, unverified id.
        target_message = None
        try:
            target_message = await ctx.channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        # report_id must be computed and written inside the same locked
        # section — reading report_counter beforehand let two concurrent
        # reports land on the same id and left the counter not advanced.
        async with self.config.networks() as ns:
            nd = ns.get(net_name)
            if not nd:
                return await ctx.send(embed=err_embed(f"Network `{net_name}` not found."))
            report_id = nd.get("report_counter", 0) + 1
            report = {
                "id": report_id,
                "reporter_id": ctx.author.id,
                "author_id": target_message.author.id if target_message else None,
                "message_id": message_id,
                "channel_id": ctx.channel.id,
                "guild_id": ctx.guild.id if ctx.guild else None,
                "content_preview": truncate(target_message.content or "*[no text]*", 300) if target_message else None,
                "jump_url": target_message.jump_url if target_message else None,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "resolved": False,
                "resolved_by": None,
                "resolution": None,
            }
            nd.setdefault("reports", []).append(report)
            nd["report_counter"] = report_id

        await ctx.send(embed=ok_embed(f"Report #{report_id} submitted. Staff will review it."), delete_after=10)

        # Send to configured report channel (if set) with action buttons
        try:
            nd_full = await self._net(net_name)
            await self._notify_report_channel(nd_full, net_name, report)
        except Exception:
            pass

    @WormholeBase.wh_report.command(name="list")
    @requires_role(Role.HELPER)
    async def wh_report_list(self, ctx: commands.Context, name: str, show_resolved: bool = False) -> None:
        """List reports for a network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        reports = nd.get("reports", [])
        if not show_resolved:
            reports = [r for r in reports if not r.get("resolved")]
        if not reports:
            return await ctx.send(embed=info_embed("No open reports."))
        lines = []
        for r in reports[-20:]:
            status = "✅" if r.get("resolved") else "🔴"
            reporter = self.bot.get_user(r.get("reporter_id"))
            lines.append(
                f"{status} **#{r['id']}** — by {reporter or r.get('reporter_id')}\n"
                f"  Reason: {truncate(r.get('reason', ''), 80)}"
            )
        em = discord.Embed(title=f"🚩 Reports — {name}", description="\n".join(lines), colour=COLOUR_INFO)
        await ctx.send(embed=em)

    @WormholeBase.wh_report.command(name="view")
    @requires_role(Role.HELPER)
    async def wh_report_view(self, ctx: commands.Context, name: str, report_id: int) -> None:
        """View details of a specific report."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        report = None
        for r in nd.get("reports", []):
            if r.get("id") == report_id:
                report = r
                break
        if not report:
            return await ctx.send(embed=err_embed(f"Report #{report_id} not found."))
        reporter = self.bot.get_user(report.get("reporter_id"))
        em = discord.Embed(title=f"🚩 Report #{report_id}", colour=COLOUR_INFO)
        em.add_field(name="Reporter", value=str(reporter or report.get("reporter_id")), inline=True)
        if report.get("author_id"):
            author = self.bot.get_user(report["author_id"])
            em.add_field(name="Message Author", value=str(author or report["author_id"]), inline=True)
        em.add_field(name="Status", value="Resolved" if report.get("resolved") else "Open", inline=True)
        em.add_field(name="Reason", value=report.get("reason", "N/A"), inline=False)
        if report.get("content_preview"):
            em.add_field(name="Message Content", value=truncate(report["content_preview"], 1024), inline=False)
        em.add_field(name="Timestamp", value=report.get("timestamp", "?")[:16], inline=True)
        if report.get("message_id"):
            id_value = f"`{report['message_id']}`"
            if report.get("jump_url"):
                id_value += f" — [Jump]({report['jump_url']})"
            em.add_field(name="Message ID", value=id_value, inline=True)
        if report.get("resolved_by"):
            resolver = self.bot.get_user(report["resolved_by"])
            em.add_field(name="Resolved By", value=str(resolver or report["resolved_by"]), inline=True)
        if report.get("resolution"):
            em.add_field(name="Resolution", value=report["resolution"], inline=False)
        await ctx.send(embed=em)

    @WormholeBase.wh_report.command(name="resolve")
    @requires_role(Role.MODERATOR)
    async def wh_report_resolve(self, ctx: commands.Context, name: str, report_id: int, *, resolution: str = "Resolved") -> None:
        """Resolve a report."""
        async with self.config.networks() as ns:
            for r in ns[name].get("reports", []):
                if r.get("id") == report_id:
                    r["resolved"] = True
                    r["resolved_by"] = ctx.author.id
                    r["resolution"] = resolution
                    break
        await ctx.send(embed=ok_embed(f"Report #{report_id} marked resolved."))

    @WormholeBase.wh_report.command(name="channel")
    @requires_role(Role.ADMIN)
    async def wh_report_set_channel(self, ctx: commands.Context, name: str, channel: discord.TextChannel | None = None) -> None:
        """Set the channel where reports are posted (for staff). Pass no channel to clear."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        async with self.config.networks() as ns:
            ns[name]["report_channel"] = channel.id if channel else None
        await ctx.send(embed=ok_embed(f"Report channel {'set' if channel else 'cleared'} for `{name}`."))

    # Helper used by both commands and the ReportModal to notify staff
    async def _notify_report_channel(self, nd: dict, net_name: str, report: dict) -> None:
        ch_id = nd.get("report_channel")
        em = discord.Embed(
            title=f"🚩 Report #{report['id']} — {net_name}",
            description=(
                f"Reporter: <@{report['reporter_id']}> (`{report['reporter_id']}`)\n"
                f"Author: <@{report['author_id']}> (`{report.get('author_id')}`)\n"
                f"Channel: <#{report['channel_id']}>\n"
                f"Reason: {truncate(report.get('reason', ''), 300)}"
            ),
            colour=COLOUR_INFO,
            timestamp=datetime.fromisoformat(report['timestamp']),
        )
        if report.get('content_preview'):
            em.add_field(name="Content Preview", value=truncate(report['content_preview'], 1024), inline=False)
        if report.get('jump_url'):
            em.add_field(name="Jump", value=f"[Jump to message]({report['jump_url']})", inline=True)

        # DM owner as a courtesy
        try:
            owner = self.bot.get_user(nd.get('owner_id'))
            if owner:
                await owner.send(embed=warn_embed(
                    f"**Report #{report['id']}** in `{net_name}`\n"
                    f"Reporter: <@{report['reporter_id']}> (`{report['reporter_id']}`)\n"
                    f"Author: <@{report.get('author_id')}> (`{report.get('author_id')}`)\n"
                    f"Reason: {truncate(report.get('reason',''),200)}",
                    title="🚩 New Report",
                ))
        except discord.Forbidden:
            pass

        if not ch_id:
            return
        ch = self.bot.get_channel(ch_id)
        if not ch:
            return
        view = ReportActionView(self, net_name, report['id'], jump_url=report.get('jump_url'))
        try:
            await ch.send(embed=em, view=view)
        except Exception:
            pass

    # Interaction handlers invoked by ReportActionView
    async def _report_resolve_via_interaction(self, interaction: discord.Interaction, net_name: str, report_id: int) -> None:
        nd = await self._net(net_name)
        if not nd:
            return await interaction.response.send_message("Network not found.", ephemeral=True)
        if not has_role(nd, interaction.user.id, Role.MODERATOR) and not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("You need Moderator role or higher.", ephemeral=True)
        # update report
        async with self.config.networks() as ns:
            for r in ns[net_name].get('reports', []):
                if r.get('id') == report_id:
                    r['resolved'] = True
                    r['resolved_by'] = interaction.user.id
                    r['resolution'] = 'Resolved via report button'
                    break
        # Edit the original message to indicate resolved
        try:
            em = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
            if em:
                em.set_footer(text=f"Resolved by {interaction.user}")
                await interaction.message.edit(embed=em, view=None)
        except Exception:
            pass
        await interaction.response.send_message(embed=ok_embed(f"Report #{report_id} marked resolved."), ephemeral=True)

    async def _report_dismiss_via_interaction(self, interaction: discord.Interaction, net_name: str, report_id: int) -> None:
        nd = await self._net(net_name)
        if not nd:
            return await interaction.response.send_message("Network not found.", ephemeral=True)
        if not has_role(nd, interaction.user.id, Role.MODERATOR) and not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message("You need Moderator role or higher.", ephemeral=True)
        async with self.config.networks() as ns:
            for r in ns[net_name].get('reports', []):
                if r.get('id') == report_id:
                    r['resolved'] = True
                    r['resolved_by'] = interaction.user.id
                    r['resolution'] = 'Dismissed'
                    break
        try:
            em = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
            if em:
                em.colour = 0x2ECC71
                em.set_footer(text=f"Dismissed by {interaction.user}")
                await interaction.message.edit(embed=em, view=None)
        except Exception:
            pass
        await interaction.response.send_message(embed=ok_embed(f"Report #{report_id} dismissed."), ephemeral=True)
