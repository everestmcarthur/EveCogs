# EveCogs

A premium cog repository for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot).

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs wormhole
[p]load wormhole
```

---

# Wormhole v3.3.0

**The ultimate cross-server message relay for Red-DiscordBot.**

Connect Discord channels across unlimited servers into named networks. Messages, edits, deletes, reactions, replies, stickers, pins, typing indicators, and files are all relayed in real-time.

## Feature Highlights

| Category | Features |
|----------|----------|
| **Relay** | Webhook / embed / compact modes, edit & delete sync, reply threading, sticker forwarding, pin sync, typing indicators, file relay |
| **DM Relay** | Bidirectional DM ↔ network messaging, quiet hours, personal ignore lists |
| **Moderation** | Ban/mute users & servers, word + regex filters, attachment filters, global blocklist, purge |
| **Auto-Mod** | Anti-spam, anti-raid, anti-caps, anti-invite, anti-link, anti-zalgo, anti-spoiler, anti-emote-spam, anti-newlines |
| **Staff** | Staff system, ownership transfer, audit log, announcements |
| **Invites** | Invite codes, vanity URLs, expiry, max uses, allowlists |
| **Social** | Karma/reputation, starboard, user profiles, keyword highlights |
| **Scheduling** | Scheduled messages, blackout windows, relay delay, slowmode |
| **Phase 4** | Anonymous mode, mirror channels, polls, AFK, auto-responses, ephemeral messages, media-only, analytics, health monitor, bookmarks, user colours, quiet hours, network bridging |

## Command Reference

### Core
| Command | Description |
|---------|-------------|
| `[p]wh create <name>` | Create a new network |
| `[p]wh delete <name>` | Delete a network |
| `[p]wh open <name>` | Link current channel |
| `[p]wh close` | Unlink current channel |
| `[p]wh list` | List all networks |
| `[p]wh info <name>` | Network info & stats |
| `[p]wh portal [name]` | Create/refresh portal embed |

### Settings (`[p]wh set`)
| Command | Description |
|---------|-------------|
| `set mode <name> <webhook\|embed\|compact>` | Relay mode |
| `set colour <name> <hex>` | Embed colour |
| `set icon <name> <url>` | Custom network icon |
| `set freeze <name> <bool>` | Freeze/unfreeze |
| `set nsfw <name> <bool>` | NSFW gate |
| `set ratelimit <name> <msgs> <secs>` | Rate limit |
| `set slowmode <name> <secs>` | Per-user slowmode |
| `set welcome <name> <msg>` | Welcome message |
| `set motd <name> <msg>` | Message of the day |
| `set rules <name> <text>` | Network rules |
| `set mention <name> <key> <bool>` | Mention control |
| `set log-channel <name> <ch>` | Log channel |
| `set max-filesize <name> <bytes>` | Max file size |
| `set delay <name> <secs>` | Relay delay |
| `set anonymous <name> <bool>` | Anonymous mode |
| `set ephemeral <name> <secs>` | Auto-delete timer |
| `set media-only <name> <bool>` | Media-only mode |

### Sync Toggles
| Command | Description |
|---------|-------------|
| `set edits / deletes / replies / reactions / stickers / threads / typing / pins` | Toggle sync features |

### Staff & Moderation
| Command | Description |
|---------|-------------|
| `staff add/remove/list` | Manage staff |
| `transfer <name> <user>` | Transfer ownership |
| `mod ban/unban/mute/unmute <name> <user>` | User moderation |
| `mod ban-server/unban-server/mute-server/unmute-server` | Server moderation |
| `mod allowlist-add/allowlist-remove` | Server allowlist |
| `mod purge <name> [count]` | Purge relayed messages |

### Filters
| Command | Description |
|---------|-------------|
| `filter add-word/remove-word` | Word filters |
| `filter add-regex/remove-regex` | Regex filters |
| `filter list` | List all filters |

### Auto-Moderation
| Command | Description |
|---------|-------------|
| `automod enable/disable` | Toggle auto-mod |
| `automod anti-spam/anti-caps/anti-invite/anti-link` | Toggle protections |
| `automod anti-zalgo/anti-spoiler/anti-emote-spam/anti-newlines` | More protections |
| `automod anti-mentions <name> <bool> [max]` | Mention spam |
| `automod anti-raid <name> <bool> [threshold] [window]` | Raid protection |
| `automod status` | View auto-mod status |

### Invites
| Command | Description |
|---------|-------------|
| `invite create <name> [uses] [mins]` | Create invite |
| `invite vanity <name> <word>` | Set vanity URL |
| `invite use <code>` | Join via invite |
| `invite revoke/list` | Manage invites |

### DM Relay
| Command | Description |
|---------|-------------|
| `dm enable/disable <name>` | Toggle DM relay |
| `dm sub/unsub <name>` | Subscribe/unsubscribe |
| `dm send <name> <msg>` | Send via DM |
| `dm list` | List subscriptions |

### Social
| Command | Description |
|---------|-------------|
| `karma enable/disable/check/leaderboard` | Karma system |
| `starboard enable/disable` | Cross-network starboard |
| `highlight add/remove/list` | Keyword notifications |
| `profile [user]` | View user profile |

### Phase 4 — New in v3.3.0
| Command | Description |
|---------|-------------|
| `mirror add/remove/list` | One-way receive-only channels |
| `poll create/close/list` | Network-wide polls with voting |
| `afk <name> [reason]` | Set AFK status |
| `ignore add/remove/list` | Personal ignore list (DM relay) |
| `autoreply add/add-regex/remove/cooldown/list` | Staff auto-responses |
| `bookmark save/list/clear` | Save messages for later |
| `colour <name> <hex>` | Personal embed colour |
| `quiet <name> <start> <end> [offset]` | Quiet hours (DM mute) |
| `quiet-off <name>` | Disable quiet hours |
| `analytics <name>` | Activity dashboard |
| `health <name>` | Channel permission audit |
| `bridge add/remove/list` | Network-to-network bridging |

### Utility
| Command | Description |
|---------|-------------|
| `announce <name> <msg>` | Broadcast to all channels |
| `schedule <name> <mins> <msg>` | Schedule a message |
| `search <name> <query>` | Search message history |
| `discover` | Browse public networks |
| `backup <name>` / `restore` | Backup & restore |
| `debug [name]` | Diagnostic info |

---

## Architecture

```
EveCogs/
├── README.md
├── LICENSE (MIT)
├── info.json
└── wormhole/
    ├── __init__.py
    ├── info.json
    ├── utils.py       (403 lines — embeds, filters, automod, helpers)
    └── wormhole.py    (3,376 lines — main cog, 70+ commands, relay engine)
```

## License

MIT — see [LICENSE](LICENSE).
