"""
Default configuration structures for Wormhole networks.

All per-network data lives inside ``networks.<name>`` in Red's Config.
Global data (cross-network) lives at the top level.
"""

from __future__ import annotations

DEFAULT_NETWORK: dict = {
    # ── Ownership / staff ──────────────────────────────────────────────────
    "owner_id": 0,
    "staff": {},                    # {user_id_str: Role int}  (new hierarchy)
    "staff_ids": [],                # LEGACY — flat list, migrated on read

    # ── Channels ───────────────────────────────────────────────────────────
    "channels": [],

    # ── Identity ───────────────────────────────────────────────────────────
    "use_webhooks": True,
    "relay_mode": "webhook",        # webhook | embed | compact
    "image_mode": "user",           # user | server | custom
    "name_mode": "both",            # user | server | both | custom
    "custom_icon": None,
    "custom_name": None,
    "colour": None,
    "description": "",

    # ── Moderation ─────────────────────────────────────────────────────────
    "banned_users": [],
    "banned_servers": [],
    "muted_users": [],
    "muted_servers": [],
    "word_filters": [],
    "regex_filters": [],
    "allowlist_servers": [],

    # ── Feature toggles ────────────────────────────────────────────────────
    "sync_edits": True,
    "sync_deletes": True,
    "sync_reactions": True,
    "sync_replies": True,
    "sync_threads": False,
    "sync_stickers": True,
    "sync_pins": False,
    "forward_embeds": True,
    "nsfw_gate": True,
    "silent": False,
    "frozen": False,

    # ── Rate limit ─────────────────────────────────────────────────────────
    "rate_limit_rate": 5,
    "rate_limit_per": 10.0,

    # ── Logging ────────────────────────────────────────────────────────────
    "log_channel": None,

    # ── Server nicknames ───────────────────────────────────────────────────
    "server_nicknames": {},

    # ── Stats ──────────────────────────────────────────────────────────────
    "total_messages": 0,
    "created_at": None,

    # ── Auto-moderation ────────────────────────────────────────────────────
    "automod": {
        "enabled": False,
        "anti_spam": False,
        "anti_mention_spam": False,
        "anti_caps": False,
        "anti_invite": False,
        "anti_link": False,
        "anti_zalgo": False,
        "anti_spoiler": False,
        "anti_emote_spam": False,
        "anti_newline_spam": False,
        "anti_raid": False,
        "max_mentions": 5,
        "caps_threshold": 0.7,
        "spam_window": 30.0,
        "spam_threshold": 3,
        "max_emotes": 10,
        "max_newlines": 15,
        "raid_window": 60.0,
        "raid_threshold": 10,
    },

    # ── Invites ────────────────────────────────────────────────────────────
    "invites": {},
    "vanity_invite": None,

    # ── Portal / welcome ───────────────────────────────────────────────────
    "portal_messages": {},
    "welcome_message": "",

    # ── Mention control (legacy) ───────────────────────────────────────────
    "mention_control": {
        "strip_everyone": True,
        "strip_role_mentions": False,
        "strip_user_mentions": False,
    },

    # ── User profiles ──────────────────────────────────────────────────────
    "user_profiles": {},
    "blackout_schedules": [],

    # ── DM relay ───────────────────────────────────────────────────────────
    "dm_enabled": False,
    "dm_subscribers": [],
    "dm_relay_mode": "embed",       # embed | compact | plain

    # ── Starboard ──────────────────────────────────────────────────────────
    "starboard_enabled": False,
    "starboard_channel": None,
    "starboard_threshold": 3,
    "starred_messages": {},

    # ── Audit log ──────────────────────────────────────────────────────────
    "audit_log": [],

    # ── Attachment filters ─────────────────────────────────────────────────
    "blocked_extensions": [],
    "max_filesize": None,

    # ── Karma ──────────────────────────────────────────────────────────────
    "karma_enabled": False,
    "karma_emoji": "👍",
    "karma_scores": {},

    # ── MOTD / Rules ───────────────────────────────────────────────────────
    "motd": "",
    "rules": "",

    # ── Relay delay ────────────────────────────────────────────────────────
    "relay_delay": 0,

    # ── Highlights ─────────────────────────────────────────────────────────
    "highlights": {},

    # ── Network roles (legacy, unused) ─────────────────────────────────────
    "roles": {},

    # ── Per-channel overrides ──────────────────────────────────────────────
    "channel_overrides": {},

    # ── Scheduled messages ─────────────────────────────────────────────────
    "scheduled_messages": [],

    # ── Slowmode ───────────────────────────────────────────────────────────
    "slowmode": 0,

    # ── Discovery ──────────────────────────────────────────────────────────
    "public": False,
    "tags": [],

    # ── Typing indicator relay ─────────────────────────────────────────────
    "sync_typing": False,

    # ── Anonymous mode ─────────────────────────────────────────────────────
    "anonymous": False,
    "anon_salt": "",

    # ── Mirror channels ────────────────────────────────────────────────────
    "mirror_channels": [],

    # ── Ephemeral messages ─────────────────────────────────────────────────
    "ephemeral_delay": 0,

    # ── Auto-responses ─────────────────────────────────────────────────────
    "auto_responses": {},

    # ── Media-only mode ────────────────────────────────────────────────────
    "media_only": False,

    # ── Analytics ──────────────────────────────────────────────────────────
    "analytics": {
        "hourly": {},
        "top_users": {},
    },

    # ── Health ─────────────────────────────────────────────────────────────
    "last_health_check": None,
    "unhealthy_channels": [],

    # ── Polls ──────────────────────────────────────────────────────────────
    "active_polls": {},

    # ── AFK system ─────────────────────────────────────────────────────────
    "afk_users": {},

    # ── Personal ignore list ───────────────────────────────────────────────
    "user_ignores": {},

    # ── User colours ───────────────────────────────────────────────────────
    "user_colours": {},

    # ── Quiet hours ────────────────────────────────────────────────────────
    "quiet_hours": {},

    # ── Network bridging ───────────────────────────────────────────────────
    "bridge_from": [],
    "bridge_to": [],

    # ── Granular mention policy ────────────────────────────────────────────
    "mention_policy": {
        "allow_user_mentions": False,
        "allow_role_mentions": False,
        "allow_everyone": False,
        "allow_here": False,
    },
    "server_mention_overrides": {},
    "mention_exempt_users": [],
    "mention_optout_users": [],

    # ── ToS acceptance gate ────────────────────────────────────────────────
    "rules_required": False,
    "rules_text": "",
    "rules_accepted": {},

    # ── Report system ──────────────────────────────────────────────────────
    "reports": [],
    "report_counter": 0,
}


DEFAULT_GLOBAL: dict = {
    "networks": {},
    "max_networks_per_user": 10,
    "global_banned_users": [],
    "global_banned_servers": [],
    "bookmarks": {},
}


MAP_LIMIT: int = 2_000
