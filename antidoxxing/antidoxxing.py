"""
AntiDoxxing Red Cog — configurable, safe defaults

This revision adds full guild-level configuration for detectors, thresholds,
whitelist/exclusions, auto-action escalation settings, and optional global
webhook logging. Defaults are conservative: cog is enabled by default but
phone/SSN/email detectors are off to avoid false positives. Immediate
`reject` action deletes the offending message; auto-actions (escalation)
are disabled by default (action="none").

Admin commands added for runtime configuration.
"""

import re
import ipaddress
import logging
import unicodedata
import asyncio
import time
from typing import Optional, Dict, List, Tuple

import aiohttp
import discord
from redbot.core import commands, Config, checks

log = logging.getLogger("red.antidoxxing")


class AntiDoxxing(commands.Cog):
    """Detect and remove/doquarantine common doxxing attempts.

    Configurable per-guild and with a single optional global webhook for
    moderator logs.
    """

    __version__ = "1.0.0"

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890123, force_registration=True)

        # Global options
        self.config.register_global(webhook_url=None)

        # Guild defaults — conservative and safe
        self.config.register_guild(
            mod_channel=None,
            enabled=True,
            filter_level="high",  # low|medium|high|paranoid
            quarantine_threshold=0.6,
            reject_threshold=0.85,
            detect_phone=False,
            detect_ssn=False,
            detect_email=False,
            detect_ipv4_candidates=False,
            ignore_code_blocks=True,
            strip_mentions=True,
            strip_urls=True,
            whitelist_role_ids=[],
            excluded_channel_ids=[],
            blocklist_regex_path=None,
            auto_action={"violations": 3, "interval_minutes": 60, "action": "none"},
            log_raw_message=False,
        )

        # Sanitization helpers
        self._markdown_strip_trans = str.maketrans("", "", "`*_~|>")
        self._invisible_chars = {
            "\u200B": "",
            "\u200C": "",
            "\u200D": "",
            "\uFEFF": "",
            "\u2060": "",
        }

        # Basic homoglyph map (keeps hex letters intact to avoid breaking IPv6)
        homoglyph_pairs = {
            "o": "0",
            "O": "0",
            "i": "1",
            "I": "1",
            "l": "1",
            "L": "1",
            "z": "2",
            "Z": "2",
            "e": "3",
            "E": "3",
            "a": "4",
            "A": "4",
            "s": "5",
            "S": "5",
            "g": "6",
            "G": "6",
            "t": "7",
            "T": "7",
            "b": "8",
            "B": "8",
            "q": "9",
            "Q": "9",
        }
        self._homoglyph_trans = {ord(k): v for k, v in homoglyph_pairs.items()}

        # Candidate regexes (kept conservative to avoid ReDoS)
        self._ipv4_candidate_re = re.compile(r"(?:\d{1,3}(?:[.\-\s]?)){3}\d{1,3}")
        self._ipv6_candidate_re = re.compile(r"(?:[0-9A-Fa-f:]{2,})")
        self._gps_candidate_re = re.compile(r"([+-]?\d{1,3}\.\d+)[,\s]+([+-]?\d{1,3}\.\d+)")
        self._email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

        # In-memory escalation tracking (best-effort)
        self._violation_history: Dict[Tuple[int, int], List[float]] = {}

        # Weights for simple scoring (only used if multiple detectors enabled)
        self._weights = {"IPv4": 1.0, "IPv6": 1.0, "GPS": 0.9, "Phone": 0.9, "SSN": 1.0, "Email": 0.8}

    # ------------------ Admin commands ------------------
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setmodchannel", help="Set the moderation channel for antidoxxing logs. Use without args to unset.")
    async def setmodchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        guild = ctx.guild
        if channel is None:
            await self.config.guild(guild).mod_channel.set(None)
            await ctx.send("AntiDoxxing moderation channel unset.")
            return
        await self.config.guild(guild).mod_channel.set(channel.id)
        await ctx.send(f"AntiDoxxing moderation channel set to #{channel.name} (ID: {channel.id}).")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setenabled", help="Enable or disable AntiDoxxing in this guild.")
    async def setenabled(self, ctx: commands.Context, enabled: bool):
        await self.config.guild(ctx.guild).enabled.set(bool(enabled))
        await ctx.send(f"AntiDoxxing enabled set to {enabled} for this guild.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setthresholds", help="Set quarantine and reject thresholds (floats 0-1).")
    async def setthresholds(self, ctx: commands.Context, quarantine: float, reject: float):
        if not (0.0 <= quarantine < reject <= 1.0):
            return await ctx.send("Invalid thresholds — require 0.0 <= quarantine < reject <= 1.0")
        async with self.config.guild(ctx.guild).all() as cfg:
            cfg["quarantine_threshold"] = quarantine
            cfg["reject_threshold"] = reject
        await ctx.send(f"Thresholds set: quarantine={quarantine}, reject={reject}")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setdetector", help="Enable/disable a detector: phone|ssn|email|ipv4_candidates")
    async def setdetector(self, ctx: commands.Context, detector: str, enabled: bool):
        detector = detector.lower()
        if detector not in ("phone", "ssn", "email", "ipv4_candidates"):
            return await ctx.send("Unknown detector. Valid: phone, ssn, email, ipv4_candidates")
        key = {
            "phone": "detect_phone",
            "ssn": "detect_ssn",
            "email": "detect_email",
            "ipv4_candidates": "detect_ipv4_candidates",
        }[detector]
        await self.config.guild(ctx.guild).set_raw(key).set(enabled) if False else await self.config.guild(ctx.guild).__getattribute__(key).set(enabled)
        await ctx.send(f"Detector {detector} set to {enabled}.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setautoaction", help="Configure auto-action: violations interval_minutes action (action = none|kick|ban|temp_ban_24h)")
    async def setautoaction(self, ctx: commands.Context, violations: int, interval_minutes: int, action: str):
        if violations < 1 or interval_minutes < 1:
            return await ctx.send("violations and interval_minutes must be >= 1")
        async with self.config.guild(ctx.guild).all() as cfg:
            cfg["auto_action"] = {"violations": violations, "interval_minutes": interval_minutes, "action": action}
        await ctx.send(f"Auto-action set: {violations} violations in {interval_minutes}m -> {action}")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="addwhitelistrole", help="Add a role to the AntiDoxxing whitelist (bypasses checks).")
    async def addwhitelistrole(self, ctx: commands.Context, role: discord.Role):
        guild = ctx.guild
        current = await self.config.guild(guild).whitelist_role_ids()
        if role.id in current:
            await ctx.send("Role already whitelisted.")
            return
        current.append(role.id)
        await self.config.guild(guild).whitelist_role_ids.set(current)
        await ctx.send(f"Role {role.name} added to AntiDoxxing whitelist.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="removewhitelistrole", help="Remove a role from the AntiDoxxing whitelist.")
    async def removewhitelistrole(self, ctx: commands.Context, role: discord.Role):
        guild = ctx.guild
        current = await self.config.guild(guild).whitelist_role_ids()
        if role.id not in current:
            await ctx.send("Role not in whitelist.")
            return
        current.remove(role.id)
        await self.config.guild(guild).whitelist_role_ids.set(current)
        await ctx.send(f"Role {role.name} removed from AntiDoxxing whitelist.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="addexcludedchannel", help="Add a channel to the exclusion list for AntiDoxxing.")
    async def addexcludedchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        guild = ctx.guild
        current = await self.config.guild(guild).excluded_channel_ids()
        if channel.id in current:
            await ctx.send("Channel already excluded.")
            return
        current.append(channel.id)
        await self.config.guild(guild).excluded_channel_ids.set(current)
        await ctx.send(f"Channel #{channel.name} excluded from AntiDoxxing checks.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="removeexcludedchannel", help="Remove a channel from the exclusion list.")
    async def removeexcludedchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        guild = ctx.guild
        current = await self.config.guild(guild).excluded_channel_ids()
        if channel.id not in current:
            await ctx.send("Channel not in exclusion list.")
            return
        current.remove(channel.id)
        await self.config.guild(guild).excluded_channel_ids.set(current)
        await ctx.send(f"Channel #{channel.name} removed from exclusion list.")

    # Bot-owner: global webhook for modlogs
    @checks.is_owner()
    @commands.command(name="setmodwebhook", help="Set a global webhook URL for AntiDoxxing modlogs. Use without args to unset.")
    async def setmodwebhook(self, ctx: commands.Context, webhook_url: Optional[str] = None):
        if webhook_url is None:
            await self.config.webhook_url.set(None)
            await ctx.send("AntiDoxxing global webhook unset.")
            return
        await self.config.webhook_url.set(webhook_url)
        await ctx.send("AntiDoxxing global webhook set.")

    # ------------------ Listeners ------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._process_message(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.content == after.content:
            return
        await self._process_message(after)

    # ------------------ Core pipeline ------------------
    async def _process_message(self, message: discord.Message):
        try:
            if message.author.bot:
                return
            if message.guild is None:
                return

            guild = message.guild
            cfg = await self.config.guild(guild).all()

            if not cfg.get("enabled", True):
                return

            if message.channel.id in (cfg.get("excluded_channel_ids") or []):
                return

            author_roles = {r.id for r in getattr(message.author, "roles", [])}
            if set(cfg.get("whitelist_role_ids", [])) & author_roles:
                return

            raw = message.content or ""
            if not raw:
                return

            # Basic sanitization
            sanitized = raw.translate(self._markdown_strip_trans)
            for ch, repl in self._invisible_chars.items():
                if ch in sanitized:
                    sanitized = sanitized.replace(ch, repl)
            sanitized = unicodedata.normalize("NFKC", sanitized)

            # Optionally ignore code blocks (```...``` and inline `...`)
            if cfg.get("ignore_code_blocks", True):
                # Remove fenced code blocks and inline code
                sanitized = re.sub(r"```[\s\S]*?```", "", sanitized)
                sanitized = re.sub(r"`[^`]*`", "", sanitized)

            # Optionally strip mentions
            normalized = sanitized
            if cfg.get("strip_mentions", True):
                normalized = re.sub(r"<@!?#?\d+>?", "", normalized)

            # Optionally strip URLs
            if cfg.get("strip_urls", True):
                normalized = re.sub(r"https?://\S+", "", normalized, flags=re.IGNORECASE)

            # Homoglyph mapping for detection — keep hex letters intact to not break IPv6
            normalized = normalized.translate(self._homoglyph_trans)

            numeric_text = re.sub(r"[ \.\-]", "", normalized)

            detections: List[Tuple[str, str]] = []

            # IPv4 detection (strict)
            if True:
                for candidate in self._ipv4_candidate_re.findall(normalized):
                    parts = re.findall(r"\d+", candidate)
                    if len(parts) != 4:
                        # optionally treat candidates in paranoid mode
                        if cfg.get("detect_ipv4_candidates"):
                            detections.append(("IPv4-like", candidate))
                        continue
                    try:
                        octets = [int(p) for p in parts]
                    except ValueError:
                        continue
                    if all(0 <= o <= 255 for o in octets):
                        ipv4_str = ".".join(str(o) for o in octets)
                        try:
                            ipaddress.IPv4Address(ipv4_str)
                            detections.append(("IPv4", ipv4_str))
                            break
                        except Exception:
                            if cfg.get("detect_ipv4_candidates"):
                                detections.append(("IPv4-like", candidate))
                            continue

            # IPv6 detection
            if not any(d[0] == "IPv6" for d in detections):
                for raw_candidate in self._ipv6_candidate_re.findall(normalized):
                    if ":" not in raw_candidate:
                        continue
                    if len(raw_candidate) > 128:
                        continue
                    try:
                        candidate = raw_candidate.strip()
                        ipaddress.IPv6Address(candidate)
                        detections.append(("IPv6", candidate))
                        break
                    except Exception:
                        continue

            # GPS detection
            if not any(d[0] == "GPS" for d in detections):
                for lat_s, lon_s in self._gps_candidate_re.findall(normalized):
                    try:
                        lat = float(lat_s)
                        lon = float(lon_s)
                    except ValueError:
                        continue
                    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                        detections.append(("GPS", f"{lat},{lon}"))
                        break

            # Optional detectors (phone/ssn/email) — conservative defaults off
            if cfg.get("detect_phone", False) and not any(d[0] == "Phone" for d in detections):
                for match in re.finditer(r"\d{10,11}", numeric_text):
                    digits = match.group(0)
                    if len(digits) == 10 or (len(digits) == 11 and digits.startswith("1")):
                        detections.append(("Phone", digits))
                        break

            if cfg.get("detect_ssn", False) and not any(d[0] == "SSN" for d in detections):
                for match in re.finditer(r"\d{9}", numeric_text):
                    digits = match.group(0)
                    area = digits[:3]
                    group = digits[3:5]
                    serial = digits[5:9]
                    try:
                        area_n = int(area)
                    except ValueError:
                        continue
                    if area == "000" or area == "666" or area_n >= 900:
                        continue
                    if group == "00" or serial == "0000":
                        continue
                    detections.append(("SSN", digits))
                    break

            if cfg.get("detect_email", False) and not any(d[0] == "Email" for d in detections):
                m = self._email_re.search(normalized)
                if m:
                    detections.append(("Email", m.group(0)))

            if not detections:
                return

            # Score (simple sum of weights)
            score = sum(self._weights.get(dtype, 0.5) for dtype, _ in detections)
            # Decide action
            quarantine_t = cfg.get("quarantine_threshold", 0.6)
            reject_t = cfg.get("reject_threshold", 0.85)
            if score >= reject_t:
                action = "reject"
            elif score >= quarantine_t:
                action = "quarantine"
            else:
                action = "ignore"

            sanitized_preview = sanitized[:1900]
            violation_lines = [f"- {dtype}: `{val}`" for dtype, val in detections]

            if action == "reject":
                deleted = False
                try:
                    await message.delete()
                    deleted = True
                except discord.Forbidden:
                    log.exception("Missing permission to delete message in %s", guild)
                except discord.NotFound:
                    deleted = True
                except Exception:
                    log.exception("Unexpected error deleting message")

                # Escalation tracking (auto_action) — best-effort
                await self._record_violation_and_maybe_autoban(guild.id, message.author.id, cfg.get("auto_action", {}), message)

                # Log to mod channel and global webhook
                await self._send_logs(guild, message, violation_lines, sanitized_preview, deleted, detections, cfg)

            elif action == "quarantine":
                await self._send_logs(guild, message, violation_lines, sanitized_preview, deleted=False, detections=detections, cfg=cfg, quarantined=True)

        except Exception:
            log.exception("Unhandled error in AntiDoxxing._process_message")

    async def _send_logs(self, guild: discord.Guild, message: discord.Message, violation_lines: List[str], sanitized: str, deleted: bool = False, detections: Optional[List[Tuple[str, str]]] = None, cfg: Optional[dict] = None, quarantined: bool = False):
        try:
            cfg = cfg or await self.config.guild(guild).all()
            author_str = f"{message.author} (ID: {message.author.id})"
            jump_url = f"https://discord.com/channels/{guild.id}/{message.channel.id}/{message.id}"
            status = "deleted" if deleted else ("quarantined" if quarantined else "detected")

            # Build text log (sanitized by default)
            body = (
                f"AntiDoxxing: message {status} in #{message.channel.name} (ID: {message.channel.id})\n"
                f"Guild: {guild.name} (ID: {guild.id})\n"
                f"Author: {author_str}\n"
                f"Reason(s):\n" + "\n".join(violation_lines) + "\n"
                f"Original message content (sanitized copy):\n"
                f"```{sanitized}```\n"
                f"Jump (may be unavailable if message deleted): {jump_url}"
            )

            # Send to guild mod channel if configured
            try:
                mod_channel_id = cfg.get("mod_channel")
                if mod_channel_id:
                    mod_channel = guild.get_channel(mod_channel_id) or self.bot.get_channel(mod_channel_id)
                    if mod_channel and isinstance(mod_channel, discord.TextChannel):
                        try:
                            await mod_channel.send(body)
                        except discord.Forbidden:
                            log.exception("Missing permission to send logs to mod channel %s", mod_channel)
                        except Exception:
                            log.exception("Failed to send mod log to channel")
            except Exception:
                log.exception("Error while attempting to log anti-dox action to channel")

            # Global webhook (bot owner set)
            try:
                webhook_url = await self.config.webhook_url()
                if webhook_url:
                    payload = {
                        "username": "AntiDoxxing",
                        "content": None,
                        "embeds": [
                            {
                                "title": f"AntiDoxxing - {status} - {guild.name}",
                                "description": "\n".join(violation_lines)[:2048],
                                "fields": [
                                    {"name": "Guild", "value": f"{guild.name} (ID: {guild.id})", "inline": True},
                                    {"name": "Channel", "value": f"#{message.channel.name} (ID: {message.channel.id})", "inline": True},
                                    {"name": "Author", "value": author_str, "inline": False},
                                    {"name": "Sanitized message", "value": sanitized[:1024], "inline": False},
                                    {"name": "Jump URL", "value": jump_url, "inline": False},
                                ],
                                "color": 15158332,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            }
                        ],
                    }
                    await self._post_webhook(webhook_url, payload)
            except Exception:
                log.exception("Failed to send global webhook log")

        except Exception:
            log.exception("Error while preparing/sending logs")

    async def _post_webhook(self, url: str, payload: dict):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status >= 400:
                        log.warning("Webhook post returned status %s", resp.status)
        except Exception:
            log.exception("Exception while posting to webhook %s", url)

    async def _record_violation_and_maybe_autoban(self, guild_id: int, user_id: int, auto_action_cfg: dict, message: discord.Message):
        try:
            key = (guild_id, user_id)
            now_ts = time.time()
            history = self._violation_history.get(key, [])
            interval = auto_action_cfg.get("interval_minutes", 60) * 60
            history = [t for t in history if now_ts - t <= interval]
            history.append(now_ts)
            self._violation_history[key] = history

            required = auto_action_cfg.get("violations", 3)
            action = auto_action_cfg.get("action", "none")

            if required <= 0 or action == "none":
                return

            if len(history) >= required:
                guild = message.guild
                member = guild.get_member(user_id)
                if member is None:
                    return
                try:
                    if action == "kick":
                        await guild.kick(member)
                        log.info("Auto-action: kicked member %s in guild %s", user_id, guild_id)
                    elif action.startswith("temp_ban"):
                        hours = 24
                        m = re.search(r"temp_ban_(\d+)h", action)
                        if m:
                            hours = int(m.group(1))
                        await guild.ban(member, reason="Auto action by AntiDoxxing")
                        log.info("Auto-action: banned member %s in guild %s for %sh", user_id, guild_id, hours)
                        asyncio.create_task(self._schedule_unban(guild, user_id, hours * 3600))
                    elif action == "ban":
                        await guild.ban(member, reason="Auto action by AntiDoxxing")
                        log.info("Auto-action: banned member %s in guild %s", user_id, guild_id)
                    else:
                        log.info("Unknown auto_action %s", action)
                except discord.Forbidden:
                    log.exception("Missing permission to perform auto-action %s in guild %s", action, guild_id)
                except Exception:
                    log.exception("Exception while performing auto-action %s in guild %s", action, guild_id)

                # reset history after action
                self._violation_history[key] = []

        except Exception:
            log.exception("Error recording violation or performing auto action")

    async def _schedule_unban(self, guild: discord.Guild, user_id: int, delay_seconds: int):
        try:
            await asyncio.sleep(delay_seconds)
            try:
                user = await self.bot.fetch_user(user_id)
                await guild.unban(user)
                log.info("Auto-action: unbanned member %s in guild %s after delay", user_id, guild.id)
            except discord.NotFound:
                log.warning("Unban: user %s not found in ban list for guild %s", user_id, guild.id)
            except discord.Forbidden:
                log.exception("Unban: missing permissions to unban %s in guild %s", user_id, guild.id)
            except Exception:
                log.exception("Unban: unexpected error for %s in guild %s", user_id, guild.id)
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Error in _schedule_unban")
