# EveDash

A modern, self-contained web dashboard for Red-DiscordBot.

## Features

- **Discord OAuth2 Login** — Secure authentication via Discord
- **Guild Management** — View and manage all guilds the bot is in
- **Cog Control** — Load, unload, and reload cogs from the browser
- **Command Toggles** — Enable/disable commands per-guild
- **Real-Time WebSocket** — Live updates for messages, members, and events
- **SDK for Cogs** — Any cog can register its own settings pages with just a few lines of code

## Requirements

- `aiohttp`
- Red-DiscordBot >= 3.5.0

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs dashboard
[p]load dashboard
```

## Setup

```
[p]evedash setup
```

Follow the interactive setup wizard to configure Discord OAuth2 credentials and server settings.

## Commands

| Command | Description |
|---------|-------------|
| `[p]evedash` | Show dashboard status and URL |
| `[p]evedash setup` | Interactive setup wizard |
| `[p]evedash port <port>` | Set the web server port |
| `[p]evedash host <host>` | Set the web server host/bind address |
| `[p]evedash secret <secret>` | Set the Discord OAuth2 client secret |
| `[p]evedash clientid <id>` | Set the Discord OAuth2 client ID |
| `[p]evedash redirect <uri>` | Set the OAuth2 redirect URI |

## Data Statement

This cog stores Discord user IDs for authentication sessions and blacklist management. No message content is stored.

## License

MIT
