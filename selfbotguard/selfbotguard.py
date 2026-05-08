"""
SelfbotGuard v1.0.0 — Advanced Selfbot Detection & Punishment
================================================================
Cog for Red-DiscordBot.

Detection heuristics:
  1. Rich-embed abuse      — User accounts cannot send rich embeds via the client.
  2. Response-time analysis — Inhuman reply speeds (< 300ms consistently).
  3. Timing precision       — Messages at exact intervals (variance < 50ms).
  4. Activity profiling     — 24/7 activity across all hours without gaps.
  5. Pattern matching       — Automated prefix→response command patterns.
  6. Burst detection        — Rapid-fire messages exceeding human typing speed.
  7. Cross-channel spam     — Same message in multiple channels simultaneously.
  8. Cross-server activity  — Messages in different servers within impossible windows.
  9. Edit cadence            — Precise, consistent message edit timing.
  11. Reaction sniping      — Adding reactions within milliseconds of a post.
  12. Formatting analysis   — Suspiciously clean structured output at inhuman speed.
  13. Token-snipe triggers  — Instantly responding to specific trigger words.
  14. Self-delete patterns  — Send → wait exact N seconds → delete.

Each heuristic contributes to a cumulative suspicion score. When the score
exceeds the server's threshold, the configured action is taken.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Deque, List, Optional, Set, Tuple

import discord
from discord import app_commands
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

log = logging.getLogger("red.selfbotguard")

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

# Heuristic weights (how much each detection adds to suspicion score)
WEIGHT_RICH_EMBED       = 40   # Very strong signal
WEIGHT_RESPONSE_SPEED   = 15   # Per fast-response instance
WEIGHT_TIMING_PRECISION = 20   # Consistent intervals
WEIGHT_ACTIVITY_247     = 25   # Active across all hour buckets
WEIGHT_PATTERN_MATCH    = 15   # Command-response patterns
WEIGHT_BURST            = 10   # Rapid-fire messages
WEIGHT_CROSS_CHANNEL    = 35   # Same message blasted across channels
WEIGHT_CROSS_SERVER     = 30   # Active in multiple guilds simultaneously
WEIGHT_EDIT_CADENCE     = 20   # Precise edit timing

WEIGHT_REACTION_SNIPE   = 20   # Instant reactions
WEIGHT_CLEAN_FORMAT     = 15   # Suspiciously clean output at speed
WEIGHT_TOKEN_SNIPE      = 30   # Instant response to trigger words
WEIGHT_SELF_DELETE      = 25   # Timed self-deletion patterns

# Thresholds for heuristics
RESPONSE_TIME_FLOOR_MS  = 300   # Faster than this = suspicious (ms)
TIMING_VARIANCE_CEIL_MS = 50    # Lower variance = more suspicious (ms)
BURST_MESSAGES          = 8     # Messages in burst window
BURST_WINDOW_SECS       = 3     # Window for burst detection (seconds)
ACTIVITY_HOUR_COVERAGE  = 20    # Out of 24 hours — if active in this many, suspicious
MIN_MESSAGES_FOR_TIMING = 10    # Need this many messages before timing analysis
MIN_RESPONSES_FOR_SPEED = 5     # Need this many fast responses before flagging
PATTERN_REPEAT_THRESHOLD= 5    # Same prefix→response pattern this many times
CROSS_CHAN_WINDOW_SECS  = 5     # Window for cross-channel spam detection
CROSS_CHAN_MIN_CHANNELS = 3     # Same msg in this many channels = selfbot
CROSS_CHAN_SIMILARITY   = 0.85  # Content similarity threshold (0-1)
CROSS_SERVER_WINDOW_SECS= 2     # Window for cross-server simultaneous activity
CROSS_SERVER_MIN_HITS   = 3     # This many near-simultaneous events to flag
MAX_CROSS_CHAN_HISTORY  = 50    # Rolling window of cross-channel entries per user
EDIT_VARIANCE_CEIL_MS   = 100   # Edit delay variance below this = suspicious
MIN_EDITS_FOR_CADENCE   = 5     # Need this many edits before analysing cadence
REACTION_SPEED_CEIL_MS  = 500   # Reaction faster than this = suspicious
MIN_FAST_REACTIONS      = 3     # This many fast reactions before flagging
CLEAN_FORMAT_MIN_LEN    = 200   # Minimum message length for formatting analysis
CLEAN_FORMAT_SPEED_CEIL = 5.0   # Seconds — structured msg this fast = suspicious
TRIGGER_WORDS           = {     # Common selfbot trigger words (lowercase)
    "giveaway", "nitro", "drop", "free", "claim", "airdrop",
    "discord.gift", "discord.gg", "dank memer", "pokétwo",
}
TRIGGER_RESPONSE_CEIL_MS= 1000  # Respond to trigger within this = suspicious
MIN_TRIGGER_HITS        = 3     # This many trigger-responses before flagging
SELF_DELETE_VARIANCE_MS = 200   # Variance of send→delete intervals below this = bot
MIN_SELF_DELETES        = 3     # This many patterned self-deletes before flagging

# Data retention
MAX_TIMESTAMPS_PER_USER = 200   # Rolling window of message timestamps
MAX_RESPONSE_PAIRS      = 100   # Rolling window of response-time pairs
SCORE_DECAY_HOURS       = 24    # Score decays fully over this period
PRUNE_INACTIVE_DAYS     = 7     # Prune user data after this many days inactive

# Sensitivity presets
SENSITIVITY_PRESETS = {
    "low":    {"score_threshold": 150, "description": "Fewer false positives, only catches obvious selfbots"},
    "medium": {"score_threshold": 100, "description": "Balanced detection — recommended for most servers"},
    "high":   {"score_threshold": 60,  "description": "Aggressive detection — may flag power users, review logs"},
}

# Action types
VALID_ACTIONS = ("log", "warn", "mute", "kick", "ban")

# Colours
COLOUR_ALERT  = discord.Colour.red()
COLOUR_WARN   = discord.Colour.orange()
COLOUR_INFO   = discord.Colour.blurple()
COLOUR_OK     = discord.Colour.green()


# ═══════════════════════════════════════════════════════════════
# User tracking dataclass
# ═══════════════════════════════════════════════════════════════

class UserProfile:
    """Tracks behavioural data for a single user in a guild."""

    __slots__ = (
        "user_id", "guild_id", "timestamps", "response_times_ms",
        "hour_buckets", "patterns", "bursts", "embed_strikes",
        "cross_channel_hits", "cross_server_hits",
        "edit_delays_ms", "fast_reactions",
        "trigger_responses", "self_delete_intervals",
        "score", "last_scored", "last_message_ts", "flagged",
        "action_taken", "last_active",
    )

    def __init__(self, user_id: int, guild_id: int):
        self.user_id = user_id
        self.guild_id = guild_id
        self.timestamps: Deque[float] = deque(maxlen=MAX_TIMESTAMPS_PER_USER)
        self.response_times_ms: Deque[float] = deque(maxlen=MAX_RESPONSE_PAIRS)
        self.hour_buckets: Set[int] = set()       # Hours (0-23) the user has been active
        self.patterns: Dict[str, int] = defaultdict(int)  # "prefix→response" counters
        self.bursts: int = 0                        # Number of burst events detected
        self.embed_strikes: int = 0                 # Rich embeds sent by non-bot user
        self.cross_channel_hits: int = 0            # Cross-channel spam events
        self.cross_server_hits: int = 0             # Cross-server simultaneous events
        self.edit_delays_ms: Deque[float] = deque(maxlen=50)  # Message edit delays

        self.fast_reactions: int = 0                # Reactions added inhumanly fast
        self.trigger_responses: int = 0             # Instant responses to trigger words
        self.self_delete_intervals: Deque[float] = deque(maxlen=50)  # Send→delete intervals
        self.score: float = 0.0
        self.last_scored: float = 0.0               # time.time() of last score calc
        self.last_message_ts: float = 0.0           # Timestamp of user's last message
        self.flagged: bool = False
        self.action_taken: Optional[str] = None
        self.last_active: float = time.time()

    def decay_score(self) -> float:
        """Apply time-based decay to the score."""
        if self.last_scored <= 0:
            return self.score
        elapsed_h = (time.time() - self.last_scored) / 3600
        if elapsed_h >= SCORE_DECAY_HOURS:
            self.score = 0.0
        else:
            decay = 1.0 - (elapsed_h / SCORE_DECAY_HOURS)
            self.score *= decay
        self.last_scored = time.time()
        return self.score


# ═══════════════════════════════════════════════════════════════
# The Cog
# ═══════════════════════════════════════════════════════════════

class SelfbotGuard(commands.Cog):
    """Advanced selfbot detection with per-server configurable punishments."""

    __version__ = "1.2.0"
    __author__ = ["everestmcarthur"]

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=58_310_627_41, force_registration=True)

        # Per-guild defaults
        self.config.register_guild(
            enabled=False,
            action="log",             # log | warn | mute | kick | ban
            sensitivity="medium",     # low | medium | high
            score_threshold=100,      # Override, or auto from sensitivity
            log_channel=None,         # Channel ID for alerts
            exempt_roles=[],          # Role IDs that bypass detection
            exempt_users=[],          # User IDs that bypass detection
            mute_duration=600,        # Seconds for mute/timeout (default 10min)
            flagged_users={},        # user_id -> {score, reason, timestamp}
            notify_staff=True,        # DM the guild owner on detection
            auto_prune=True,          # Auto-prune old tracking data
        )

        # In-memory tracking: guild_id -> user_id -> UserProfile
        self._profiles: Dict[int, Dict[int, UserProfile]] = defaultdict(dict)

        # Recent messages cache for response-time analysis
        # guild_id -> channel_id -> (author_id, timestamp, content_prefix)
        self._recent_messages: Dict[int, Dict[int, Tuple[int, float, str]]] = defaultdict(dict)

        # Cross-channel tracking: guild_id -> user_id -> deque of (channel_id, timestamp, content_hash)
        self._cross_channel: Dict[int, Dict[int, Deque[Tuple[int, float, str]]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=MAX_CROSS_CHAN_HISTORY))
        )

        # Cross-server tracking (GLOBAL, not per-guild):
        # user_id -> deque of (guild_id, timestamp)
        self._global_activity: Dict[int, Deque[Tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=100)
        )

        # Message send times for self-delete correlation:
        # message_id -> (author_id, guild_id, send_timestamp)
        self._message_send_times: Dict[int, Tuple[int, int, float]] = {}

        # Recent trigger messages per channel for token-snipe detection:
        # channel_id -> (trigger_word, timestamp)
        self._trigger_cache: Dict[int, Tuple[str, float]] = {}

        # Background task
        self._prune_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        """Start background tasks."""
        self._prune_task = self.bot.loop.create_task(self._prune_loop())
        log.info("SelfbotGuard v%s loaded.", self.__version__)

    async def cog_unload(self):
        """Clean up."""
        if self._prune_task and not self._prune_task.done():
            self._prune_task.cancel()
        log.info("SelfbotGuard unloaded.")

    # ── Helpers ──────────────────────────────────────────────

    def _get_profile(self, guild_id: int, user_id: int) -> UserProfile:
        """Get or create a UserProfile."""
        guild_profiles = self._profiles[guild_id]
        if user_id not in guild_profiles:
            guild_profiles[user_id] = UserProfile(user_id, guild_id)
        return guild_profiles[user_id]

    async def _is_exempt(self, member: discord.Member) -> bool:
        """Check if a member is exempt from detection."""
        if member.bot:
            return True  # Actual bots are not selfbots
        if member.guild_permissions.administrator:
            return True
        if member.id == member.guild.owner_id:
            return True

        guild_conf = await self.config.guild(member.guild).all()
        if member.id in guild_conf["exempt_users"]:
            return True
        member_role_ids = {r.id for r in member.roles}
        if member_role_ids & set(guild_conf["exempt_roles"]):
            return True
        return False

    async def _get_log_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Get the configured log channel."""
        ch_id = await self.config.guild(guild).log_channel()
        if ch_id:
            return guild.get_channel(ch_id)
        return None

    # ── Detection heuristics ─────────────────────────────────

    def _check_rich_embeds(self, message: discord.Message, profile: UserProfile) -> float:
        """
        Heuristic 1: Rich embeds from non-bot user accounts.

        The Discord client does NOT allow regular users to send rich embeds.
        URL unfurls (type='rich' with url field matching message content) are excluded.
        If a user account sends a genuine rich embed, it's almost certainly a selfbot.
        """
        if not message.embeds:
            return 0.0

        score = 0.0
        for embed in message.embeds:
            # Skip URL unfurls — these are normal
            if embed.type in ("image", "video", "gifv", "link", "article"):
                continue
            # If it's a "rich" embed, check if it's just a URL preview
            if embed.type == "rich":
                # URL unfurls typically have a url that matches something in message content
                if embed.url and embed.url in (message.content or ""):
                    continue
                # If embed has no title/description/fields, it's likely a provider embed
                if not embed.title and not embed.description and not embed.fields:
                    continue
                # This is a real rich embed from a user account — strong selfbot signal
                profile.embed_strikes += 1
                score += WEIGHT_RICH_EMBED
                log.debug(
                    "Rich embed detected from user %s in guild %s (strike %d)",
                    message.author.id, message.guild.id, profile.embed_strikes
                )
        return score

    def _check_response_speed(self, message: discord.Message, profile: UserProfile) -> float:
        """
        Heuristic 2: Inhuman response speed.

        If a user consistently responds to other users' messages in < 300ms,
        they're likely automated. We track response times per channel.
        """
        guild_id = message.guild.id
        channel_id = message.channel.id
        now = time.time()

        # Check if there's a recent message in this channel from someone else
        last = self._recent_messages.get(guild_id, {}).get(channel_id)
        if last and last[0] != message.author.id:
            response_ms = (now - last[1]) * 1000
            if response_ms < RESPONSE_TIME_FLOOR_MS:
                profile.response_times_ms.append(response_ms)

        # Update the recent message cache
        if guild_id not in self._recent_messages:
            self._recent_messages[guild_id] = {}
        content_prefix = (message.content or "")[:50]
        self._recent_messages[guild_id][channel_id] = (message.author.id, now, content_prefix)

        # Score based on accumulated fast responses
        fast_count = sum(1 for t in profile.response_times_ms if t < RESPONSE_TIME_FLOOR_MS)
        if fast_count >= MIN_RESPONSES_FOR_SPEED:
            return WEIGHT_RESPONSE_SPEED * (fast_count / MIN_RESPONSES_FOR_SPEED)
        return 0.0

    def _check_timing_precision(self, profile: UserProfile) -> float:
        """
        Heuristic 3: Message timing precision.

        Selfbots often send messages at very precise intervals (e.g., exactly
        every 5.000 seconds). We measure the variance of inter-message delays.
        Low variance = likely automated.
        """
        if len(profile.timestamps) < MIN_MESSAGES_FOR_TIMING:
            return 0.0

        timestamps = sorted(profile.timestamps)
        deltas = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps) - 1)]

        if not deltas:
            return 0.0

        # Filter out very large gaps (> 60s) — those are natural pauses
        active_deltas = [d for d in deltas if d < 60.0]
        if len(active_deltas) < 5:
            return 0.0

        mean = sum(active_deltas) / len(active_deltas)
        if mean <= 0:
            return 0.0
        variance_ms = (sum((d - mean) ** 2 for d in active_deltas) / len(active_deltas)) * 1000

        if variance_ms < TIMING_VARIANCE_CEIL_MS:
            # Very precise timing — scale score by how precise
            precision_factor = 1.0 - (variance_ms / TIMING_VARIANCE_CEIL_MS)
            return WEIGHT_TIMING_PRECISION * (1.0 + precision_factor)
        return 0.0

    def _check_activity_247(self, profile: UserProfile) -> float:
        """
        Heuristic 4: 24/7 activity profiling.

        Normal humans sleep. If a user has sent messages across 20+ distinct
        hours of the day, they're likely automated.
        """
        if len(profile.hour_buckets) >= ACTIVITY_HOUR_COVERAGE:
            coverage = len(profile.hour_buckets) / 24.0
            return WEIGHT_ACTIVITY_247 * coverage
        return 0.0

    def _check_patterns(self, message: discord.Message, profile: UserProfile) -> float:
        """
        Heuristic 5: Automated command-response patterns.

        Selfbots often respond with the same pattern to the same triggers.
        We track content prefixes and look for repetitive automated responses.
        """
        content = (message.content or "").strip()
        if not content or len(content) < 2:
            return 0.0

        # Build a simplified pattern key (first 30 chars, lowered)
        pattern_key = content[:30].lower()
        profile.patterns[pattern_key] += 1

        # Check for repeated patterns
        max_repeats = max(profile.patterns.values()) if profile.patterns else 0
        if max_repeats >= PATTERN_REPEAT_THRESHOLD:
            return WEIGHT_PATTERN_MATCH * (max_repeats / PATTERN_REPEAT_THRESHOLD)
        return 0.0

    def _check_burst(self, profile: UserProfile) -> float:
        """
        Heuristic 6: Rapid-fire burst detection.

        If a user sends BURST_MESSAGES+ messages within BURST_WINDOW_SECS,
        that exceeds normal human typing speed.
        """
        if len(profile.timestamps) < BURST_MESSAGES:
            return 0.0

        recent = sorted(profile.timestamps)[-BURST_MESSAGES:]
        window = recent[-1] - recent[0]
        if window <= BURST_WINDOW_SECS:
            profile.bursts += 1
            return WEIGHT_BURST * profile.bursts
        return 0.0

    @staticmethod
    def _content_hash(text: str) -> str:
        """Normalise and hash message content for cross-channel comparison."""
        # Strip whitespace, lower-case, remove common prefixes like bot commands
        normalised = text.strip().lower()
        # Use first 100 chars as the fingerprint — enough to detect copy-paste
        return normalised[:100]

    @staticmethod
    def _content_similar(a: str, b: str) -> float:
        """Quick similarity ratio between two content hashes (0.0 – 1.0)."""
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        # Character-level Jaccard similarity (fast, no imports)
        set_a, set_b = set(a), set(b)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union else 0.0

    def _check_cross_channel(self, message: discord.Message, profile: UserProfile) -> float:
        """
        Heuristic 7: Cross-channel spam.

        Selfbots blast the same (or near-identical) message across multiple
        channels simultaneously. A human can't paste the same message into
        3+ channels within 5 seconds. No exceptions.
        """
        content = (message.content or "").strip()
        if len(content) < 5:
            return 0.0

        guild_id = message.guild.id
        user_id = message.author.id
        channel_id = message.channel.id
        now = time.time()
        content_fp = self._content_hash(content)

        # Record this message
        user_cache = self._cross_channel[guild_id][user_id]
        user_cache.append((channel_id, now, content_fp))

        # Look back within the time window for similar content in OTHER channels
        cutoff = now - CROSS_CHAN_WINDOW_SECS
        channels_hit: Set[int] = set()
        for ch_id, ts, fp in user_cache:
            if ts >= cutoff and ch_id != channel_id:
                if self._content_similar(content_fp, fp) >= CROSS_CHAN_SIMILARITY:
                    channels_hit.add(ch_id)

        if len(channels_hit) >= (CROSS_CHAN_MIN_CHANNELS - 1):  # -1 because current channel counts
            profile.cross_channel_hits += 1
            channel_count = len(channels_hit) + 1  # Include current channel
            # Scale by how many channels — 3 channels is baseline, more = worse
            multiplier = channel_count / CROSS_CHAN_MIN_CHANNELS
            score = WEIGHT_CROSS_CHANNEL * multiplier * profile.cross_channel_hits
            log.debug(
                "Cross-channel spam: user %s in guild %s — %d channels in %ds (hit #%d)",
                user_id, guild_id, channel_count, CROSS_CHAN_WINDOW_SECS,
                profile.cross_channel_hits,
            )
            return score
        return 0.0

    def _check_cross_server(self, message: discord.Message, profile: UserProfile) -> float:
        """
        Heuristic 8: Cross-server simultaneous activity.

        The bot tracks user activity GLOBALLY across all guilds it monitors.
        If the same user sends messages in different servers within <2 seconds,
        repeatedly, that's physically impossible for a human (they'd need to
        switch servers, find a channel, type, and send). No exceptions.
        """
        user_id = message.author.id
        guild_id = message.guild.id
        now = time.time()

        # Record to global tracker
        self._global_activity[user_id].append((guild_id, now))

        # Check for messages in OTHER guilds within the window
        cutoff = now - CROSS_SERVER_WINDOW_SECS
        other_guilds: Set[int] = set()
        for g_id, ts in self._global_activity[user_id]:
            if ts >= cutoff and g_id != guild_id:
                other_guilds.add(g_id)

        if other_guilds:
            profile.cross_server_hits += 1
            if profile.cross_server_hits >= CROSS_SERVER_MIN_HITS:
                server_count = len(other_guilds) + 1  # Include current
                multiplier = server_count  # More servers = more suspicious
                score = WEIGHT_CROSS_SERVER * multiplier * (profile.cross_server_hits / CROSS_SERVER_MIN_HITS)
                log.debug(
                    "Cross-server activity: user %s — %d guilds within %ds (hit #%d)",
                    user_id, server_count, CROSS_SERVER_WINDOW_SECS,
                    profile.cross_server_hits,
                )
                return score
        return 0.0


    def _check_clean_formatting(self, message: discord.Message, profile: UserProfile) -> float:
        """
        Heuristic 12: Suspiciously clean formatted output at inhuman speed.

        Long messages with perfect markdown tables, structured formatting, zero
        typos, and code blocks that appear faster than any human could type.
        """
        content = message.content or ""
        if len(content) < CLEAN_FORMAT_MIN_LEN:
            return 0.0

        # Check speed — how fast since last message?
        now = time.time()
        if profile.last_message_ts > 0:
            gap = now - profile.last_message_ts
            if gap > CLEAN_FORMAT_SPEED_CEIL:
                return 0.0  # Took long enough to be human

        # Score structural indicators
        indicators = 0
        if "```" in content:
            indicators += 1  # Code blocks
        if "| " in content and " |" in content:
            indicators += 2  # Markdown tables
        if content.count("\n") > 10:
            indicators += 1  # Many lines
        if "**" in content and "__" in content:
            indicators += 1  # Mixed formatting

        # Check for zero-typo heuristic: ratio of dictionary-like words
        # (simplified: just check for consistent capitalisation patterns)
        lines = content.split("\n")
        if len(lines) > 5:
            # Structured: many lines start with same prefix pattern (bullet, number, etc.)
            prefixes = [line.strip()[:2] for line in lines if line.strip()]
            from collections import Counter
            prefix_counts = Counter(prefixes)
            if prefix_counts and prefix_counts.most_common(1)[0][1] > len(lines) * 0.5:
                indicators += 2  # Very structured repeated format

        if indicators >= 3:
            return WEIGHT_CLEAN_FORMAT * (indicators / 3)
        return 0.0

    def _check_trigger_snipe(self, message: discord.Message, profile: UserProfile) -> float:
        """
        Heuristic 13: Token-snipe / trigger-word response.

        Selfbots monitor for specific trigger words (giveaway, nitro, free, etc.)
        and respond instantly. We track when trigger words appear, then check if
        this user responded impossibly fast.
        """
        content_lower = (message.content or "").lower()
        channel_id = message.channel.id
        now = time.time()

        # First, check if THIS message contains trigger words (record for others)
        for word in TRIGGER_WORDS:
            if word in content_lower:
                self._trigger_cache[channel_id] = (word, now)
                break

        # Then, check if user is responding to a recent trigger
        cached = self._trigger_cache.get(channel_id)
        if cached:
            trigger_word, trigger_ts = cached
            response_ms = (now - trigger_ts) * 1000
            # Skip if this IS the trigger message itself
            if response_ms > 50 and response_ms < TRIGGER_RESPONSE_CEIL_MS:
                profile.trigger_responses += 1
                if profile.trigger_responses >= MIN_TRIGGER_HITS:
                    return WEIGHT_TOKEN_SNIPE * (profile.trigger_responses / MIN_TRIGGER_HITS)
        return 0.0

    async def _compute_score(self, message: discord.Message, profile: UserProfile) -> Tuple[float, List[str]]:
        """Run all heuristics and return (total_score, list_of_triggered_reasons)."""
        reasons = []

        # Apply decay first
        profile.decay_score()

        # Heuristic 1: Rich embeds
        s1 = self._check_rich_embeds(message, profile)
        if s1 > 0:
            reasons.append(f"Rich embed from user account (+{s1:.0f})")
            profile.score += s1

        # Heuristic 2: Response speed
        s2 = self._check_response_speed(message, profile)
        if s2 > 0:
            reasons.append(f"Inhuman response speed (<{RESPONSE_TIME_FLOOR_MS}ms) (+{s2:.0f})")
            profile.score += s2

        # Heuristic 3: Timing precision
        s3 = self._check_timing_precision(profile)
        if s3 > 0:
            reasons.append(f"Precise message timing (low variance) (+{s3:.0f})")
            profile.score += s3

        # Heuristic 4: 24/7 activity
        s4 = self._check_activity_247(profile)
        if s4 > 0:
            reasons.append(f"24/7 activity ({len(profile.hour_buckets)}/24 hours) (+{s4:.0f})")
            profile.score += s4

        # Heuristic 5: Pattern matching
        s5 = self._check_patterns(message, profile)
        if s5 > 0:
            reasons.append(f"Repetitive automated patterns (+{s5:.0f})")
            profile.score += s5

        # Heuristic 6: Burst detection
        s6 = self._check_burst(profile)
        if s6 > 0:
            reasons.append(f"Rapid-fire burst ({BURST_MESSAGES}+ msgs in {BURST_WINDOW_SECS}s) (+{s6:.0f})")
            profile.score += s6

        # Heuristic 7: Cross-channel spam
        s7 = self._check_cross_channel(message, profile)
        if s7 > 0:
            reasons.append(f"Cross-channel spam ({CROSS_CHAN_MIN_CHANNELS}+ channels in {CROSS_CHAN_WINDOW_SECS}s) (+{s7:.0f})")
            profile.score += s7

        # Heuristic 8: Cross-server simultaneous activity
        s8 = self._check_cross_server(message, profile)
        if s8 > 0:
            reasons.append(f"Cross-server simultaneous activity (<{CROSS_SERVER_WINDOW_SECS}s between guilds) (+{s8:.0f})")
            profile.score += s8

        # Heuristic 9: Edit cadence (scored in on_message_edit listener)
        if len(profile.edit_delays_ms) >= MIN_EDITS_FOR_CADENCE:
            delays = list(profile.edit_delays_ms)
            mean_d = sum(delays) / len(delays)
            if mean_d > 0:
                variance = sum((d - mean_d) ** 2 for d in delays) / len(delays)
                if variance < EDIT_VARIANCE_CEIL_MS:
                    s9 = WEIGHT_EDIT_CADENCE * (1.0 + (1.0 - variance / EDIT_VARIANCE_CEIL_MS))
                    reasons.append(f"Precise edit timing (variance {variance:.0f}ms) (+{s9:.0f})")
                    profile.score += s9


        # Heuristic 11: Fast reactions (scored in on_reaction_add listener)
        if profile.fast_reactions >= MIN_FAST_REACTIONS:
            s11 = WEIGHT_REACTION_SNIPE * (profile.fast_reactions / MIN_FAST_REACTIONS)
            reasons.append(f"Instant reactions (<{REACTION_SPEED_CEIL_MS}ms, {profile.fast_reactions}x) (+{s11:.0f})")
            profile.score += s11

        # Heuristic 12: Clean formatting at speed
        s12 = self._check_clean_formatting(message, profile)
        if s12 > 0:
            reasons.append(f"Suspiciously clean structured output at speed (+{s12:.0f})")
            profile.score += s12

        # Heuristic 13: Trigger-word sniping
        s13 = self._check_trigger_snipe(message, profile)
        if s13 > 0:
            reasons.append(f"Instant response to trigger words ({profile.trigger_responses}x) (+{s13:.0f})")
            profile.score += s13

        # Heuristic 14: Self-delete patterns (scored in on_message_delete listener)
        if len(profile.self_delete_intervals) >= MIN_SELF_DELETES:
            intervals = list(profile.self_delete_intervals)
            mean_i = sum(intervals) / len(intervals)
            if mean_i > 0:
                variance_i = sum((i - mean_i) ** 2 for i in intervals) / len(intervals)
                if variance_i < SELF_DELETE_VARIANCE_MS:
                    s14 = WEIGHT_SELF_DELETE * (1.0 + (1.0 - variance_i / SELF_DELETE_VARIANCE_MS))
                    reasons.append(f"Timed self-deletion pattern (variance {variance_i:.0f}ms) (+{s14:.0f})")
                    profile.score += s14

        profile.last_scored = time.time()
        return profile.score, reasons

    # ── Punishment execution ─────────────────────────────────

    async def _execute_action(
        self, member: discord.Member, action: str, score: float,
        reasons: List[str], mute_duration: int
    ) -> str:
        """Execute the configured punishment. Returns a status string."""
        reason_text = f"SelfbotGuard — score {score:.0f}: {'; '.join(reasons[:3])}"

        try:
            if action == "log":
                return "Logged (no action taken)"

            elif action == "warn":
                try:
                    embed = discord.Embed(
                        title="⚠️ SelfbotGuard Warning",
                        description=(
                            f"Your account has been flagged for automated behaviour in "
                            f"**{member.guild.name}**.\n\n"
                            f"If you believe this is an error, please contact the server staff."
                        ),
                        colour=COLOUR_WARN,
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.add_field(name="Suspicion Score", value=f"{score:.0f}", inline=True)
                    await member.send(embed=embed)
                except discord.Forbidden:
                    pass
                return "Warned via DM"

            elif action == "mute":
                duration = min(mute_duration, 2419200)  # Discord max: 28 days
                await member.timeout(
                    discord.utils.utcnow() + __import__("datetime").timedelta(seconds=duration),
                    reason=reason_text,
                )
                return f"Timed out for {duration}s"

            elif action == "kick":
                try:
                    embed = discord.Embed(
                        title="🚫 SelfbotGuard — Kicked",
                        description=(
                            f"You were kicked from **{member.guild.name}** for suspected "
                            f"selfbot activity.\nScore: {score:.0f}"
                        ),
                        colour=COLOUR_ALERT,
                    )
                    await member.send(embed=embed)
                except discord.Forbidden:
                    pass
                await member.kick(reason=reason_text)
                return "Kicked"

            elif action == "ban":
                try:
                    embed = discord.Embed(
                        title="🔨 SelfbotGuard — Banned",
                        description=(
                            f"You were banned from **{member.guild.name}** for suspected "
                            f"selfbot activity.\nScore: {score:.0f}"
                        ),
                        colour=COLOUR_ALERT,
                    )
                    await member.send(embed=embed)
                except discord.Forbidden:
                    pass
                await member.ban(reason=reason_text, delete_message_days=0)
                return "Banned"

        except discord.Forbidden:
            return f"Failed (missing permissions for {action})"
        except discord.HTTPException as e:
            return f"Failed ({e})"

        return "Unknown action"

    # ── Alert / logging ──────────────────────────────────────

    async def _send_alert(
        self, guild: discord.Guild, member: discord.Member,
        score: float, reasons: List[str], action_result: str
    ):
        """Send an alert to the log channel."""
        log_channel = await self._get_log_channel(guild)
        if not log_channel:
            return

        embed = discord.Embed(
            title="🛡️ SelfbotGuard Detection",
            colour=COLOUR_ALERT if "Ban" in action_result or "Kick" in action_result else COLOUR_WARN,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Score", value=f"**{score:.0f}**", inline=True)
        embed.add_field(name="Action", value=action_result, inline=True)
        embed.add_field(
            name="Triggered Heuristics",
            value="\n".join(f"• {r}" for r in reasons) or "None",
            inline=False,
        )
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        embed.add_field(name="Joined Server", value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True)
        embed.set_footer(text=f"SelfbotGuard v{self.__version__}")

        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass

        # Optionally DM guild owner
        conf = await self.config.guild(guild).all()
        if conf["notify_staff"] and guild.owner:
            try:
                owner_embed = discord.Embed(
                    title="🛡️ SelfbotGuard Alert",
                    description=(
                        f"A potential selfbot was detected in **{guild.name}**:\n"
                        f"**{member}** (`{member.id}`) — Score: {score:.0f}\n"
                        f"Action taken: {action_result}"
                    ),
                    colour=COLOUR_WARN,
                )
                await guild.owner.send(embed=owner_embed)
            except discord.Forbidden:
                pass

    # ── Persistence ──────────────────────────────────────────

    async def _save_flagged_user(self, guild: discord.Guild, profile: UserProfile, reasons: List[str]):
        """Persist flagged user to config."""
        async with self.config.guild(guild).flagged_users() as flagged:
            flagged[str(profile.user_id)] = {
                "score": round(profile.score, 1),
                "reasons": reasons[:5],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action_taken": profile.action_taken,
                "embed_strikes": profile.embed_strikes,
                "bursts": profile.bursts,
            }

    # ── Background prune task ────────────────────────────────

    async def _prune_loop(self):
        """Periodically prune stale user tracking data."""
        await self.bot.wait_until_ready()
        while True:
            try:
                await asyncio.sleep(3600)  # Every hour
                cutoff = time.time() - (PRUNE_INACTIVE_DAYS * 86400)
                pruned = 0
                for guild_id in list(self._profiles.keys()):
                    guild_profiles = self._profiles[guild_id]
                    stale = [
                        uid for uid, p in guild_profiles.items()
                        if p.last_active < cutoff and not p.flagged
                    ]
                    for uid in stale:
                        del guild_profiles[uid]
                        pruned += 1
                    if not guild_profiles:
                        del self._profiles[guild_id]
                if pruned:
                    log.debug("SelfbotGuard pruned %d stale user profiles.", pruned)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Error in SelfbotGuard prune loop")
                await asyncio.sleep(60)

    # ═════════════════════════════════════════════════════════
    # Event listener — the core detection loop
    # ═════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Analyse every message for selfbot indicators."""
        # Skip DMs, bot messages, messages without a guild
        if not message.guild or message.author.bot:
            return

        # Check if enabled
        guild = message.guild
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return

        member = message.author
        if not isinstance(member, discord.Member):
            return

        # Check exemptions
        if await self._is_exempt(member):
            return

        # Get / update profile
        profile = self._get_profile(guild.id, member.id)
        now = time.time()
        profile.timestamps.append(now)
        profile.hour_buckets.add(datetime.now(timezone.utc).hour)
        profile.last_active = now

        # Track message send time for self-delete correlation (heuristic 14)
        self._message_send_times[message.id] = (member.id, guild.id, now)
        # Prune old entries (keep last 1000)
        if len(self._message_send_times) > 1000:
            oldest_keys = sorted(self._message_send_times, key=lambda k: self._message_send_times[k][2])[:500]
            for k in oldest_keys:
                self._message_send_times.pop(k, None)

        # Run heuristics (note: last_message_ts is used by _check_clean_formatting)
        score, reasons = await self._compute_score(message, profile)

        # Update last_message_ts AFTER scoring (heuristic 12 needs the gap)
        profile.last_message_ts = now

        # Check threshold
        threshold = conf["score_threshold"]
        if score >= threshold and not profile.flagged:
            profile.flagged = True
            action = conf["action"]
            mute_duration = conf["mute_duration"]

            # Execute action
            action_result = await self._execute_action(member, action, score, reasons, mute_duration)
            profile.action_taken = action_result

            # Log and alert
            await self._send_alert(guild, member, score, reasons, action_result)
            await self._save_flagged_user(guild, profile, reasons)

            log.info(
                "SelfbotGuard flagged user %s in guild %s (score: %.0f, action: %s)",
                member.id, guild.id, score, action_result,
            )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Heuristic 9: Track edit timing cadence."""
        if not after.guild or after.author.bot:
            return
        conf = await self.config.guild(after.guild).all()
        if not conf["enabled"]:
            return
        member = after.author
        if not isinstance(member, discord.Member):
            return
        if await self._is_exempt(member):
            return

        # Calculate edit delay
        created_ts = before.created_at.timestamp()
        edited_ts = after.edited_at.timestamp() if after.edited_at else time.time()
        delay_ms = (edited_ts - created_ts) * 1000

        profile = self._get_profile(after.guild.id, member.id)
        profile.edit_delays_ms.append(delay_ms)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user):
        """Heuristic 11: Track reaction speed."""
        if not reaction.message.guild or user.bot:
            return
        if not isinstance(user, discord.Member):
            return
        conf = await self.config.guild(reaction.message.guild).all()
        if not conf["enabled"]:
            return
        if await self._is_exempt(user):
            return

        # How fast was the reaction added after the message was sent?
        msg_ts = reaction.message.created_at.timestamp()
        now = time.time()
        delay_ms = (now - msg_ts) * 1000

        if delay_ms < REACTION_SPEED_CEIL_MS:
            profile = self._get_profile(reaction.message.guild.id, user.id)
            profile.fast_reactions += 1
            log.debug(
                "Fast reaction from user %s in guild %s: %.0fms (count: %d)",
                user.id, reaction.message.guild.id, delay_ms, profile.fast_reactions,
            )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Heuristic 14: Track self-deletion patterns."""
        if not message.guild or message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return

        conf = await self.config.guild(message.guild).all()
        if not conf["enabled"]:
            return
        if await self._is_exempt(message.author):
            return

        # Check if this was tracked at send time
        send_info = self._message_send_times.pop(message.id, None)
        if send_info:
            author_id, guild_id, send_ts = send_info
            if author_id == message.author.id:
                delete_delay_ms = (time.time() - send_ts) * 1000
                profile = self._get_profile(guild_id, author_id)
                profile.self_delete_intervals.append(delete_delay_ms)

    # ═════════════════════════════════════════════════════════
    # Commands — Admin configuration
    # ═════════════════════════════════════════════════════════

    @commands.group(name="sbguard", aliases=["selfbotguard", "sbg"])
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def sbguard(self, ctx: commands.Context):
        """🛡️ SelfbotGuard — Advanced selfbot detection & punishment.

        Detects selfbots using behavioural heuristics and takes configurable action.
        Disabled by default — use `[p]sbguard enable` to activate.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @sbguard.command(name="enable", aliases=["on"])
    async def sbguard_enable(self, ctx: commands.Context):
        """Enable SelfbotGuard for this server."""
        await self.config.guild(ctx.guild).enabled.set(True)
        embed = discord.Embed(
            title="🛡️ SelfbotGuard Enabled",
            description=(
                "Selfbot detection is now **active** in this server.\n\n"
                "• Set a log channel: `[p]sbguard logchannel #channel`\n"
                "• Set the action: `[p]sbguard action <log|warn|mute|kick|ban>`\n"
                "• Adjust sensitivity: `[p]sbguard sensitivity <low|medium|high>`"
            ),
            colour=COLOUR_OK,
        )
        await ctx.send(embed=embed)

    @sbguard.command(name="disable", aliases=["off"])
    async def sbguard_disable(self, ctx: commands.Context):
        """Disable SelfbotGuard for this server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        embed = discord.Embed(
            title="🛡️ SelfbotGuard Disabled",
            description="Selfbot detection is now **inactive** in this server.",
            colour=COLOUR_INFO,
        )
        await ctx.send(embed=embed)

    @sbguard.command(name="action")
    async def sbguard_action(self, ctx: commands.Context, action: str):
        """Set the punishment action when a selfbot is detected.

        Valid actions: `log`, `warn`, `mute`, `kick`, `ban`
        """
        action = action.lower()
        if action not in VALID_ACTIONS:
            return await ctx.send(
                f"❌ Invalid action `{action}`. Choose from: {', '.join(f'`{a}`' for a in VALID_ACTIONS)}"
            )
        await self.config.guild(ctx.guild).action.set(action)

        action_descriptions = {
            "log": "📝 Detections will be logged but no action taken.",
            "warn": "⚠️ Users will be warned via DM.",
            "mute": "🔇 Users will be timed out.",
            "kick": "👢 Users will be kicked from the server.",
            "ban": "🔨 Users will be banned from the server.",
        }
        embed = discord.Embed(
            title=f"🛡️ Action Set: {action.title()}",
            description=action_descriptions[action],
            colour=COLOUR_OK,
        )
        await ctx.send(embed=embed)

    @sbguard.command(name="sensitivity")
    async def sbguard_sensitivity(self, ctx: commands.Context, level: str):
        """Set detection sensitivity: `low`, `medium`, or `high`.

        • **Low** — Score threshold 150. Fewer false positives, only catches obvious selfbots.
        • **Medium** — Score threshold 100. Balanced — recommended for most servers.
        • **High** — Score threshold 60. Aggressive — may flag power users, review logs carefully.
        """
        level = level.lower()
        if level not in SENSITIVITY_PRESETS:
            return await ctx.send(
                f"❌ Invalid level `{level}`. Choose from: {', '.join(f'`{l}`' for l in SENSITIVITY_PRESETS)}"
            )
        preset = SENSITIVITY_PRESETS[level]
        await self.config.guild(ctx.guild).sensitivity.set(level)
        await self.config.guild(ctx.guild).score_threshold.set(preset["score_threshold"])

        embed = discord.Embed(
            title=f"🛡️ Sensitivity: {level.title()}",
            description=f"{preset['description']}\nScore threshold: **{preset['score_threshold']}**",
            colour=COLOUR_OK,
        )
        await ctx.send(embed=embed)

    @sbguard.command(name="threshold")
    async def sbguard_threshold(self, ctx: commands.Context, value: int):
        """Set a custom score threshold (overrides sensitivity preset).

        Lower = more aggressive, higher = more lenient.
        Recommended range: 50-200.
        """
        if value < 10 or value > 500:
            return await ctx.send("❌ Threshold must be between 10 and 500.")
        await self.config.guild(ctx.guild).score_threshold.set(value)
        embed = discord.Embed(
            title="🛡️ Custom Threshold Set",
            description=f"Score threshold: **{value}**",
            colour=COLOUR_OK,
        )
        await ctx.send(embed=embed)

    @sbguard.command(name="logchannel", aliases=["log"])
    async def sbguard_logchannel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set or clear the log channel for SelfbotGuard alerts.

        Run without a channel to clear.
        """
        if channel:
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            embed = discord.Embed(
                title="🛡️ Log Channel Set",
                description=f"Alerts will be sent to {channel.mention}",
                colour=COLOUR_OK,
            )
        else:
            await self.config.guild(ctx.guild).log_channel.set(None)
            embed = discord.Embed(
                title="🛡️ Log Channel Cleared",
                description="No log channel configured. Set one with `[p]sbguard logchannel #channel`.",
                colour=COLOUR_INFO,
            )
        await ctx.send(embed=embed)

    @sbguard.command(name="muteduration", aliases=["timeout"])
    async def sbguard_muteduration(self, ctx: commands.Context, seconds: int):
        """Set the mute/timeout duration in seconds (default: 600 = 10 minutes).

        Max: 2419200 (28 days — Discord limit).
        """
        if seconds < 60:
            return await ctx.send("❌ Minimum mute duration is 60 seconds.")
        if seconds > 2419200:
            return await ctx.send("❌ Maximum mute duration is 2,419,200 seconds (28 days).")
        await self.config.guild(ctx.guild).mute_duration.set(seconds)
        mins = seconds // 60
        embed = discord.Embed(
            title="🛡️ Mute Duration Set",
            description=f"Timeout duration: **{seconds}s** (~{mins} minutes)",
            colour=COLOUR_OK,
        )
        await ctx.send(embed=embed)

    @sbguard.command(name="exempt")
    async def sbguard_exempt(self, ctx: commands.Context, target: discord.abc.Snowflake):
        """Add a role or user to the exempt list.

        Exempt members bypass all selfbot detection.
        Accepts a @role, @user, or raw ID.
        """
        # Check if it's a role or user
        if isinstance(target, discord.Role):
            async with self.config.guild(ctx.guild).exempt_roles() as roles:
                if target.id not in roles:
                    roles.append(target.id)
            await ctx.send(f"✅ Role **{target.name}** is now exempt from SelfbotGuard.")
        elif isinstance(target, (discord.Member, discord.User)):
            async with self.config.guild(ctx.guild).exempt_users() as users:
                if target.id not in users:
                    users.append(target.id)
            await ctx.send(f"✅ User **{target}** is now exempt from SelfbotGuard.")
        else:
            await ctx.send("❌ Please provide a valid @role or @user mention.")

    @sbguard.command(name="unexempt")
    async def sbguard_unexempt(self, ctx: commands.Context, target: discord.abc.Snowflake):
        """Remove a role or user from the exempt list."""
        if isinstance(target, discord.Role):
            async with self.config.guild(ctx.guild).exempt_roles() as roles:
                if target.id in roles:
                    roles.remove(target.id)
            await ctx.send(f"✅ Role **{target.name}** is no longer exempt.")
        elif isinstance(target, (discord.Member, discord.User)):
            async with self.config.guild(ctx.guild).exempt_users() as users:
                if target.id in users:
                    users.remove(target.id)
            await ctx.send(f"✅ User **{target}** is no longer exempt.")
        else:
            await ctx.send("❌ Please provide a valid @role or @user mention.")

    @sbguard.command(name="notifystaff", aliases=["notify"])
    async def sbguard_notifystaff(self, ctx: commands.Context, toggle: bool = None):
        """Toggle DM notifications to the guild owner on detection.

        Run without argument to toggle, or specify `true`/`false`.
        """
        current = await self.config.guild(ctx.guild).notify_staff()
        new_val = not current if toggle is None else toggle
        await self.config.guild(ctx.guild).notify_staff.set(new_val)
        state = "enabled" if new_val else "disabled"
        embed = discord.Embed(
            title=f"🛡️ Staff Notifications {state.title()}",
            description=f"DM notifications to the server owner are now **{state}**.",
            colour=COLOUR_OK,
        )
        await ctx.send(embed=embed)

    # ── Status / review commands ─────────────────────────────

    @sbguard.command(name="settings", aliases=["config", "status"])
    async def sbguard_settings(self, ctx: commands.Context):
        """View the current SelfbotGuard configuration for this server."""
        conf = await self.config.guild(ctx.guild).all()

        log_ch = ctx.guild.get_channel(conf["log_channel"]) if conf["log_channel"] else None
        exempt_roles = [ctx.guild.get_role(r) for r in conf["exempt_roles"] if ctx.guild.get_role(r)]
        exempt_users_str = ", ".join(f"<@{u}>" for u in conf["exempt_users"][:10]) or "None"

        embed = discord.Embed(
            title="🛡️ SelfbotGuard Settings",
            colour=COLOUR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Status", value="✅ Enabled" if conf["enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Action", value=conf["action"].title(), inline=True)
        embed.add_field(name="Sensitivity", value=conf["sensitivity"].title(), inline=True)
        embed.add_field(name="Score Threshold", value=str(conf["score_threshold"]), inline=True)
        embed.add_field(name="Mute Duration", value=f"{conf['mute_duration']}s", inline=True)
        embed.add_field(name="Notify Staff", value="✅" if conf["notify_staff"] else "❌", inline=True)
        embed.add_field(name="Log Channel", value=log_ch.mention if log_ch else "Not set", inline=True)
        embed.add_field(
            name="Exempt Roles",
            value=", ".join(r.mention for r in exempt_roles) or "None",
            inline=False,
        )
        embed.add_field(name="Exempt Users", value=exempt_users_str, inline=False)

        flagged_count = len(conf.get("flagged_users", {}))
        embed.add_field(name="Flagged Users", value=str(flagged_count), inline=True)

        # In-memory tracking stats
        guild_profiles = self._profiles.get(ctx.guild.id, {})
        embed.add_field(name="Tracking", value=f"{len(guild_profiles)} users", inline=True)

        embed.set_footer(text=f"SelfbotGuard v{self.__version__}")
        await ctx.send(embed=embed)

    @sbguard.command(name="flagged", aliases=["list", "suspects"])
    async def sbguard_flagged(self, ctx: commands.Context):
        """View all flagged users in this server."""
        flagged = await self.config.guild(ctx.guild).flagged_users()

        if not flagged:
            return await ctx.send("✅ No flagged users — SelfbotGuard hasn't detected any selfbots.")

        embed = discord.Embed(
            title="🛡️ Flagged Users",
            colour=COLOUR_WARN,
            timestamp=datetime.now(timezone.utc),
        )

        for uid, data in list(flagged.items())[:25]:
            reasons_str = "\n".join(f"  • {r}" for r in data.get("reasons", [])[:3])
            embed.add_field(
                name=f"<@{uid}> (`{uid}`)",
                value=(
                    f"**Score:** {data.get('score', 0)}\n"
                    f"**Action:** {data.get('action_taken', 'N/A')}\n"
                    f"**When:** {data.get('timestamp', 'N/A')[:19]}\n"
                    f"{reasons_str}"
                ),
                inline=False,
            )

        if len(flagged) > 25:
            embed.set_footer(text=f"Showing 25 of {len(flagged)} flagged users")
        else:
            embed.set_footer(text=f"SelfbotGuard v{self.__version__}")

        await ctx.send(embed=embed)

    @sbguard.command(name="unflag", aliases=["clear"])
    async def sbguard_unflag(self, ctx: commands.Context, user: discord.User):
        """Remove a user from the flagged list and reset their tracking data."""
        async with self.config.guild(ctx.guild).flagged_users() as flagged:
            if str(user.id) in flagged:
                del flagged[str(user.id)]
            else:
                return await ctx.send(f"❌ {user} is not in the flagged list.")

        # Reset in-memory profile
        guild_profiles = self._profiles.get(ctx.guild.id, {})
        if user.id in guild_profiles:
            del guild_profiles[user.id]

        await ctx.send(f"✅ **{user}** has been unflagged and their tracking data reset.")

    @sbguard.command(name="scan")
    async def sbguard_scan(self, ctx: commands.Context, user: discord.Member):
        """Manually check a user's current suspicion profile.

        Shows the live heuristic breakdown without triggering any action.
        """
        if user.bot:
            return await ctx.send("ℹ️ That's an actual bot account — SelfbotGuard only tracks user accounts.")

        profile = self._profiles.get(ctx.guild.id, {}).get(user.id)
        if not profile:
            return await ctx.send(f"ℹ️ No tracking data for **{user}** yet.")

        profile.decay_score()

        embed = discord.Embed(
            title=f"🔍 SelfbotGuard Scan — {user}",
            colour=COLOUR_INFO,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
        embed.add_field(name="Current Score", value=f"**{profile.score:.1f}**", inline=True)
        embed.add_field(name="Flagged", value="⚠️ Yes" if profile.flagged else "✅ No", inline=True)
        embed.add_field(name="Action Taken", value=profile.action_taken or "None", inline=True)
        embed.add_field(name="Messages Tracked", value=str(len(profile.timestamps)), inline=True)
        embed.add_field(name="Hour Coverage", value=f"{len(profile.hour_buckets)}/24", inline=True)
        embed.add_field(name="Embed Strikes", value=str(profile.embed_strikes), inline=True)
        embed.add_field(name="Fast Responses", value=str(len(profile.response_times_ms)), inline=True)
        embed.add_field(name="Burst Events", value=str(profile.bursts), inline=True)
        embed.add_field(name="Unique Patterns", value=str(len(profile.patterns)), inline=True)
        embed.add_field(name="Cross-Channel Hits", value=str(profile.cross_channel_hits), inline=True)
        embed.add_field(name="Cross-Server Hits", value=str(profile.cross_server_hits), inline=True)
        embed.add_field(name="Edit Cadence Samples", value=str(len(profile.edit_delays_ms)), inline=True)
        embed.add_field(name="Fast Reactions", value=str(profile.fast_reactions), inline=True)
        embed.add_field(name="Trigger Responses", value=str(profile.trigger_responses), inline=True)
        embed.add_field(name="Self-Deletes Tracked", value=str(len(profile.self_delete_intervals)), inline=True)

        threshold = await self.config.guild(ctx.guild).score_threshold()
        bar_len = 20
        fill = min(int((profile.score / threshold) * bar_len), bar_len)
        bar = "█" * fill + "░" * (bar_len - fill)
        embed.add_field(
            name="Threshold Progress",
            value=f"`[{bar}]` {profile.score:.0f}/{threshold}",
            inline=False,
        )

        embed.set_footer(text=f"SelfbotGuard v{self.__version__}")
        await ctx.send(embed=embed)

    @sbguard.command(name="reset")
    @commands.is_owner()
    async def sbguard_reset(self, ctx: commands.Context, confirm: bool = False):
        """⚠️ Reset ALL SelfbotGuard data for this server (owner only).

        Pass `True` to confirm: `[p]sbguard reset True`
        """
        if not confirm:
            return await ctx.send(
                "⚠️ This will clear ALL flagged users and tracking data for this server.\n"
                "Run `[p]sbguard reset True` to confirm."
            )
        await self.config.guild(ctx.guild).flagged_users.set({})
        if ctx.guild.id in self._profiles:
            del self._profiles[ctx.guild.id]
        if ctx.guild.id in self._recent_messages:
            del self._recent_messages[ctx.guild.id]
        if ctx.guild.id in self._cross_channel:
            del self._cross_channel[ctx.guild.id]
        await ctx.send("✅ All SelfbotGuard data for this server has been reset.")

    # ── Hybrid slash support ─────────────────────────────────

    @app_commands.command(name="sbguard-status", description="Check SelfbotGuard status")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def slash_sbguard_status(self, interaction: discord.Interaction):
        """Slash command: view SelfbotGuard status."""
        ctx = await commands.Context.from_interaction(interaction)
        await self.sbguard_settings(ctx)

    @app_commands.command(name="sbguard-scan", description="Scan a user for selfbot indicators")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(user="The user to scan")
    async def slash_sbguard_scan(self, interaction: discord.Interaction, user: discord.Member):
        """Slash command: scan a specific user."""
        ctx = await commands.Context.from_interaction(interaction)
        await self.sbguard_scan(ctx, user)
