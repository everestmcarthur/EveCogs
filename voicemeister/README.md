# VoiceMeister v1.0.0

The ultimate temporary voice channel system for Red-DiscordBot — Join-to-Create, full button control panel, name templates, game detection, and more.

## Features

- **Join-to-Create** — Users join a designated channel and a personal voice channel is auto-created
- **Control Panel** — Persistent button panel with 17 actions (Lock, Unlock, Hide, Rename, Kick, Ban, etc.)
- **Name Templates** — `{user}`, `{game}`, `{count}`, `{custom}` variables
- **Game Detection** — Channels auto-rename based on the owner's current game activity
- **Auto-Cleanup** — Channels are deleted when everyone leaves
- **Blacklist / Whitelist** — Control who can create channels
- **Persistent Views** — All buttons survive bot restarts

## Requirements

- Red-DiscordBot >= 3.5.0
- Python >= 3.9

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs voicemeister
[p]load voicemeister
```

## Quick Start

```
[p]voicemeister setup              # Interactive setup wizard
[p]voicemeister creator add #vc    # Add a Join-to-Create channel
[p]voicemeister panel #channel     # Send the control panel
```

## Commands

### Admin Commands (`[p]voicemeister` / `[p]vm`)
| Command | Description |
|---------|-------------|
| `[p]vm setup` | Interactive setup wizard |
| `[p]vm panel <#channel>` | Send the button control panel |
| `[p]vm settings` | View current configuration |
| `[p]vm logchannel <#channel>` | Set logging channel |
| `[p]vm defaultname <template>` | Set default channel name template |
| `[p]vm defaultlimit <number>` | Set default user limit |
| `[p]vm defaultbitrate <kbps>` | Set default bitrate |
| `[p]vm cooldown <seconds>` | Set creation cooldown |
| `[p]vm maxchannels <number>` | Max temp channels per user |
| `[p]vm gamerename <on/off>` | Toggle game activity renaming |
| `[p]vm resetall` | Reset all VoiceMeister data |

### Creator Management (`[p]vm creator` / `[p]vm jtc`)
| Command | Description |
|---------|-------------|
| `[p]vm creator add <#vc>` | Add a Join-to-Create channel |
| `[p]vm creator remove <#vc>` | Remove a JTC channel |
| `[p]vm creator list` | List all JTC channels |
| `[p]vm creator template <#vc> <name>` | Set per-creator name template |
| `[p]vm creator userlimit <#vc> <n>` | Set per-creator user limit |
| `[p]vm creator bitrate <#vc> <kbps>` | Set per-creator bitrate |

### Blacklist / Whitelist
| Command | Description |
|---------|-------------|
| `[p]vm blacklist add/remove/list` | Manage blacklisted users |
| `[p]vm whitelist add/remove/list` | Manage whitelisted users |

### User Commands (`[p]vc`)
| Command | Description |
|---------|-------------|
| `[p]vc lock / unlock` | Lock/unlock your channel |
| `[p]vc hide / unhide` | Hide/unhide your channel |
| `[p]vc rename <name>` | Rename your channel |
| `[p]vc limit <number>` | Set user limit |
| `[p]vc permit / reject <@user>` | Allow/deny a user |
| `[p]vc kick / ban <@user>` | Kick/ban a user from your channel |
| `[p]vc claim` | Claim an ownerless channel |
| `[p]vc transfer <@user>` | Transfer ownership |
| `[p]vc bitrate <kbps>` | Set bitrate |
| `[p]vc info` | Channel info & stats |
| `[p]vc ghost` | Hide + lock (go invisible) |
| `[p]vc delete` | Delete your channel |

### Control Panel Buttons

The persistent panel provides one-click access to: Lock, Unlock, Hide, Unhide, Ghost, Reveal, Rename, User Limit, Bitrate, Region, Permit, Reject, Kick, Ban, Mute All, Unmute All, Claim, Transfer, Info, and Delete.

## Data Statement

This cog stores Discord user IDs, guild IDs, and channel IDs for voice channel ownership and settings. Per-user data includes channel ownership, ban/permit lists, and usage cooldowns. Data is cleaned up when channels are deleted.

## License

MIT
