# UserSlash

User-installable slash commands for Red-DiscordBot — every Red command works in servers, DMs, and group DMs.

## What It Does

UserSlash registers a single proxy slash command (named after the bot) that bridges *every* Red text command through Discord's slash-command interface. After syncing, all global commands are automatically patched with user-install integration types so the bot works as a user-installable app.

Commands work everywhere:
- ✅ Guild channels (where the bot is a member)
- ✅ Bot DMs
- ✅ Group DMs
- ✅ Servers where the bot *isn't* a member (via user-install)

## Requirements

- Red-DiscordBot >= 3.5.0
- Python >= 3.9
- `rapidfuzz` (auto-installed)

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs userslash
[p]load userslash
```

> ⚠️ **Unload OneTrueSlash first** if you have it loaded — this cog replaces it.

## Setup (One-Time)

1. Go to the **Discord Developer Portal** → Your Application → **Installation**
2. Under *Installation Contexts*, enable **User Install**
3. Under *Default Install Settings — User Install*, add the `applications.commands` scope
4. Run `[p]userslash sync` to register & patch commands
5. Share the OAuth2 User-Install link so users can add your bot to their profile

## Commands (Owner Only)

| Command | Description |
|---------|-------------|
| `[p]userslash sync` | Sync the command tree + patch every command for user-install |
| `[p]userslash patch` | Patch already-synced commands with user-install flags (no full sync) |
| `[p]userslash status` | Show per-command user-install status (✅/⚠️) |

### Whitelist
| Command | Description |
|---------|-------------|
| `[p]userslash whitelist enable` | Restrict user-install to whitelisted users only |
| `[p]userslash whitelist disable` | Allow anyone to use user-install |
| `[p]userslash whitelist add <@users>` | Add users to the whitelist |
| `[p]userslash whitelist remove <@users>` | Remove users from the whitelist |
| `[p]userslash whitelist list` | View whitelist status and members |
| `[p]userslash whitelist clear` | Clear the entire whitelist |

## Architecture

```
userslash/
├── __init__.py       # Cog class, lifecycle, owner commands, whitelist
├── slash_bridge.py   # Proxy slash command, autocomplete, error handler
├── patcher.py        # REST API patcher for user-install flags
├── context.py        # InterContext — adapted Context for interactions
├── channel.py        # Fake channel for DM/group-DM contexts
├── message.py        # Synthetic Message for interaction contexts
└── utils.py          # Name validation helpers
```

## How It Works

1. On load, registers `/<botname>` as a global slash command with `integration_types: [0, 1]` (guild + user install)
2. The slash command accepts a `command` parameter with fuzzy autocomplete
3. When invoked, it finds the matching Red text command and executes it through Red's command system
4. `InterContext` wraps the interaction to look like a regular `commands.Context`
5. `patch_all_commands` hits the Discord REST API to add user-install flags to every registered command

## Data Statement

This cog does not persistently store any data or metadata about users.

## License

MIT
