# SelfbotGuard v1.2.0

Advanced selfbot detection with 14 heuristic layers and configurable per-server punishments for Red-DiscordBot.

## Detection Layers

| # | Heuristic | What it detects |
|---|-----------|-----------------|
| 1 | Rich-embed abuse | Selfbots sending embeds (regular users can't) |
| 2 | Inhuman response time | Replies faster than humanly possible |
| 3 | Timing precision | Unnaturally consistent message intervals |
| 4 | 24/7 activity | No sleep/break patterns |
| 5 | Pattern matching | Automated command-response sequences |
| 6 | Burst detection | Rapid-fire message floods |
| 7 | Cross-channel spam | Same message blasted across channels |
| 8 | Cross-server activity | Messages in different servers within impossible windows |
| 9 | Edit cadence | Suspiciously regular edit timing |
| 10 | Presence anomalies | Messaging while offline/invisible |
| 11 | Reaction sniping | Reacting inhumanly fast (giveaway sniping) |
| 12 | Formatting analysis | Suspiciously clean formatting at speed |
| 13 | Trigger-word sniping | Instant response to giveaway/nitro keywords |
| 14 | Self-delete patterns | Automated self-deletion behaviour |

Each heuristic contributes to a cumulative suspicion score per user. When the score exceeds the configurable threshold, action is taken.

## Requirements

- Red-DiscordBot >= 3.5.0
- Python >= 3.9

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs selfbotguard
[p]load selfbotguard
```

> ⚠️ The cog is **disabled by default** — enable per-server with `[p]sbguard enable`.

## Commands

### Prefix Commands (`[p]sbguard`)
| Command | Description |
|---------|-------------|
| `[p]sbguard enable` | Enable detection in this server |
| `[p]sbguard disable` | Disable detection |
| `[p]sbguard action <action>` | Set punishment: `warn`, `mute`, `kick`, `ban`, `log` |
| `[p]sbguard sensitivity <level>` | Set sensitivity: `low`, `medium`, `high`, `paranoid` |
| `[p]sbguard threshold <number>` | Set custom suspicion threshold |
| `[p]sbguard logchannel <#channel>` | Set the alert/log channel |
| `[p]sbguard muteduration <time>` | Set mute/timeout duration |
| `[p]sbguard exempt <@role>` | Exempt a role from detection |
| `[p]sbguard unexempt <@role>` | Remove exemption |
| `[p]sbguard notifystaff <on/off>` | Toggle staff DM notifications |
| `[p]sbguard settings` | View current configuration |
| `[p]sbguard flagged` | View flagged/suspected users |
| `[p]sbguard unflag <@user>` | Clear a user's suspicion score |
| `[p]sbguard scan <@user>` | Manually scan a specific user |
| `[p]sbguard reset` | Reset all detection data for this server |

### Slash Commands
| Command | Description |
|---------|-------------|
| `/sbguard-status` | Check SelfbotGuard status (admin only) |
| `/sbguard-scan <user>` | Scan a user for selfbot indicators (admin only) |

## Data Statement

This cog stores Discord user IDs and guild IDs for selfbot detection. Per-user data includes message timestamps, response timing, activity windows, and suspicion scores. Data is periodically pruned.

## License

MIT
