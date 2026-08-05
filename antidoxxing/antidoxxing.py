"""
AntiDoxxing Red Cog

Features:
- Listens to on_message and on_message_edit.
- Sanitization pipeline:
  1. Ignore bots
  2. Strip Discord markdown characters
  3. Remove invisible zero-width characters
  4. Homoglyph normalization (leet -> digits)
  5. Unicode normalization and simple obfuscation replacements
  6. Create numeric-only string by removing spaces, dots, dashes
- Detection for IPv4, IPv6, phone, SSN, emails, and simple GPS coords.
- Scoring: weights per detection; quarantine vs reject thresholds.
- On reject: delete message and send a silent log to a configured moderation channel and/or a global webhook.
- Quarantine: do not delete; send to mod channel/webhook for review.
- Guild-level config: enabled, thresholds, whitelist roles, excluded channels, auto-action.
- Global config: single webhook URL for all guilds.
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
    """Detect and remove common doxxing attempts (IPv4, IPv6, phone, SSN, GPS, email).

    Provides guild-level config and a single global webhook for modlogs.
    """

    __version__ = "1.1.0"

    def __init__(self, bot):
        self.bot = bot
        # Unique identifier for Config; change if you fork to avoid collisions
        self.config = Config.get_conf(self, identifier=1234567890123, force_registration=True)

        # Global config (one webhook for all guilds)
        self.config.register_global(webhook_url=None)

        # Guild-specific config
        self.config.register_guild(
            mod_channel=None,
            enabled=True,
            filter_level="high",  # low|medium|high|paranoid
            quarantine_threshold=0.6,
            reject_threshold=0.85,
            whitelist_role_ids=[],
            excluded_channel_ids=[],
            auto_action={"violations": 3, "interval_minutes": 60, "action": "temp_ban_24h"},
        )

        # Precompute translation maps and regex candidates
        # Characters to strip for discord markdown formatting
        self._markdown_strip_trans = str.maketrans("", "", "`*_~|>")

        # Zero-width and invisible characters to remove
        self._invisible_chars = {
            "\u200B": "",
            "\u200C": "",
            "\u200D": "",
            "\uFEFF": "",
            "\u2060": "",
        }

        # Homoglyph (leet/homoglyph) mapping: letters -> digits (both cases)
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

        # Regexes to find candidate sequences (kept small/simple to avoid ReDoS)
        # Candidate IPv4-like sequences: digits separated by ., -, or whitespace (at least 3 separators)
        self._ipv4_candidate_re = re.compile(r"(?:\d{1,3}(?:[.\-\s]?)){3}\d{1,3}")
        # Candidate IPv6-like candidate: contains colon and hex characters
        self._ipv6_candidate_re = re.compile(r"(?:[0-9A-Fa-f:]{2,})")
        # Candidate GPS: float pairs with a comma or whitespace separator (simple)
        self._gps_candidate_re = re.compile(r"([+-]?\d{1,3}\.\d+)[,\s]+([+-]?\d{1,3}\.\d+)")
        # Email regex (simple and safe)
        self._email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

        # In-memory recent violation tracking: (guild_id, user_id) -> list[timestamp_seconds]
        self._violation_history: Dict[Tuple[int, int], List[float]] = {}

        # Scoring weights (tuneable)
        self._weights = {
            "IPv4": 1.0,
            "IPv6": 1.0,
            "GPS": 0.9,
            "Phone": 0.9,
            "SSN": 1.0,
            "Email": 0.8,
        }

    # ---------- Administrative Commands ----------
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setmodchannel", help="Set the moderation channel for antidoxxing logs. Use without args to unset.")
    async def setmodchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Set or unset the moderation channel where silent logs are posted."""
        guild = ctx.guild
        if channel is None:
            await self.config.guild(guild).mod_channel.set(None)
            await ctx.send("AntiDoxxing moderation channel unset. Logs will not be posted to a channel.")
            return
        # Save channel ID
        await self.config.guild(guild).mod_channel.set(channel.id)
        await ctx.send(f"AntiDoxxing moderation channel set to #{channel.name} (ID: {channel.id}).")

    @commands.guild_only()
    @commands.command(name="showmodchannel", help="Show configured moderation channel for antidoxxing logs.")
    async def showmodchannel(self, ctx: commands.Context):
        """Show the current moderation channel setting."""
        guild = ctx.guild
        channel_id = await self.config.guild(guild).mod_channel()
        if channel_id:
            ch = guild.get_channel(channel_id) or self.bot.get_channel(channel_id)
            if ch:
                await ctx.send(f"AntiDoxxing logs go to #{ch.name} (ID: {channel_id}).")
                return
            # channel not found
            await ctx.send(f"Configured moderation channel ID {channel_id} not found in this bot's cache.")
            return
        await ctx.send("No moderation channel configured for AntiDoxxing.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setenabled", help="Enable or disable AntiDoxxing in this guild.")
    async def setenabled(self, ctx: commands.Context, enabled: bool):
        guild = ctx.guild
        await self.config.guild(guild).enabled.set(bool(enabled))
        await ctx.send(f"AntiDoxxing enabled set to {enabled} for this guild.")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="addwhitelistrole", help="Add a role to the Antidoxxing whitelist (bypasses checks).")
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
    @commands.command(name="removewhitelistrole", help="Remove a role from the Antidoxxing whitelist.")
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
    @commands.command(name="listexcludedchannels", help="List channels excluded from Antidoxxing.")
    async def listexcludedchannels(self, ctx: commands.Context):
        guild = ctx.guild
        current = await self.config.guild(guild).excluded_channel_ids()
        if not current:
            await ctx.send("No channels excluded.")
            return
        lines = []
        for cid in current:
            ch = guild.get_channel(cid) or self.bot.get_channel(cid)
            if ch:
                lines.append(f"- {ch.name} (ID: {cid})")
            else:
                lines.append(f"- Unknown channel ID: {cid}")
        await ctx.send("Excluded channels:\n" + "\n".join(lines))

    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="addexcludedchannel", help="Add a channel to the exclusion list for Antidoxxing.")
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

    # Global webhook setter - bot owner only
    @checks.is_owner()
    @commands.command(name="setmodwebhook", help="Set a global webhook URL for AntiDoxxing modlogs. Use without args to unset.")
    async def setmodwebhook(self, ctx: commands.Context, webhook_url: Optional[str] = None):
        if webhook_url is None:
            await self.config.webhook_url.set(None)
            await ctx.send("AntiDoxxing global webhook unset.")
            return
        await self.config.webhook_url.set(webhook_url)
        await ctx.send("AntiDoxxing global webhook set.")

    @checks.is_owner()
    @commands.command(name="showmodwebhook", help="Show configured global webhook URL for AntiDoxxing (bot owner only).")
    async def showmodwebhook(self, ctx: commands.Context):
        url = await self.config.webhook_url()
        if url:
            await ctx.send(f"Global AntiDoxxing webhook: {url}")
        else:
            await ctx.send("No global webhook configured.")

    # ---------- Listeners ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Process new messages."""
        await self._process_message(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Process edited messages (checks the edited content)."""
        # Only process if the content actually changed
        if before.content == after.content:
            return
        await self._process_message(after)

    # ---------- Core processing ----------
    async def _process_message(self, message: discord.Message):
        """Full pipeline: sanitize -> detect -> action."""
        try:
            # 1) IGNORE BOTS: Skip messages from any bot, including ourselves
            if message.author.bot:
                return

            # Prefer to only operate in guilds (server messages)
            if message.guild is None:
                return

            guild = message.guild

            # Load guild config early for short-circuit
            guild_cfg = await self.config.guild(guild).all()
            enabled = guild_cfg.get("enabled", True)
            excluded_channels = guild_cfg.get("excluded_channel_ids", []) or []
            whitelist_roles = set(guild_cfg.get("whitelist_role_ids", []) or [])
            mod_channel_id = guild_cfg.get("mod_channel")
            quarantine_threshold = guild_cfg.get("quarantine_threshold", 0.6)
            reject_threshold = guild_cfg.get("reject_threshold", 0.85)
            auto_action_cfg = guild_cfg.get("auto_action", {"violations": 3, "interval_minutes": 60, "action": "temp_ban_24h"})

            if not enabled:
                return

            # Excluded channels
            if message.channel.id in excluded_channels:
                return

            # Whitelisted roles
            author_role_ids = {r.id for r in getattr(message.author, "roles", [])}
            if whitelist_roles & author_role_ids:
                return

            raw = message.content or ""
            if not raw:
                return

            # SANITIZE MARKDOWN: remove common markdown characters used to obfuscate content
            sanitized = raw.translate(self._markdown_strip_trans)

            # SANITIZE INVISIBLE CHARACTERS
            # Replace listed invisible characters with empty string
            for ch, repl in self._invisible_chars.items():
                if ch in sanitized:
                    sanitized = sanitized.replace(ch, repl)

            # UNICODE NORMALIZATION
            sanitized = unicodedata.normalize("NFKC", sanitized)

            # SIMPLE OBFS NORMALIZATION: common human obfuscations -> canonical
            lowered = sanitized
            replacements = [
                ("[at]", "@"),
                ("(at)", "@"),
                (" at ", "@"),
                ("\\s?\\[dot\\]\\s?", "."),
                (" dotcom", ".com"),
                (" dot ", "."),
            ]
            # apply simple replacements safely
            for a, b in replacements:
                try:
                    lowered = re.sub(a, b, lowered, flags=re.IGNORECASE)
                except re.error:
                    # fallback to plain replace if replacement pattern fails
                    lowered = lowered.replace(a, b)

            # REMOVE DISCORD MENTIONS: user/nick/role/channel mentions (including possible missing closing '>')
            # Patterns: <@123...>, <@!123...>, <@&123...>, <#123...>
            try:
                lowered = re.sub(r"<@!?\d+>?", "", lowered)
                lowered = re.sub(r"<@&\d+>?", "", lowered)
                lowered = re.sub(r"<#\d+>?", "", lowered)
            except re.error:
                # In the rare case regex fails, fallback to simple replacements for common prefixes
                lowered = lowered.replace("<@", "")
                lowered = lowered.replace("<#", "")

            # HOMOGLYPH NORMALIZATION: map common letters to digits for detection
            # Create a normalized copy for detection only
            normalized = lowered.translate(self._homoglyph_trans)

            # STRIP SPACES & PUNCTUATION: create numeric_text used for phone/SSN detection
            # Remove spaces, dots, and dashes (per requirements)
            numeric_text = re.sub(r"[ \\.\-]", "", normalized)

            # Detection: gather flags and reasons to log
            detections: List[Tuple[str, str]] = []

            # IPv4 detection:
            for candidate in self._ipv4_candidate_re.findall(normalized):
                # Extract numeric parts (split non-digit), expect 4 parts
                parts = re.findall(r"\d+", candidate)
                if len(parts) != 4:
                    continue
                try:
                    octets = [int(p) for p in parts]
                except ValueError:
                    continue
                # Validate each octet in 0-255
                if all(0 <= o <= 255 for o in octets):
                    # Reconstruct dotted IPv4 and validate via ipaddress for extra safety
                    ipv4_str = ".".join(str(o) for o in octets)
                    try:
                        ipaddress.IPv4Address(ipv4_str)
                        detections.append(("IPv4", ipv4_str))
                        break  # no need to find more IPv4 candidates
                    except Exception:
                        # not a valid IPv4, continue searching
                        continue

            # IPv6 detection:
            if not any(d[0] == "IPv6" for d in detections):
                for raw_candidate in self._ipv6_candidate_re.findall(normalized):
                    if ":" not in raw_candidate:
                        continue
                    # Keep reasonable length to avoid CPU waste
                    if len(raw_candidate) > 128:
                        continue
                    # Try validating via ipaddress
                    try:
                        candidate = raw_candidate.strip()
                        ipaddress.IPv6Address(candidate)
                        detections.append(("IPv6", candidate))
                        break
                    except Exception:
                        continue

            # GPS detection (simple float-pair detection)
            if not any(d[0] == "GPS" for d in detections):
                for lat_s, lon_s in self._gps_candidate_re.findall(normalized):
                    try:
                        lat = float(lat_s)
                        lon = float(lon_s)
                    except ValueError:
                        continue
                    # Validate ranges: latitude [-90, 90], longitude [-180, 180]
                    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                        detections.append(("GPS", f"{lat},{lon}"))
                        break

            # PHONE detection (North American): look for 10-digit or 11-digit numbers starting with 1
            if not any(d[0] == "Phone" for d in detections):
                for match in re.finditer(r"\d{10,11}", numeric_text):
                    digits = match.group(0)
                    if len(digits) == 10:
                        detections.append(("Phone", digits))
                        break
                    elif len(digits) == 11 and digits.startswith("1"):
                        detections.append(("Phone", digits))
                        break

            # SSN detection: 9-digit sequences, exclude invalid ranges
            if not any(d[0] == "SSN" for d in detections):
                for match in re.finditer(r"\d{9}", numeric_text):
                    digits = match.group(0)
                    # Basic SSN invalid checks
                    area = digits[:3]
                    group = digits[3:5]
                    serial = digits[5:9]
                    try:
                        area_n = int(area)
                    except ValueError:
                        continue
                    # Exclude invalid starting blocks: 000, 666, 900-999
                    if area == "000" or area == "666" or area_n >= 900:
                        continue
                    # Exclude group or serial all-zero
                    if group == "00" or serial == "0000":
                        continue
                    # Looks like a valid SSN
                    detections.append(("SSN", digits))
                    break

            # EMAIL detection
            if not any(d[0] == "Email" for d in detections):
                for match in self._email_re.finditer(normalized):
                    addr = match.group(0)
                    detections.append(("Email", addr))
                    break

            # If nothing detected, return
            if not detections:
                return

            # Compute a simple score based on weights
            score = 0.0
            for dtype, _ in detections:
                score += self._weights.get(dtype, 0.5)
            # Normalize score (simple): divide by max possible weight (sum of weights of detected types but cap)
            # For decision we compare raw score vs thresholds tuned to these weights

            # Decide action based on thresholds
            if score >= reject_threshold:
                action = "reject"
            elif score >= quarantine_threshold:
                action = "quarantine"
            else:
                action = "ignore"

            # Build structured violation list for logs
            violation_lines = [f"- {dtype}: `{val}`" for dtype, val in detections]

            # Take actions
            if action == "reject":
                # Attempt to delete the offending message
                deleted = False
                try:
                    await message.delete()
                    deleted = True
                except discord.Forbidden:
                    log.exception("Missing permission to delete message in %s", message.guild)
                except discord.NotFound:
                    # Message already deleted
                    deleted = True
                except Exception:
                    log.exception("Unexpected error deleting message")

                # Record violation and potentially auto-act
                await self._record_violation_and_maybe_autoban(guild.id, message.author.id, auto_action_cfg, message)

                # Send logs to configured targets
                await self._send_logs(guild, message, violation_lines, sanitized, deleted, detections)

            elif action == "quarantine":
                # Do not delete but send detailed log for moderator review
                await self._send_logs(guild, message, violation_lines, sanitized, deleted=False, detections=detections, quarantined=True)

            else:
                # Shouldn't get here because we returned earlier if detections empty
                log.debug("Detection score below quarantine threshold; ignoring.")

        except Exception:
            # Top-level protection so the bot doesn't crash from unexpected input
            log.exception("Unhandled error in AntiDoxxing._process_message")

    async def _send_logs(self, guild: discord.Guild, message: discord.Message, violation_lines: List[str], sanitized: str, deleted: bool = False, detections: Optional[List[Tuple[str, str]]] = None, quarantined: bool = False):
        """Send logs to mod channel and/or global webhook. Webhook is a single global URL for all guilds."""
        try:
            # Prepare human-friendly info
            author_str = f"{message.author} (ID: {message.author.id})"
            jump_url = f"https://discord.com/channels/{guild.id}/{message.channel.id}/{message.id}"
            status = "deleted" if deleted else ("quarantined" if quarantined else "detected")

            log_text = (
                f"AntiDoxxing: message {status} in #{message.channel.name} (ID: {message.channel.id})\n"
                f"Guild: {guild.name} (ID: {guild.id})\n"
                f"Author: {author_str}\n"
                f"Reason(s):\n" + "\n".join(violation_lines) + "\n"
                f"Original message content (sanitized copy):\n"
                f"```{sanitized[:1900]}```\n"
                f"Jump (may be unavailable if message deleted): {jump_url}"
            )

            # Send to configured mod channel if present
            try:
                mod_channel_id = await self.config.guild(guild).mod_channel()
                if mod_channel_id:
                    mod_channel = guild.get_channel(mod_channel_id) or self.bot.get_channel(mod_channel_id)
                    if mod_channel and isinstance(mod_channel, discord.TextChannel):
                        try:
                            await mod_channel.send(log_text)
                        except discord.Forbidden:
                            log.exception("Missing permission to send logs to mod channel %s", mod_channel)
                        except Exception:
                            log.exception("Failed to send mod log to channel")
                    else:
                        log.warning("Configured mod channel ID %s not found or not a text channel", mod_channel_id)
                else:
                    log.debug("No anti-dox mod channel configured for guild %s", guild.id)
            except Exception:
                log.exception("Error while attempting to log anti-dox action to channel")

            # Send to global webhook if configured
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
        """POST a JSON payload to the configured webhook URL. Fire-and-forget with basic error handling."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status >= 400:
                        log.warning("Webhook post returned status %s", resp.status)
        except Exception:
            log.exception("Exception while posting to webhook %s", url)

    async def _record_violation_and_maybe_autoban(self, guild_id: int, user_id: int, auto_action_cfg: dict, message: discord.Message):
        """Record a violation and perform auto_action if thresholds are exceeded."""
        try:
            key = (guild_id, user_id)
            now_ts = time.time()
            history = self._violation_history.get(key, [])
            # purge old entries
            interval = auto_action_cfg.get("interval_minutes", 60) * 60
            history = [t for t in history if now_ts - t <= interval]
            history.append(now_ts)
            self._violation_history[key] = history

            required = auto_action_cfg.get("violations", 3)
            action = auto_action_cfg.get("action", "temp_ban_24h")

            if len(history) >= required:
                # attempt action
                guild = message.guild
                member = guild.get_member(user_id)
                if member is None:
                    # cannot act if member not in cache
                    return
                try:
                    if action == "kick":
                        await guild.kick(member)
                        log.info("Auto-action: kicked member %s in guild %s", user_id, guild_id)
                    elif action.startswith("temp_ban"):
                        # parse optional duration in hours e.g. temp_ban_24h
                        hours = 24
                        m = re.search(r"temp_ban_(\d+)h", action)
                        if m:
                            hours = int(m.group(1))
                        await guild.ban(member, reason="Auto action by AntiDoxxing")
                        log.info("Auto-action: banned member %s in guild %s for %sh", user_id, guild_id, hours)

                        # schedule unban after duration (best-effort; will not survive restarts)
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
        """Unban a user after delay_seconds (best-effort)."""
        try:
            await asyncio.sleep(delay_seconds)
            # attempt unban
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
            # task cancelled on shutdown
            return
        except Exception:
            log.exception("Error in _schedule_unban")
