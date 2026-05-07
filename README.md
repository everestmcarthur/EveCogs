# 🌀 EveCogs

A premium cog repository for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot).

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs wormhole
[p]load wormhole
```

---

# 🌀 Wormhole v3.2.0

**The ultimate cross-server message relay for Discord.**

Connect channels across multiple servers into named networks. Messages, edits, deletes, reactions, replies, stickers, pins, typing indicators, and files are relayed in real-time. Features DM relay, starboard, karma, auto-moderation, invites, portals, and 50+ commands.

## ✨ Features

### 📡 Core Relay
- **Named networks** — create unlimited named relay networks
- **Three relay modes** — `webhook` (rich identity), `embed` (styled cards), `compact` (minimal text)
- **Full sync** — edits, deletes, reactions, replies, stickers, threads, pins, typing indicators
- **File forwarding** — images, videos, documents all relayed automatically
- **Embed forwarding** — rich embeds from bots/links passed through
- **Reply context** — quoted reply previews carried across servers

### 📧 DM Relay
- **Subscribe** to receive network messages directly in your DMs
- **Send from DMs** — participate in networks without being in a server channel
- **Three DM formats** — embed, compact, or plain text
- **Bidirectional** — full two-way communication via DMs

### 🛡️ Moderation
- **Ban / mute** individual users or entire servers
- **Word filters** — block specific words
- **Regex filters** — pattern-based content blocking
- **Allowlist** — restrict which servers can join
- **Purge** — mass delete relayed messages across all channels
- **Audit log** — full trail of all admin/mod actions (last 500 entries)

### 🤖 Auto-Moderation Engine
- **Anti-spam** — duplicate message detection with configurable window/threshold
- **Anti-mention spam** — block mass mentions
- **Anti-caps** — configurable caps percentage threshold
- **Anti-invite** — block Discord invite links
- **Anti-link** — block all URLs
- **Anti-zalgo** — block combining character abuse
- **Anti-spoiler spam** — block excessive spoiler tags
- **Anti-emote spam** — limit custom emoji per message
- **Anti-newline spam** — limit vertical space abuse
- **Anti-raid** — auto-freeze network on flood detection

### ⭐ Starboard
- Cross-network starboard — star reactions collected across all channels
- Configurable threshold and dedicated starboard channel
- Auto-updating star count on the board embed

### 💎 Karma / Reputation
- React with a configurable emoji to give karma
- Per-user karma scores tracked across the network
- Leaderboard command

### 🔔 Keyword Highlights
- Subscribe to keywords — get DM'd when they're mentioned
- Per-user, per-network keyword lists

### 🔗 Invites
- **Invite codes** — shareable codes with optional max uses and expiry
- **Vanity invites** — custom words (e.g. `gaming` instead of `xK4mR2pQ`)
- Join networks from any server with just a code

### 📢 Communication
- **Staff announcements** — broadcast to all channels + DM subscribers
- **Scheduled messages** — send timed announcements
- **MOTD** — message of the day shown on join
- **Rules** — network rules displayed on demand
- **Welcome messages** — greet new servers automatically

### 🌀 Portal Messages
- Persistent, auto-updating status embeds pinned in channels
- Shows network status, channel count, features, MOTD
- Refreshes every 5 minutes automatically

### 🔍 Search & Discovery
- **Search** — search recent messages across the entire network
- **Network discovery** — list public networks with tags
- **Tags** — categorize networks for easy discovery

### ⚙️ Advanced Configuration
- **Per-channel overrides** — different relay mode per channel
- **Server nicknames** — custom display names per server
- **Custom identity** — custom icons, names, colour accents
- **Name modes** — show user, server, both, or custom template
- **Mention control** — strip @everyone, @here, @role, @user
- **Attachment filters** — block file types and enforce size limits
- **Relay delay** — configurable seconds before relay (for review)
- **Slowmode** — network-wide per-user cooldown
- **Rate limiting** — configurable messages per time window
- **NSFW gate** — block relay from NSFW channels
- **Freeze** — pause a network instantly
- **Silent mode** — suppress join/leave notifications

### 🌙 Blackout Scheduling
- Auto-freeze/unfreeze on schedule
- Per-day-of-week and hour range (UTC)
- Multiple schedules per network

### 💾 Backup & Restore
- Export entire network config as JSON
- Restore to same or different name
- Preserves all settings, filters, profiles

### 👤 User Profiles & Stats
- Per-user message counts, first-seen date, server list
- Network-wide statistics with top-5 leaderboard
- Karma integration in profiles

### 🌐 Global Blocklist (Bot Owner)
- Block users/servers from ALL wormhole networks
- Independent of per-network moderation

### ⭐ Staff System
- **Owner** — full control, can add/remove staff
- **Staff** — moderation, settings, filters, announcements
- **Ownership transfer** — hand off networks to other users

## 📋 Quick Start

```
[p]wh create mynetwork A cool cross-server chat!
[p]wh open mynetwork              # in each channel you want linked
[p]wh invite create mynetwork     # share the code
[p]wh dm enable mynetwork         # enable DM relay
[p]wh set relay-mode mynetwork webhook
[p]wh automod enable mynetwork
[p]wh starboard enable mynetwork #starboard 3
[p]wh karma enable mynetwork 👍
```

## 📖 Command Reference

Run `[p]wh help` in Discord for the full interactive reference (3-page embed).

### Network Management
| Command | Description |
|---------|-------------|
| `wh create <name> [desc]` | Create a new network |
| `wh delete <name>` | Delete a network (with confirmation) |
| `wh open <name>` | Link current channel |
| `wh close [name]` | Unlink current channel |
| `wh list` | List all networks |
| `wh discover` | List public networks |
| `wh info <name>` | Detailed network info |
| `wh stats <name>` | Statistics & leaderboard |
| `wh transfer <name> @user` | Transfer ownership |
| `wh announce <name> <msg>` | Staff broadcast |
| `wh portal [name]` | Create/refresh portal |
| `wh search <name> <query>` | Search messages |
| `wh schedule <name> <min> <msg>` | Scheduled message |
| `wh rules <name>` | Show rules |
| `wh motd <name>` | Show MOTD |
| `wh audit <name> [n]` | View audit log |
| `wh backup <name>` | Export JSON backup |
| `wh restore [name]` | Import from JSON |

### DM Relay
| Command | Description |
|---------|-------------|
| `wh dm enable/disable <name>` | Toggle DM relay |
| `wh dm mode <name> <format>` | Set DM format |
| `wh dm subscribe <name>` | Subscribe to DMs |
| `wh dm unsubscribe <name>` | Unsubscribe |
| `wh dm send <name> <msg>` | Send via DM |
| `wh dm list` | Your subscriptions |

### Settings (`wh set`)
`relay-mode` · `webhooks` · `name-mode` · `image-mode` · `custom-icon` · `custom-name` · `description` · `colour` · `ratelimit` · `slowmode` · `relay-delay` · `log-channel` · `nickname` · `welcome` · `motd` · `rules` · `tags` · `public` · `max-filesize` · `blocked-extensions` · `freeze` · `silent` · `nsfw-gate` · `sync-edits` · `sync-deletes` · `sync-reactions` · `sync-replies` · `sync-stickers` · `sync-threads` · `sync-pins` · `sync-typing` · `forward-embeds` · `strip-everyone` · `strip-roles` · `strip-users` · `channel-override`

### Moderation (`wh mod`)
`ban/unban` · `mute/unmute` · `ban-server/unban-server` · `mute-server/unmute-server` · `allowlist-add/remove` · `purge`

### Auto-Moderation (`wh automod`)
`enable/disable` · `anti-spam` · `anti-mentions` · `anti-caps` · `anti-invite` · `anti-link` · `anti-zalgo` · `anti-spoiler` · `anti-emote-spam` · `anti-newlines` · `anti-raid` · `status`

### More
| Category | Commands |
|----------|----------|
| **Staff** | `wh staff add/remove/list` |
| **Invites** | `wh invite create/vanity/use/revoke/list` |
| **Filters** | `wh filter add-word/remove-word/add-regex/remove-regex/list` |
| **Starboard** | `wh starboard enable/disable` |
| **Karma** | `wh karma enable/disable/check/leaderboard` |
| **Highlights** | `wh highlight add/remove/list` |
| **Blackout** | `wh blackout add/clear/list` |
| **Profiles** | `wh profile <name> [@user]` |
| **Global** | `wh global ban-user/unban-user/ban-server/unban-server/list` |

## 📊 Architecture

```
EveCogs/
├── README.md
├── LICENSE (MIT)
├── info.json (repo metadata)
└── wormhole/
    ├── __init__.py       (cog loader + data statement)
    ├── info.json         (cog metadata)
    ├── utils.py          (helpers, embeds, detectors, filters)
    └── wormhole.py       (main cog — 2,200+ lines, 50+ commands)
```

## 📄 License

MIT — see [LICENSE](LICENSE).

## 🤝 Credits

Built by [everestmcarthur](https://github.com/everestmcarthur) with assistance from Viktor AI.
