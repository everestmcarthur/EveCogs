"""Report system commands — create, view, resolve, dismiss reports."""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role, has_role
from ..utils import ok_embed, err_embed, info_embed, warn_embed, truncate, COLOUR_INFO
from ._base import WormholeBase


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
        await self._log(nd, warn_embed(
            f"🚩 **Report #{report_id}**\n"
            f"Reporter: {ctx.author} (`{ctx.author.id}`)\n"
            f"Message ID: `{message_id}`\n"
            f"Reason: {reason}",
            title="New Report",
        ))

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
                    r["resolved_at"] = datetime.now(timezone.utc).isoformat()
                    break
            else:
                return await ctx.send(embed=err_embed(f"Report #{report_id} not found."))
        await ctx.send(embed=ok_embed(f"Report #{report_id} resolved."))
        await self._audit(name, "report_resolve", str(ctx.author), str(report_id), resolution)

    @WormholeBase.wh_report.command(name="dismiss")
    @requires_role(Role.MODERATOR)
    async def wh_report_dismiss(self, ctx: commands.Context, name: str, report_id: int, *, reason: str = "Dismissed") -> None:
        """Dismiss a report."""
        async with self.config.networks() as ns:
            for r in ns[name].get("reports", []):
                if r.get("id") == report_id:
                    r["resolved"] = True
                    r["resolved_by"] = ctx.author.id
                    r["resolution"] = f"Dismissed: {reason}"
                    r["resolved_at"] = datetime.now(timezone.utc).isoformat()
                    break
            else:
                return await ctx.send(embed=err_embed(f"Report #{report_id} not found."))
        await ctx.send(embed=ok_embed(f"Report #{report_id} dismissed."))
        await self._audit(name, "report_dismiss", str(ctx.author), str(report_id), reason)
