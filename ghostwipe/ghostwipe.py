"""
GhostWipe - Deletes a departing member's messages server-wide and produces a
full HTML audit log of what was removed.

Fires only on `on_member_remove` (voluntary leave, kick, or ban - Discord
delivers all three through that single event). The departure type is then
classified via the audit log purely for reporting/toggle purposes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import humanize_number

from .report import generate_report_html

LOG = logging.getLogger("red.evecogs.ghostwipe")

REASON_TRIGGER_KEY = {
    "left": "trigger_leave",
    "kicked": "trigger_kick",
    "banned": "trigger_ban",
}
REASON_LABEL = {"left": "Left", "kicked": "Kicked", "banned": "Banned", "manual": "Manual"}
REASON_COLOUR = {
    "left": discord.Colour.light_grey(),
    "kicked": discord.Colour.orange(),
    "banned": discord.Colour.red(),
    "manual": discord.Colour.blurple(),
}
COLOUR_OK = discord.Colour.green()
COLOUR_INFO = discord.Colour.blurple()
COLOUR_WARN = discord.Colour.orange()
COLOUR_ERR = discord.Colour.red()

MAX_HISTORY_ENTRIES = 50
DISCORD_ATTACHMENT_LIMIT = 8 * 1024 * 1024  # 8MB, safe default (no boost assumptions)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _humanize_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


class GhostWipe(commands.Cog):
    """Auto-purge a departing member's messages, with a full HTML audit log."""

    __version__ = "1.0.0"
    __author__ = ["everestmcarthur"]

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x67686F73_74776970, force_registration=True)

        default_guild: Dict[str, Any] = {
            "enabled": False,
            "log_channel": None,

            "trigger_leave": True,
            "trigger_kick": True,
            "trigger_ban": True,

            "whitelist_users": [],
            "ignore_roles": [],

            "ignored_channels": [],
            "include_threads": True,
            "include_archived_threads": True,
            "history_limit": 2000,

            "delete_delay": 0,
            "dry_run": False,
            "rate_limit_delay": 0.5,
            "audit_log_window": 10,

            "attach_html_report": True,
            "reveal_content": True,
            "keep_reports_days": 30,

            "history": [],
            "stats": {"total_events": 0, "total_messages_deleted": 0},
        }
        self.config.register_guild(**default_guild)

        # (guild_id, user_id) -> asyncio.Task, used to cancel a pending delayed
        # purge if the member rejoins within the configured grace period.
        self._pending: Dict[Tuple[int, int], asyncio.Task] = {}

    async def cog_unload(self) -> None:
        for task in list(self._pending.values()):
            if not task.done():
                task.cancel()
        self._pending.clear()

    # ══════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════

    def _reports_dir(self, guild_id: int) -> Path:
        path = cog_data_path(self) / str(guild_id) / "reports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _classify_departure(
        self, guild: discord.Guild, member: discord.abc.Snowflake, window: int
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """Return (reason, moderator_str, mod_reason) by inspecting the audit log.

        reason is one of "banned", "kicked", "left".
        """
        now = datetime.now(timezone.utc)

        async def _recent_entry(action: discord.AuditLogAction):
            try:
                async for entry in guild.audit_logs(action=action, limit=10):
                    if entry.target and entry.target.id == member.id:
                        age = (now - entry.created_at).total_seconds()
                        if age <= window:
                            return entry
            except discord.Forbidden:
                return None
            except discord.HTTPException:
                return None
            return None

        ban_entry = await _recent_entry(discord.AuditLogAction.ban)
        if ban_entry:
            mod = str(ban_entry.user) if ban_entry.user else None
            return "banned", mod, ban_entry.reason

        kick_entry = await _recent_entry(discord.AuditLogAction.kick)
        if kick_entry:
            mod = str(kick_entry.user) if kick_entry.user else None
            return "kicked", mod, kick_entry.reason

        return "left", None, None

    def _is_image(self, filename: str, content_type: Optional[str]) -> bool:
        if content_type and content_type.startswith("image/"):
            return True
        return filename.lower().endswith(IMAGE_EXTENSIONS)

    def _serialize_message(self, message: discord.Message) -> Dict[str, Any]:
        attachments = []
        for att in message.attachments:
            attachments.append(
                {
                    "filename": att.filename,
                    "url": att.url,
                    "size": _humanize_size(att.size),
                    "is_image": self._is_image(att.filename, att.content_type),
                }
            )
        stickers = [s.name for s in getattr(message, "stickers", [])]
        return {
            "id": str(message.id),
            "timestamp": message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "content": message.content or "",
            "attachments": attachments,
            "stickers": stickers,
        }

    async def _gather_target_channels(
        self, guild: discord.Guild, conf: Dict[str, Any]
    ) -> List[Tuple[str, discord.abc.Messageable, str]]:
        """Return list of (kind, channel, display_name) to scan."""
        ignored = set(conf["ignored_channels"])
        targets: List[Tuple[str, discord.abc.Messageable, str]] = []

        for ch in guild.text_channels:
            if ch.id in ignored:
                continue
            targets.append(("text", ch, ch.name))

        for ch in guild.voice_channels:
            if ch.id in ignored:
                continue
            targets.append(("voice", ch, ch.name))

        if conf["include_threads"]:
            for th in guild.threads:
                if th.id in ignored:
                    continue
                targets.append(("thread", th, th.name))

            if conf["include_archived_threads"]:
                for ch in guild.text_channels:
                    if ch.id in ignored:
                        continue
                    try:
                        async for th in ch.archived_threads(limit=100):
                            if th.id in ignored:
                                continue
                            targets.append(("thread", th, th.name))
                    except (discord.Forbidden, discord.HTTPException):
                        continue

        return targets

    async def _scan_channel(
        self,
        kind: str,
        channel: discord.abc.Messageable,
        member: discord.abc.Snowflake,
        history_limit: int,
        dry_run: bool,
    ) -> Dict[str, Any]:
        limit = None if not history_limit else history_limit
        perms = getattr(channel, "permissions_for", None)
        me = channel.guild.me if hasattr(channel, "guild") else None
        if perms and me:
            p = channel.permissions_for(me)
            needed = p.read_message_history and (dry_run or p.manage_messages)
            if not needed:
                return {
                    "id": str(channel.id),
                    "name": getattr(channel, "name", str(channel.id)),
                    "type": kind,
                    "skipped": True,
                    "skip_reason": "missing permissions (read message history / manage messages)",
                    "message_count": 0,
                    "messages": [],
                }

        def _check(m: discord.Message) -> bool:
            return m.author.id == member.id

        try:
            if dry_run:
                collected = []
                async for m in channel.history(limit=limit):
                    if _check(m):
                        collected.append(m)
            else:
                collected = await channel.purge(limit=limit, check=_check)
        except discord.Forbidden:
            return {
                "id": str(channel.id),
                "name": getattr(channel, "name", str(channel.id)),
                "type": kind,
                "skipped": True,
                "skip_reason": "forbidden while scanning/deleting",
                "message_count": 0,
                "messages": [],
            }
        except discord.HTTPException as exc:
            return {
                "id": str(channel.id),
                "name": getattr(channel, "name", str(channel.id)),
                "type": kind,
                "skipped": True,
                "skip_reason": f"discord API error: {exc}",
                "message_count": 0,
                "messages": [],
            }

        messages = [self._serialize_message(m) for m in collected]
        return {
            "id": str(channel.id),
            "name": getattr(channel, "name", str(channel.id)),
            "type": kind,
            "skipped": False,
            "skip_reason": None,
            "message_count": len(messages),
            "messages": messages,
        }

    async def _purge_member(
        self,
        guild: discord.Guild,
        member: discord.abc.Snowflake,
        member_display: str,
        member_avatar_url: str,
        reason: str,
        conf: Dict[str, Any],
        moderator: Optional[str] = None,
        mod_reason: Optional[str] = None,
    ) -> None:
        targets = await self._gather_target_channels(guild, conf)
        history_limit = conf["history_limit"]
        dry_run = conf["dry_run"]
        rate_delay = conf["rate_limit_delay"]

        semaphore = asyncio.Semaphore(3)
        channels_data: List[Dict[str, Any]] = []

        async def _worker(kind: str, channel: discord.abc.Messageable):
            async with semaphore:
                result = await self._scan_channel(kind, channel, member, history_limit, dry_run)
                if rate_delay:
                    await asyncio.sleep(rate_delay)
                return result

        results = await asyncio.gather(*(_worker(k, c) for k, c, _ in targets))
        channels_data.extend(results)

        total_deleted = sum(c["message_count"] for c in channels_data if not c["skipped"])
        event_id = f"{int(time.time())}_{member.id}"
        event_time = datetime.now(timezone.utc)

        html = generate_report_html(
            guild_name=guild.name,
            member_name=member_display,
            member_id=member.id,
            avatar_url=member_avatar_url,
            reason=reason,
            event_time_str=event_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            moderator=moderator,
            mod_reason=mod_reason,
            dry_run=dry_run,
            reveal_content=conf["reveal_content"],
            channels=channels_data,
            version=self.__version__,
            generated_at=event_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

        reports_dir = self._reports_dir(guild.id)
        html_path = reports_dir / f"{event_id}.html"
        json_path = reports_dir / f"{event_id}.json"
        html_path.write_text(html, encoding="utf-8")
        json_path.write_text(
            json.dumps(
                {
                    "event_id": event_id,
                    "guild_id": guild.id,
                    "member_id": member.id,
                    "member_display": member_display,
                    "reason": reason,
                    "moderator": moderator,
                    "mod_reason": mod_reason,
                    "dry_run": dry_run,
                    "timestamp": event_time.isoformat(),
                    "channels": channels_data,
                },
                default=str,
            ),
            encoding="utf-8",
        )

        channels_affected = sum(1 for c in channels_data if not c["skipped"] and c["message_count"] > 0)
        channels_skipped = sum(1 for c in channels_data if c["skipped"])

        async with self.config.guild(guild).history() as history:
            history.append(
                {
                    "event_id": event_id,
                    "member_id": member.id,
                    "member_display": member_display,
                    "reason": reason,
                    "timestamp": event_time.isoformat(),
                    "messages_deleted": total_deleted,
                    "channels_affected": channels_affected,
                    "channels_skipped": channels_skipped,
                    "dry_run": dry_run,
                }
            )
            if len(history) > MAX_HISTORY_ENTRIES:
                del history[: len(history) - MAX_HISTORY_ENTRIES]

        if not dry_run:
            async with self.config.guild(guild).stats() as stats:
                stats["total_events"] = stats.get("total_events", 0) + 1
                stats["total_messages_deleted"] = stats.get("total_messages_deleted", 0) + total_deleted

        self._prune_old_reports(guild.id, conf["keep_reports_days"])

        LOG.info(
            "GhostWipe purged %s in guild %s (%s): %d messages across %d channels",
            member_display, guild.id, reason, total_deleted, channels_affected,
        )

        await self._send_log(
            guild, conf, member_display, member.id, member_avatar_url, reason,
            moderator, mod_reason, total_deleted, channels_affected, channels_skipped,
            dry_run, html_path, channels_data,
        )

    def _prune_old_reports(self, guild_id: int, keep_days: int) -> None:
        if not keep_days:
            return
        cutoff = time.time() - (keep_days * 86400)
        directory = self._reports_dir(guild_id)
        for f in directory.glob("*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                continue

    async def _send_log(
        self,
        guild: discord.Guild,
        conf: Dict[str, Any],
        member_display: str,
        member_id: int,
        avatar_url: str,
        reason: str,
        moderator: Optional[str],
        mod_reason: Optional[str],
        total_deleted: int,
        channels_affected: int,
        channels_skipped: int,
        dry_run: bool,
        html_path: Path,
        channels_data: List[Dict[str, Any]],
    ) -> None:
        channel_id = conf["log_channel"]
        if not channel_id:
            return
        log_channel = guild.get_channel(channel_id)
        if not isinstance(log_channel, discord.TextChannel):
            return

        title = f"👻 GhostWipe — {REASON_LABEL.get(reason, reason.title())}"
        if dry_run:
            title += " (Dry Run)"
        embed = discord.Embed(title=title, colour=REASON_COLOUR.get(reason, COLOUR_INFO), timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=avatar_url)
        embed.add_field(name="Member", value=f"{member_display} (`{member_id}`)", inline=True)
        embed.add_field(name="Messages Deleted", value=humanize_number(total_deleted), inline=True)
        embed.add_field(name="Channels Affected", value=str(channels_affected), inline=True)
        if channels_skipped:
            embed.add_field(name="Channels Skipped", value=str(channels_skipped), inline=True)
        if moderator:
            field_val = moderator
            if mod_reason:
                field_val += f"\nReason: {mod_reason}"
            embed.add_field(name="Actioned By", value=field_val, inline=True)

        top = sorted((c for c in channels_data if not c["skipped"] and c["message_count"] > 0),
                     key=lambda c: c["message_count"], reverse=True)[:10]
        if top:
            breakdown = "\n".join(f"**{c['name']}** — {c['message_count']}" for c in top)
            embed.add_field(name="Per-Channel Breakdown", value=breakdown, inline=False)
        embed.set_footer(text=f"GhostWipe v{self.__version__}")

        file_obj = None
        if conf["attach_html_report"]:
            try:
                if html_path.stat().st_size <= DISCORD_ATTACHMENT_LIMIT:
                    file_obj = discord.File(str(html_path), filename=f"ghostwipe_{member_id}.html")
                else:
                    embed.add_field(
                        name="Report",
                        value="Report file exceeds Discord's upload limit — saved to disk only.",
                        inline=False,
                    )
            except OSError:
                pass

        try:
            if file_obj:
                await log_channel.send(embed=embed, file=file_obj)
            else:
                await log_channel.send(embed=embed)
        except discord.HTTPException:
            LOG.exception("Failed to send GhostWipe log to channel %s in guild %s", channel_id, guild.id)

    # ══════════════════════════════════════════════════════════
    # Listeners
    # ══════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = member.guild
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return
        if member.id in conf["whitelist_users"]:
            return

        member_role_ids = {r.id for r in getattr(member, "roles", [])}
        if member_role_ids & set(conf["ignore_roles"]):
            return

        reason, moderator, mod_reason = await self._classify_departure(
            guild, member, conf["audit_log_window"]
        )
        trigger_key = REASON_TRIGGER_KEY.get(reason)
        if trigger_key and not conf[trigger_key]:
            return

        member_display = str(member)
        avatar_url = member.display_avatar.url if member.display_avatar else ""
        delay = conf["delete_delay"]
        key = (guild.id, member.id)

        async def _runner():
            try:
                if delay:
                    await asyncio.sleep(delay)
                await self._purge_member(
                    guild, member, member_display, avatar_url, reason, conf,
                    moderator, mod_reason,
                )
            except asyncio.CancelledError:
                LOG.debug("GhostWipe purge cancelled (rejoin) for %s in guild %s", member.id, guild.id)
            except Exception:
                LOG.exception("GhostWipe purge failed for %s in guild %s", member.id, guild.id)
            finally:
                self._pending.pop(key, None)

        task = self.bot.loop.create_task(_runner())
        self._pending[key] = task

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        key = (member.guild.id, member.id)
        task = self._pending.pop(key, None)
        if task and not task.done():
            task.cancel()

    # ══════════════════════════════════════════════════════════
    # Commands
    # ══════════════════════════════════════════════════════════

    @commands.group(name="ghostwipe", aliases=["gw", "wipe"])
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def ghostwipe(self, ctx: commands.Context):
        """👻 GhostWipe — auto-delete a departing member's messages, with a full HTML audit log."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ghostwipe.command(name="enable", aliases=["on"])
    async def gw_enable(self, ctx: commands.Context):
        """Enable GhostWipe for this server."""
        await self.config.guild(ctx.guild).enabled.set(True)
        embed = discord.Embed(
            title="👻 GhostWipe Enabled",
            description=(
                "Departing members' messages will now be purged server-wide.\n\n"
                "• Set a log channel: `[p]ghostwipe logchannel #channel`\n"
                "• Review full config: `[p]ghostwipe settings`"
            ),
            colour=COLOUR_OK,
        )
        await ctx.send(embed=embed)

    @ghostwipe.command(name="disable", aliases=["off"])
    async def gw_disable(self, ctx: commands.Context):
        """Disable GhostWipe for this server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send(embed=discord.Embed(
            title="👻 GhostWipe Disabled", colour=COLOUR_INFO,
            description="GhostWipe will no longer act on member departures in this server.",
        ))

    @ghostwipe.command(name="logchannel", aliases=["log"])
    async def gw_logchannel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set or clear the channel GhostWipe sends its purge reports to."""
        if channel:
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            desc = f"Reports will be sent to {channel.mention}"
        else:
            await self.config.guild(ctx.guild).log_channel.set(None)
            desc = "Log channel cleared — reports are still saved to disk but not posted."
        await ctx.send(embed=discord.Embed(title="👻 Log Channel Updated", description=desc, colour=COLOUR_OK))

    @ghostwipe.command(name="trigger")
    async def gw_trigger(self, ctx: commands.Context, kind: str, toggle: bool):
        """Toggle whether a departure type triggers a purge.

        `kind` is one of `leave`, `kick`, `ban`.
        """
        kind = kind.lower()
        mapping = {"leave": "trigger_leave", "kick": "trigger_kick", "ban": "trigger_ban"}
        if kind not in mapping:
            return await ctx.send("❌ `kind` must be one of `leave`, `kick`, `ban`.")
        await getattr(self.config.guild(ctx.guild), mapping[kind]).set(toggle)
        state = "will" if toggle else "will NOT"
        await ctx.send(f"✅ Members who **{kind}** {state} have their messages purged.")

    @ghostwipe.group(name="whitelist")
    async def gw_whitelist(self, ctx: commands.Context):
        """Manage users who are never purged, no matter how they leave."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @gw_whitelist.command(name="add")
    async def gw_whitelist_add(self, ctx: commands.Context, user: discord.User):
        async with self.config.guild(ctx.guild).whitelist_users() as ids:
            if user.id not in ids:
                ids.append(user.id)
        await ctx.send(f"✅ **{user}** is now whitelisted and will never be purged.")

    @gw_whitelist.command(name="remove")
    async def gw_whitelist_remove(self, ctx: commands.Context, user: discord.User):
        async with self.config.guild(ctx.guild).whitelist_users() as ids:
            if user.id in ids:
                ids.remove(user.id)
        await ctx.send(f"✅ **{user}** removed from the whitelist.")

    @gw_whitelist.command(name="list")
    async def gw_whitelist_list(self, ctx: commands.Context):
        ids = await self.config.guild(ctx.guild).whitelist_users()
        if not ids:
            return await ctx.send("No whitelisted users.")
        await ctx.send("Whitelisted users:\n" + "\n".join(f"<@{i}> (`{i}`)" for i in ids))

    @ghostwipe.group(name="ignorerole")
    async def gw_ignorerole(self, ctx: commands.Context):
        """Manage roles that exempt a member from being purged."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @gw_ignorerole.command(name="add")
    async def gw_ignorerole_add(self, ctx: commands.Context, role: discord.Role):
        async with self.config.guild(ctx.guild).ignore_roles() as ids:
            if role.id not in ids:
                ids.append(role.id)
        await ctx.send(f"✅ Members with **{role.name}** will no longer be purged on departure.")

    @gw_ignorerole.command(name="remove")
    async def gw_ignorerole_remove(self, ctx: commands.Context, role: discord.Role):
        async with self.config.guild(ctx.guild).ignore_roles() as ids:
            if role.id in ids:
                ids.remove(role.id)
        await ctx.send(f"✅ **{role.name}** removed from the ignore list.")

    @gw_ignorerole.command(name="list")
    async def gw_ignorerole_list(self, ctx: commands.Context):
        ids = await self.config.guild(ctx.guild).ignore_roles()
        roles = [ctx.guild.get_role(i) for i in ids]
        roles = [r for r in roles if r]
        if not roles:
            return await ctx.send("No ignored roles.")
        await ctx.send("Ignored roles:\n" + "\n".join(r.mention for r in roles))

    @ghostwipe.group(name="ignorechannel")
    async def gw_ignorechannel(self, ctx: commands.Context):
        """Manage channels/threads GhostWipe never scans."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @gw_ignorechannel.command(name="add")
    async def gw_ignorechannel_add(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).ignored_channels() as ids:
            if channel.id not in ids:
                ids.append(channel.id)
        await ctx.send(f"✅ {channel.mention} will never be scanned.")

    @gw_ignorechannel.command(name="remove")
    async def gw_ignorechannel_remove(
        self, ctx: commands.Context,
        channel: Union[discord.TextChannel, discord.VoiceChannel, discord.Thread],
    ):
        async with self.config.guild(ctx.guild).ignored_channels() as ids:
            if channel.id in ids:
                ids.remove(channel.id)
        await ctx.send(f"✅ {channel.mention} removed from the ignore list.")

    @gw_ignorechannel.command(name="list")
    async def gw_ignorechannel_list(self, ctx: commands.Context):
        ids = await self.config.guild(ctx.guild).ignored_channels()
        if not ids:
            return await ctx.send("No ignored channels.")
        await ctx.send("Ignored channels:\n" + "\n".join(f"<#{i}>" for i in ids))

    @ghostwipe.command(name="scanlimit")
    async def gw_scanlimit(self, ctx: commands.Context, messages: str):
        """Set how many recent messages per channel to scan for the departing member.

        Pass a number, or `none` for unlimited (scans full channel history — slower).
        """
        if messages.lower() in ("none", "unlimited", "0"):
            await self.config.guild(ctx.guild).history_limit.set(0)
            return await ctx.send("✅ Scan limit set to **unlimited** (full channel history).")
        try:
            value = int(messages)
        except ValueError:
            return await ctx.send("❌ Provide a number, or `none` for unlimited.")
        if value < 1:
            return await ctx.send("❌ Must be a positive number, or `none` for unlimited.")
        await self.config.guild(ctx.guild).history_limit.set(value)
        await ctx.send(f"✅ Scan limit set to **{value}** messages per channel.")

    @ghostwipe.command(name="threads")
    async def gw_threads(self, ctx: commands.Context, toggle: bool):
        """Toggle whether active threads are scanned."""
        await self.config.guild(ctx.guild).include_threads.set(toggle)
        await ctx.send(f"✅ Thread scanning {'enabled' if toggle else 'disabled'}.")

    @ghostwipe.command(name="archivedthreads")
    async def gw_archivedthreads(self, ctx: commands.Context, toggle: bool):
        """Toggle whether archived threads are also scanned (slower, more thorough)."""
        await self.config.guild(ctx.guild).include_archived_threads.set(toggle)
        await ctx.send(f"✅ Archived thread scanning {'enabled' if toggle else 'disabled'}.")

    @ghostwipe.command(name="dryrun")
    async def gw_dryrun(self, ctx: commands.Context, toggle: bool):
        """Toggle dry-run mode: simulate and report, but never actually delete."""
        await self.config.guild(ctx.guild).dry_run.set(toggle)
        await ctx.send(f"✅ Dry-run mode {'enabled — nothing will be deleted' if toggle else 'disabled — purges are live'}.")

    @ghostwipe.command(name="delay")
    async def gw_delay(self, ctx: commands.Context, seconds: int):
        """Set a grace period (seconds) before purging starts.

        If the member rejoins within this window, the purge is cancelled. Use `0` to purge immediately.
        """
        if seconds < 0 or seconds > 3600:
            return await ctx.send("❌ Delay must be between 0 and 3600 seconds.")
        await self.config.guild(ctx.guild).delete_delay.set(seconds)
        await ctx.send(f"✅ Purge delay set to **{seconds}s**.")

    @ghostwipe.group(name="report")
    async def gw_report(self, ctx: commands.Context):
        """Configure the HTML report output."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @gw_report.command(name="content")
    async def gw_report_content(self, ctx: commands.Context, toggle: bool):
        """Toggle whether message content is shown in the report (off = redacted, counts/meta only)."""
        await self.config.guild(ctx.guild).reveal_content.set(toggle)
        await ctx.send(f"✅ Report content {'revealed' if toggle else 'redacted'}.")

    @gw_report.command(name="attach")
    async def gw_report_attach(self, ctx: commands.Context, toggle: bool):
        """Toggle whether the HTML report file is attached to the log message."""
        await self.config.guild(ctx.guild).attach_html_report.set(toggle)
        await ctx.send(f"✅ HTML report attachment {'enabled' if toggle else 'disabled (reports still saved to disk)'}.")

    @ghostwipe.command(name="retention")
    async def gw_retention(self, ctx: commands.Context, days: int):
        """Auto-delete saved report files after this many days. Use `0` to keep forever."""
        if days < 0:
            return await ctx.send("❌ Days must be 0 or greater.")
        await self.config.guild(ctx.guild).keep_reports_days.set(days)
        await ctx.send(f"✅ Report retention set to {'forever' if days == 0 else f'{days} days'}.")

    @ghostwipe.command(name="settings", aliases=["config", "status"])
    async def gw_settings(self, ctx: commands.Context):
        """View GhostWipe's full configuration for this server."""
        conf = await self.config.guild(ctx.guild).all()
        log_ch = ctx.guild.get_channel(conf["log_channel"]) if conf["log_channel"] else None
        roles = [ctx.guild.get_role(r) for r in conf["ignore_roles"]]
        roles = [r for r in roles if r]

        embed = discord.Embed(title="👻 GhostWipe Settings", colour=COLOUR_INFO, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Status", value="✅ Enabled" if conf["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Dry Run", value="✅" if conf["dry_run"] else "❌", inline=True)
        embed.add_field(name="Log Channel", value=log_ch.mention if log_ch else "Not set", inline=True)
        embed.add_field(
            name="Triggers",
            value=(
                f"Leave: {'✅' if conf['trigger_leave'] else '❌'} | "
                f"Kick: {'✅' if conf['trigger_kick'] else '❌'} | "
                f"Ban: {'✅' if conf['trigger_ban'] else '❌'}"
            ),
            inline=False,
        )
        embed.add_field(name="Purge Delay", value=f"{conf['delete_delay']}s", inline=True)
        embed.add_field(
            name="Scan Limit",
            value="Unlimited" if not conf["history_limit"] else f"{conf['history_limit']} msgs/channel",
            inline=True,
        )
        embed.add_field(name="Rate Limit Delay", value=f"{conf['rate_limit_delay']}s", inline=True)
        embed.add_field(name="Include Threads", value="✅" if conf["include_threads"] else "❌", inline=True)
        embed.add_field(name="Include Archived Threads", value="✅" if conf["include_archived_threads"] else "❌", inline=True)
        embed.add_field(name="Audit Log Window", value=f"{conf['audit_log_window']}s", inline=True)
        embed.add_field(name="Report Content", value="Revealed" if conf["reveal_content"] else "Redacted", inline=True)
        embed.add_field(name="Attach HTML Report", value="✅" if conf["attach_html_report"] else "❌", inline=True)
        embed.add_field(
            name="Report Retention",
            value="Forever" if not conf["keep_reports_days"] else f"{conf['keep_reports_days']} days",
            inline=True,
        )
        embed.add_field(name="Whitelisted Users", value=str(len(conf["whitelist_users"])), inline=True)
        embed.add_field(name="Ignored Roles", value=", ".join(r.mention for r in roles) or "None", inline=False)
        embed.add_field(name="Ignored Channels", value=str(len(conf["ignored_channels"])), inline=True)
        stats = conf["stats"]
        embed.add_field(
            name="Lifetime Stats",
            value=f"{humanize_number(stats.get('total_events', 0))} events, "
                  f"{humanize_number(stats.get('total_messages_deleted', 0))} messages deleted",
            inline=False,
        )
        embed.set_footer(text=f"GhostWipe v{self.__version__}")
        await ctx.send(embed=embed)

    @ghostwipe.command(name="history")
    async def gw_history(self, ctx: commands.Context, page: int = 1):
        """View recent GhostWipe purge events for this server."""
        history = await self.config.guild(ctx.guild).history()
        if not history:
            return await ctx.send("No GhostWipe events recorded yet.")

        per_page = 10
        history = list(reversed(history))
        total_pages = max(1, (len(history) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        chunk = history[(page - 1) * per_page: page * per_page]

        embed = discord.Embed(title="👻 GhostWipe History", colour=COLOUR_INFO)
        for entry in chunk:
            dry_tag = " (dry run)" if entry.get("dry_run") else ""
            embed.add_field(
                name=f"{REASON_LABEL.get(entry['reason'], entry['reason'].title())}{dry_tag} — {entry['member_display']}",
                value=(
                    f"`{entry['event_id']}` — {entry['messages_deleted']} messages across "
                    f"{entry['channels_affected']} channels\n{entry['timestamp'][:19]}"
                ),
                inline=False,
            )
        embed.set_footer(text=f"Page {page}/{total_pages} • Use `[p]ghostwipe viewreport <event_id>` to re-send a report")
        await ctx.send(embed=embed)

    @ghostwipe.command(name="viewreport")
    async def gw_viewreport(self, ctx: commands.Context, event_id: str):
        """Re-send a past purge event's HTML report from disk."""
        safe_id = "".join(c for c in event_id if c.isalnum() or c == "_")
        html_path = self._reports_dir(ctx.guild.id) / f"{safe_id}.html"
        if not html_path.exists():
            return await ctx.send("❌ No report found with that event ID. Check `[p]ghostwipe history`.")
        await ctx.send(file=discord.File(str(html_path), filename=f"ghostwipe_{safe_id}.html"))

    @ghostwipe.command(name="stats")
    async def gw_stats(self, ctx: commands.Context):
        """View lifetime GhostWipe stats for this server."""
        conf = await self.config.guild(ctx.guild).all()
        stats = conf["stats"]
        embed = discord.Embed(
            title="👻 GhostWipe Stats",
            colour=COLOUR_INFO,
            description=(
                f"**{humanize_number(stats.get('total_events', 0))}** purge events\n"
                f"**{humanize_number(stats.get('total_messages_deleted', 0))}** messages deleted"
            ),
        )
        await ctx.send(embed=embed)

    @ghostwipe.command(name="purge")
    async def gw_purge(self, ctx: commands.Context, user: discord.User, confirm: bool = False):
        """Manually trigger a purge for a user (bypasses trigger toggles).

        Still respects the whitelist and ignored roles (for current members). Requires
        `confirm=True` to actually run: `[p]ghostwipe purge @user True`.
        """
        conf = await self.config.guild(ctx.guild).all()
        if user.id in conf["whitelist_users"]:
            return await ctx.send("❌ That user is whitelisted and cannot be purged.")

        member = ctx.guild.get_member(user.id)
        if member:
            member_role_ids = {r.id for r in member.roles}
            if member_role_ids & set(conf["ignore_roles"]):
                return await ctx.send("❌ That member has an ignored role and cannot be purged.")

        if not confirm:
            return await ctx.send(
                f"⚠️ This will {'simulate deleting' if conf['dry_run'] else 'permanently delete'} "
                f"every message from **{user}** across this server.\n"
                f"Run `[p]ghostwipe purge {user.id} True` to confirm."
            )

        await ctx.send(f"👻 Starting manual purge for **{user}**... this may take a while.")
        avatar_url = user.display_avatar.url if user.display_avatar else ""
        await self._purge_member(
            ctx.guild, user, str(user), avatar_url, "manual", conf,
            moderator=str(ctx.author), mod_reason="Manual purge command",
        )
        await ctx.send(f"✅ Manual purge for **{user}** complete. Check the log channel or `[p]ghostwipe history`.")

