# Wormhole v4.0.0

The ultimate cross-server message relay for Red-DiscordBot — modular architecture, hierarchical staff system, 100+ hybrid commands.

## Features

| Category | Features |
|----------|----------|
| **Relay** | Webhook / embed / compact modes, edit & delete sync, reply threading, sticker forwarding, pin sync, typing indicators, file relay |
| **DM Relay** | Bidirectional DM ↔ network messaging, quiet hours, personal ignore lists |
| **Moderation** | Ban/mute users & servers, word + regex filters, attachment filters, global blocklist, purge, network-wide edit & delete |
| **Auto-Mod** | Anti-spam, anti-raid, anti-caps, anti-invite, anti-link, anti-zalgo, anti-spoiler, anti-emote-spam, anti-newlines |
| **Staff System** | Hierarchical roles: Owner → Admin → Moderator → Helper → Member |
| **Mentions** | Per-network + per-server policy for @user, @role, @everyone, @here with per-user exemptions |
| **ToS/Rules** | Acceptance gate, legal template, consent tracking with timestamps, force re-accept |
| **Reports** | Report via command or context menu, staff review, resolve, action (ban/mute/warn/dismiss) |
| **Context Menus** | Report to Wormhole, Bookmark, Delete (staff), Profile — right-click actions |
| **Social** | Karma/reputation, starboard, user profiles, keyword highlights |
| **Invites** | Invite codes, vanity URLs, expiry, max uses, allowlists |
| **Scheduling** | Scheduled messages, blackout windows, relay delay, slowmode |
| **Advanced** | Anonymous mode, mirror channels, polls, AFK, auto-responses, ephemeral messages, media-only, analytics, health monitor, bookmarks, user colours, quiet hours, network bridging |

## Requirements

- Red-DiscordBot >= 3.5.0
- Python >= 3.9

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs wormhole
[p]load wormhole
```

## Quick Start

```
[p]wh create <network-name>     # Create a new network
[p]wh open <network-name>       # Link current channel to a network
[p]wh close                     # Unlink current channel
[p]wh list                      # List all networks
```

## Command Reference (100+ commands)

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
| `set mode` | Relay mode (webhook/embed/compact) |
| `set colour / icon / description` | Network identity |
| `set freeze / silent / nsfw-gate` | Toggles |
| `set ratelimit / slowmode / relay-delay` | Flow control |
| `set anonymous / ephemeral / media-only` | Special modes |
| `set sync-*` | Toggle sync for edit/delete/reaction/reply/sticker/thread/pin/typing |

### Mentions (`[p]wh mentions`)
| Command | Description |
|---------|-------------|
| `mentions set <name> <type> <bool>` | Network-wide policy |
| `mentions server-set <name> <type> <bool>` | Per-server override |
| `mentions exempt / unexempt <name> @user` | Per-user exemptions |
| `mentions status <name>` | View current policy |

### Terms of Service (`[p]wh tos`)
| Command | Description |
|---------|-------------|
| `tos enable / disable <name>` | Toggle ToS requirement |
| `tos set <name> <text>` | Custom ToS text |
| `tos template <name>` | Reset to legal template |
| `tos accepted <name>` | View who accepted |
| `tos reset <name>` | Force re-accept |

### Reports (`[p]wh report`)
| Command | Description |
|---------|-------------|
| `report message [msg_id] [reason]` | Report a message |
| `report list <name>` | View reports (staff) |
| `report resolve / action <name> <id>` | Handle reports |

### Moderation (`[p]wh mod`)
| Command | Description |
|---------|-------------|
| `mod ban / unban / mute / unmute` | User moderation |
| `mod ban-server / unban-server` | Server moderation |
| `mod edit <name> <msg_id> <text>` | Edit across entire network |
| `mod nuke <name> <msg_id>` | Delete from entire network |
| `mod purge <name> [count]` | Purge relayed messages |

### Staff (`[p]wh staff`)
| Command | Description |
|---------|-------------|
| `staff add / remove <name> <@user> <role>` | Manage staff |
| `staff list <name>` | View staff roster |
| `staff transfer <name> <@user>` | Transfer ownership |

*See `[p]wh help` for the full interactive reference including DM relay, invites, filters, automod, social, scheduling, and advanced features.*

## Architecture (v4.0.0)

```
wormhole/
├── __init__.py          # Entry point
├── core.py              # Main cog class, config, internal helpers
├── wormhole.py          # Command definitions (100+ commands)
├── utils.py             # Embeds, filters, automod, mention policy, helpers
├── commands/            # Modular command mixins
│   ├── _base.py         # Base mixin
│   ├── network.py       # Network management
│   ├── settings.py      # Settings commands
│   ├── moderation.py    # Mod tools
│   ├── filters.py       # Word/regex filters
│   ├── mentions.py      # Mention policy
│   ├── tos.py           # Terms of service
│   ├── reports.py       # Report system
│   ├── staff.py         # Staff management
│   ├── social.py        # Karma, starboard, highlights
│   ├── dm.py            # DM relay
│   ├── bridge.py        # Network bridging
│   ├── advanced.py      # Polls, AFK, auto-responses, analytics
│   └── debug.py         # Debug commands
├── listeners/           # Event listeners
│   ├── relay.py         # Message relay pipeline
│   ├── sync.py          # Edit/delete/reaction sync
│   └── misc.py          # Guild join/leave
├── models/              # Data models
│   ├── config.py        # Config defaults
│   ├── message_map.py   # Cross-server message ID mapping
│   └── permissions.py   # Hierarchical role system
├── services/
│   └── emoji.py         # Foreign emoji resolution
└── ui/
    ├── modals.py        # Report modal
    └── views.py         # Reply jump buttons
```

## Data Statement

This cog stores Discord user IDs, guild IDs, and channel IDs for relay functionality. Per-user data includes message counts, karma scores, keyword highlights, DM relay subscriptions, bookmarks, AFK status, and more.

## License

MIT
