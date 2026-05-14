# NewHelpMenu

Components V2 help menu + global embed/menu override for Red-DiscordBot.

## Features

- **Components V2 Help** — Replaces Red's entire help system with Discord's Components V2 (containers, sections, text displays, thumbnails, media galleries, separators)
- **Global Embed Override** — Optionally converts ALL bot embeds and menus into Components V2 layouts
- **Categories** — Group cogs into custom categories for organized help pages
- **Accent Colours** — Customizable colour scheme per-server
- **Layout Modes** — Multiple layout styles for help pages
- **Paginated Navigation** — Interactive buttons for browsing commands
- **Select Menus** — Quick-jump to any cog or command

## Requirements

- Red-DiscordBot >= 3.5.21
- Python >= 3.9

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs newhelpmenu
[p]load newhelpmenu
```

> ⚠️ This cog replaces Red's built-in `help` command. The original is restored on unload.

## Quick Start

```
[p]cv2 toggle          # Enable Components V2 (off by default)
[p]cv2 settings        # View all current settings
[p]cv2 color <hex>     # Set accent colour
[p]cv2 category add <name> <cog1> <cog2>...  # Group cogs into categories
```

## Commands

| Command | Description |
|---------|-------------|
| `[p]cv2 toggle` | Enable/disable Components V2 mode |
| `[p]cv2 settings` | View current configuration |
| `[p]cv2 color <hex>` | Set accent colour |
| `[p]cv2 category add <name> <cogs...>` | Create a cog category |
| `[p]cv2 category remove <name>` | Remove a category |
| `[p]cv2 category list` | List all categories |
| `[p]help` | Show the help menu (replaced) |
| `[p]help <command>` | Show help for a specific command |
| `[p]help <cog>` | Show help for a specific cog |

## Data Statement

This cog stores per-guild configuration. No personal user data is stored.

## License

MIT
