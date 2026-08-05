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
    "report_channel": None,

    # ── Server nicknames ───────────────────────────────────────────────────
    "server_nicknames": {},

    # ── Stats ─────────────────────────────────────────────────────────────
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
}
