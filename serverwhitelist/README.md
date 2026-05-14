# ServerWhitelist v4.0

The ultimate owner-only server management cog for Red-DiscordBot. Complete control over which Discord servers the bot can operate in.

## Features

- **Whitelist / Blacklist** — Approve or block servers with paginated views
- **Interactive Browser** — Browse all servers with leave dropdowns
- **Whitelist Requests** — Server owners can request access via DM button; you approve/deny
- **Notes & Tags** — Annotate and categorize servers for organization
- **Invite Audit** — See who added the bot via Discord audit log
- **Temp Whitelist** — Time-limited server access (e.g., `[p]join temp <id> 7d`)
- **Member Requirements** — Min/max member thresholds for auto-approval
- **Trusted Inviters** — Auto-whitelist when specific users add the bot
- **Owner Alerts** — DM notifications for all join/leave events
- **Auto-Ban** — Configurable threshold for repeated unauthorized join attempts
- **Backup & Restore** — Full config export/import
- **Rich Logging** — Colour-coded event logging to a dedicated channel

## Requirements

- Red-DiscordBot >= 3.5.0
- Python >= 3.9

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs serverwhitelist
[p]load serverwhitelist
```

> All servers the bot is currently in are automatically whitelisted on first load.

## Commands (Owner Only)

### Core
| Command | Description |
|---------|-------------|
| `[p]join <id>` | Whitelist a server |
| `[p]join remove <id>` | Remove from whitelist |
| `[p]join whitelist` | View the whitelist |
| `[p]join blacklist <id>` | Blacklist a server |
| `[p]join unblacklist <id>` | Remove from blacklist |
| `[p]join blacklisted` | View the blacklist |

### Management
| Command | Description |
|---------|-------------|
| `[p]join servers` | Interactive server browser with leave controls |
| `[p]join info <id>` | Detailed server info embed |
| `[p]join search <query>` | Search servers by name |
| `[p]join stats` | Overview statistics |
| `[p]join leave <id>` | Force-leave a server |
| `[p]join purge` | Leave all non-whitelisted servers |
| `[p]join lock / unlock` | Lock mode (reject all new joins) |

### Configuration
| Command | Description |
|---------|-------------|
| `[p]join log <#channel>` | Set event logging channel |
| `[p]join settings` | View all settings |
| `[p]join export` | Export full config |
| `[p]join attempts` | View unauthorized join attempts |
| `[p]join attempts reset` | Reset attempt counters |

### v4.0 Features
| Command | Description |
|---------|-------------|
| `[p]join temp <id> <duration>` | Temporary whitelist |
| `[p]join note <id> <text>` | Add a note to a server |
| `[p]join tag <id> <tag>` | Tag a server for organization |
| `[p]join trusted add/remove <@user>` | Manage trusted inviters |
| `[p]join minmembers / maxmembers` | Set member requirements |
| `[p]join alerts on/off` | Toggle owner DM alerts |
| `[p]join backup / restore` | Backup and restore config |

## Data Statement

This cog stores guild IDs in a global whitelist, blacklist, join-attempt tracker, notes, tags, and whitelist request queue. No per-user data is collected beyond requester IDs in the request queue.

## License

MIT
