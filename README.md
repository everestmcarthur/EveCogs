# EveCogs

A premium cog repository for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot).

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs wormhole
[p]load wormhole
```

---

# Wormhole v3.4.0

**The ultimate cross-server message relay for Red-DiscordBot.**

Connect Discord channels across unlimited servers into named networks. All commands work as **both slash commands and prefix commands** (hybrid). Messages, edits, deletes, reactions, replies, stickers, pins, typing indicators, and files are all relayed in real-time.

## What's New in v3.4.0

- **Hybrid Commands** — every command works as both `/wh` and `[p]wh`
- **Context Menu Actions** — right-click messages/users for Report, Bookmark, Delete, Profile
- **Granular Mention Policy** — control @user, @role, @everyone, @here per-network AND per-server, with per-user exemptions
- **Terms of Service Gate** — require users to accept legal ToS before messaging, with built-in prosecution-ready legal template
- **Mod Edit/Delete Across Network** — staff can edit or delete a message from every server at once
- **Report System** — users can report messages (prefix command or right-click), staff review/action/resolve, with DM warnings and auto-ban/mute

## Feature Highlights

| Category | Features |
|----------|----------|
| **Relay** | Webhook / embed / compact modes, edit & delete sync, reply threading, sticker forwarding, pin sync, typing indicators, file relay |
| **DM Relay** | Bidirectional DM ↔ network messaging, quiet hours, personal ignore lists |
| **Moderation** | Ban/mute users & servers, word + regex filters, attachment filters, global blocklist, purge, network-wide edit & delete |
| **Auto-Mod** | Anti-spam, anti-raid, anti-caps, anti-invite, anti-link, anti-zalgo, anti-spoiler, anti-emote-spam, anti-newlines |
| **Mentions** | Per-network + per-server policy for @user, @role, @everyone, @here with exemptions |
| **ToS/Rules** | Acceptance gate, legal template, consent tracking with timestamps, force re-accept |
| **Reports** | Report via command or context menu, staff review, resolve, action (ban/mute/warn/dismiss) |
| **Staff** | Staff system, ownership transfer, audit log, announcements |
| **Invites** | Invite codes, vanity URLs, expiry, max uses, allowlists |
| **Social** | Karma/reputation, starboard, user profiles, keyword highlights |
| **Scheduling** | Scheduled messages, blackout windows, relay delay, slowmode |
| **Phase 4** | Anonymous mode, mirror channels, polls, AFK, auto-responses, ephemeral messages, media-only, analytics, health monitor, bookmarks, user colours, quiet hours, network bridging |
| **Context Menus** | Report to Wormhole, Wormhole Bookmark, Wormhole Delete (staff), Wormhole Profile |

## Command Reference (85+ commands)

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
| `set colour/icon/description` | Network identity |
| `set freeze/silent/nsfw-gate` | Toggles |
| `set ratelimit/slowmode/relay-delay` | Flow control |
| `set anonymous/ephemeral/media-only` | Special modes |
| `set sync-*` | Toggle edit/delete/reaction/reply/sticker/thread/pin/typing sync |
| `set strip-everyone/roles/users` | Legacy mention stripping |
| `set channel-override` | Per-channel setting overrides |

### Mention Policy (`[p]wh mentions`) — NEW
| Command | Description |
|---------|-------------|
| `mentions set <name> <type> <bool>` | Network-wide policy (users/roles/everyone/here) |
| `mentions server-set <name> <type> <bool>` | Per-server override |
| `mentions exempt <name> @user` | Allow user to bypass policy |
| `mentions unexempt <name> @user` | Remove exemption |
| `mentions status <name>` | View current policy |

### Terms of Service (`[p]wh tos`) — NEW
| Command | Description |
|---------|-------------|
| `tos enable <name>` | Require acceptance before messaging |
| `tos disable <name>` | Remove requirement |
| `tos set <name> <text>` | Custom ToS text |
| `tos template <name>` | Reset to legal template |
| `tos accepted <name>` | View who accepted |
| `tos reset <name>` | Force everyone to re-accept |
| `[p]wh accept <name>` | View the ToS |
| `[p]wh agree <name>` | Accept the ToS |

### Reports (`[p]wh report`) — NEW
| Command | Description |
|---------|-------------|
| `report message [msg_id] [reason]` | Report a message (or reply to one) |
| `report list <name> [show_resolved]` | View reports (staff) |
| `report resolve <name> <id>` | Mark as resolved |
| `report action <name> <id> <action>` | Take action: ban, mute, warn, dismiss |

### Mod Tools (`[p]wh mod`)
| Command | Description |
|---------|-------------|
| `mod ban/unban/mute/unmute` | User moderation |
| `mod ban-server/unban-server/mute-server/unmute-server` | Server moderation |
| `mod edit <name> <msg_id> <new_text>` | Edit across entire network — NEW |
| `mod nuke <name> <msg_id>` | Delete from entire network — NEW |
| `mod purge <name> [count]` | Purge relayed messages |

### Context Menus (right-click) — NEW
| Action | Description |
|--------|-------------|
| **Report to Wormhole** | Right-click any message → opens report modal |
| **Wormhole Bookmark** | Right-click any message → saves to DM |
| **Wormhole Delete** | Right-click any message → deletes from all servers (staff) |
| **Wormhole Profile** | Right-click any user → view their network stats |

### DM Relay / Invites / Staff / Filters / AutoMod / Starboard / Karma / Highlights / Blackout / Backup / Global
*See `[p]wh help` for the full interactive reference (4 pages).*

### Phase 4 Features
| Command | Description |
|---------|-------------|
| `mirror add/remove/list` | One-way receive-only channels |
| `poll create/close/list` | Network-wide polls with voting |
| `afk <name> [reason]` | Set AFK status |
| `ignore add/remove/list` | Personal ignore list (DM relay) |
| `autoreply add/add-regex/remove/list` | Staff auto-responses |
| `bookmark save/list/clear` | Save messages for later |
| `colour <name> <hex>` | Personal embed colour |
| `quiet/quiet-off` | Quiet hours (DM mute) |
| `analytics <name>` | Activity dashboard |
| `health <name>` | Channel permission audit |
| `bridge add/remove/list` | Network-to-network bridging |

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
    ├── utils.py       (419 lines — embeds, filters, automod, mention policy, helpers)
    └── wormhole.py    (4,196 lines — main cog, 85+ commands, relay engine, context menus)
```

## License

MIT — see [LICENSE](LICENSE).
