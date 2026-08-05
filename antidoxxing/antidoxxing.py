"""
AntiDoxxing Red Cog

Features:
- Listens to on_message and on_message_edit.
- Sanitization pipeline:
  1. Ignore bots
  2. Strip Discord markdown characters
  3. Remove invisible zero-width characters
  4. Homoglyph normalization (leet -> digits)
  5. Create numeric-only string by removing spaces, dots, dashes
- Detection for IPv4, IPv6, North American phone numbers, SSNs, and simple GPS coords.
- On detection: delete message and send a silent log to a configured moderation channel.
- Uses Config per guild (setmodchannel command).
"""

import re
import ipaddress
import logging
from typing import Optional

import discord
from redbot.core import commands, Config, checks

log = logging.getLogger("red.antidoxxing")


class AntiDoxxing(commands.Cog):
    """Detect and remove common doxxing attempts (IPv4, IPv6, phone, SSN, GPS)."""

    __version__ = "1.0.0"

    def __init__(self, bot):
        self.bot = bot
        # Unique identifier for Config; change if you fork to avoid collisions
        self.config = Config.get_conf(self, identifier=1234567890123, force_registration=True)
        self.config.register_guild(mod_channel=None)

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
        # Candidate digits for phone/ssn detection will be taken from numeric_text via \d runs

    # ---------- Commands ----------
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="setmodchannel", help="Set the moderation channel for antidoxxing logs. Use without args to unset.")
    async def setmodchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Set or unset the moderation channel where silent logs are posted."""
        guild = ctx.guild
        if channel is None:
            await self.config.guild(guild).mod_channel.set(None)
            await ctx.send("AntiDoxxing moderation channel unset. Logs will not be posted.")
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

            # HOMOGLYPH NORMALIZATION: map common letters to digits for detection
            # Create a normalized copy for detection only
            normalized = sanitized.translate(self._homoglyph_trans)

            # STRIP SPACES & PUNCTUATION: create numeric_text used for phone/SSN detection
            # Remove spaces, dots, and dashes (per requirements)
            numeric_text = re.sub(r"[ \.\-]", "", normalized)

            # Detection: gather flags and reasons to log
            violations = []

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
                        violations.append(("IPv4", ipv4_str))
                        break  # no need to find more IPv4 candidates
                    except Exception:
                        # not a valid IPv4, continue searching
                        continue

            # IPv6 detection:
            if not any(v[0] == "IPv6" for v in violations):
                for raw_candidate in self._ipv6_candidate_re.findall(normalized):
                    if ":" not in raw_candidate:
                        continue
                    # Keep reasonable length to avoid CPU waste
                    if len(raw_candidate) > 128:
                        continue
                    # Try validating via ipaddress
                    try:
                        # Strip surrounding non-hex/colon characters
                        candidate = raw_candidate.strip()
                        ipaddress.IPv6Address(candidate)
                        violations.append(("IPv6", candidate))
                        break
                    except Exception:
                        continue

            # GPS detection (simple float-pair detection)
            if not any(v[0] == "GPS" for v in violations):
                for lat_s, lon_s in self._gps_candidate_re.findall(normalized):
                    try:
                        lat = float(lat_s)
                        lon = float(lon_s)
                    except ValueError:
                        continue
                    # Validate ranges: latitude [-90, 90], longitude [-180, 180]
                    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                        violations.append(("GPS", f"{lat},{lon}"))
                        break

            # PHONE detection (North American): look for 10-digit or 11-digit numbers starting with 1
            if not any(v[0] == "Phone" for v in violations):
                for match in re.finditer(r"\d{10,11}", numeric_text):
                    digits = match.group(0)
                    if len(digits) == 10:
                        violations.append(("Phone", digits))
                        break
                    elif len(digits) == 11 and digits.startswith("1"):
                        violations.append(("Phone", digits))
                        break

            # SSN detection: 9-digit sequences, exclude invalid ranges
            if not any(v[0] == "SSN" for v in violations):
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
                    violations.append(("SSN", digits))
                    break

            # If anything flagged, take action
            if violations:
                # Attempt to delete the offending message
                try:
                    await message.delete()
                except discord.Forbidden:
                    # Bot lacks permissions to delete; still attempt to log
                    log.exception("Missing permission to delete message in %s", message.guild)
                except discord.NotFound:
                    # Message already deleted
                    pass
                except Exception:
                    log.exception("Unexpected error deleting message")

                # Send a silent log to the configured moderation channel (guild-specific)
                try:
                    mod_channel_id = await self.config.guild(message.guild).mod_channel()
                    if mod_channel_id:
                        mod_channel = message.guild.get_channel(mod_channel_id) or self.bot.get_channel(mod_channel_id)
                        if mod_channel and isinstance(mod_channel, discord.TextChannel):
                            # Build a concise, non-pinging log message
                            violation_lines = []
                            for vtype, val in violations:
                                violation_lines.append(f"- {vtype}: `{val}`")
                            author_str = f"{message.author} (ID: {message.author.id})"
                            jump_url = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
                            # Note: message is deleted already but link gives context for moderators when accessible
                            log_text = (
                                f"AntiDoxxing: message removed in #{message.channel.name} (ID: {message.channel.id})\n"
                                f"Author: {author_str}\n"
                                f"Reason(s):\n" + "\n".join(violation_lines) + "\n"
                                f"Original message content (sanitized copy):\n"
                                f"```{sanitized[:1900]}```\n"
                                f"Jump (may be unavailable if message deleted): {jump_url}"
                            )
                            # Send without mentioning the user (no @)
                            try:
                                await mod_channel.send(log_text)
                            except discord.Forbidden:
                                log.exception("Missing permission to send logs to mod channel %s", mod_channel)
                            except Exception:
                                log.exception("Failed to send mod log")
                        else:
                            # Configured ID not found or not a text channel
                            log.warning("Configured mod channel ID %s not found or not a text channel", mod_channel_id)
                    else:
                        # No mod channel configured; do nothing (or optionally log to bot owner)
                        log.debug("No anti-dox mod channel configured for guild %s", message.guild.id)
                except Exception:
                    log.exception("Error while attempting to log anti-dox action")
        except Exception:
            # Top-level protection so the bot doesn't crash from unexpected input
            log.exception("Unhandled error in AntiDoxxing._process_message")
