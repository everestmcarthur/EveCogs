# NexusCore v2.0.0

The ultimate all-in-one server management cog for Red-DiscordBot. 10 modules, 100+ commands.

## Modules

| Module | Description |
|--------|-------------|
| 🎫 **Tickets** | Panel-based creation, categories, custom questions, staff claim, priority levels, HTML transcripts, auto-close, feedback |
| 📝 **Applications** | Multi-type forms, multi-page modals (10+ questions), review system, auto-role, staff notes, cooldowns |
| 💡 **Suggestions** | Voting, 10 status types, anonymous mode, auto-thread, staff responses, categories, leaderboard |
| 🎭 **Reaction Roles** | Button/select/reaction modes, exclusive groups, sticky/temp roles, max picks, persistent |
| 🎉 **Giveaways** | Button-entry, role requirements, bonus entries, drop mode, recurring, DM notifications |
| 📋 **Server Logging** | 30+ event types, per-event routing, message cache, invite tracking, ignore filters |
| 🛡️ **Moderation** | Case system, warnings with auto-escalation, quarantine, reputation, appeal system, anti-raid/nuke |
| 💰 **Economy** | Wallet/bank, daily/weekly, work/crime, gambling (coinflip/slots/blackjack/roulette/dice), shop, pets, heist, auction house |
| 🎨 **Embed Builder** | Webhook-based, Sapphire-style, templates, scheduling, variables |
| 📊 **Dashboard** | Web config integration for all modules (requires EveDash) |

## Requirements

- Red-DiscordBot >= 3.5.0
- Python >= 3.9

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs nexuscore
[p]load nexuscore
```

## Quick Start

```
[p]nexus                        # Module overview & version
[p]ticket setup #category #logs # Set up tickets
[p]apply setup #review          # Set up applications
[p]suggest setup #suggestions   # Set up suggestions
[p]roles create #channel button Title  # Create a role panel
[p]gw start #channel 1d 1 Prize       # Start a giveaway
[p]serverlog enable #logs       # Enable logging (30+ events)
[p]nmod setup #modlog           # Set up moderation
[p]eco balance                  # Check economy balance
[p]eb create                    # Interactive embed builder
```

## Key Commands

### Tickets
| Command | Description |
|---------|-------------|
| `[p]ticket setup <category> <log_channel>` | Set up the ticket system |
| `[p]ticket panel <channel>` | Send a ticket creation panel |
| `[p]ticket close [reason]` | Close a ticket |
| `[p]ticket add/remove <user>` | Add/remove user from ticket |
| `[p]ticket claim` | Claim a ticket as staff |
| `[p]ticket priority <level>` | Set ticket priority |
| `[p]ticket transcript` | Export HTML transcript |

### Moderation
| Command | Description |
|---------|-------------|
| `[p]nmod setup <modlog>` | Set up moderation |
| `[p]nmod warn <user> [reason]` | Warn a user (auto-escalates) |
| `[p]nmod mute/unmute <user>` | Mute/unmute |
| `[p]nmod kick/ban <user>` | Kick/ban |
| `[p]nmod case <id>` | View a case |
| `[p]nmod history <user>` | User's moderation history |
| `[p]nmod quarantine <user>` | Quarantine a user |
| `[p]nmod lockdown` | Lock the server |

### Economy
| Command | Description |
|---------|-------------|
| `[p]eco balance` | Check balance |
| `[p]eco daily / weekly` | Claim rewards |
| `[p]eco work / crime` | Earn money |
| `[p]eco coinflip / slots / blackjack` | Gamble |
| `[p]eco shop / buy / inventory` | Shop system |
| `[p]eco pet adopt <type>` | Adopt a pet |
| `[p]eco heist <amount>` | Start a multiplayer heist |
| `[p]eco leaderboard` | View rankings |

*Full command reference: `[p]help NexusCore`*

## Data Statement

This cog stores Discord user IDs, guild IDs, and channel IDs. Per-user data includes: ticket history, application submissions, suggestion authorship, moderation cases/warnings/notes, economy balances/inventories/pets/transactions, giveaway entries, and reaction role state.

## License

MIT
