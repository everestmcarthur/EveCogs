# 🌀 EveCogs

A premium cog repository for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot).

## Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs <cog_name>
[p]load <cog_name>
```

### Available Cogs

| Cog | Description |
|-----|-------------|
| **[Wormhole](#-wormhole-v320)** | Ultimate cross-server message relay — DM relay, starboard, karma, auto-mod, 50+ commands |
| **[NewHelpMenu](#-new-help-menu-v100)** | Fully customisable interactive help system — categories, buttons, themes, search, favourites |

---

# 📖 New Help Menu v1.0.0

**The ultimate customisable help system for Red-DiscordBot.**

Completely replaces Red's default help formatter with a modern, interactive experience powered by Discord buttons, select menus, modals, and rich embeds. Every aspect is configurable — from categories and colours to button styles and role gating.

## ✨ Features

### 🎨 Themes & Branding
- **4 built-in themes** — `default`, `minimal`, `compact`, `dark`
- **Full custom mode** — control every visual aspect independently
- **Custom accent colours** — per-server or per-category
- **Thumbnails & images** — custom icons on home page and per-category
- **Title, description, tagline, footer** — fully templated with `{bot_name}` and `{prefix}` placeholders
- **Footer icons** — custom footer branding

### 📂 Custom Categories
- **Create unlimited categories** — group cogs however you want
- **Per-category customisation** — emoji, colour, thumbnail, image, description
- **Ordering** — set display order for each category
- **Role gating** — restrict category visibility to specific roles
- **Hide/unhide** — toggle category visibility
- **Auto-categories** — uncategorised cogs get their own section automatically
- **Rename** — change category labels on the fly

### 🔘 Interactive Navigation
- **Select menu dropdown** — jump between categories instantly
- **Button navigation** — category buttons when select menus are disabled
- **Pagination** — ◀️ ▶️ buttons with page counter
- **Command detail view** — click into any command for full docs, subcommands, aliases
- **Back navigation** — return to previous views seamlessly
- **Close button** — dismiss the menu

### 🔍 Search
- **Modal search** — pop-up search dialog searches command names, descriptions, aliases, and help text
- **Results view** — shows matching commands with their category
- **Fuzzy matching** — finds commands across all categories

### ⭐ Favourites
- **Per-user favourites** — save frequently-used commands
- **Star button** — add/remove favourites from the detail view
- **Favourites page** — quick access from the main menu
- **Command-based** — `[p]fav <command>` to toggle

### 🛡️ Visibility Control
- **Hide cogs** — remove entire cogs from help
- **Hide commands** — blacklist specific commands
- **Show hidden** — toggle visibility of hidden commands for admins
- **Permission-based filtering** — only shows commands the user can actually run
- **Role-gated categories** — restrict categories to certain roles

### ⚙️ Display Options
- **Aliases** — show/hide command aliases
- **Cooldowns** — show/hide cooldown info
- **Permissions** — show/hide required permission levels
- **Signatures** — show/hide command usage signatures
- **Timestamps** — toggle embed timestamps
- **Subcommand counts** — groups show number of subcommands

### 🔗 Quick Links
- **URL buttons** — add up to 5 link buttons (support server, docs, website, etc.)
- **Custom emoji** — set emoji per link button

### 📧 Delivery Options
- **DM help** — send help to DMs instead of the channel
- **Ephemeral mode** — only visible to the user (slash command contexts)
- **Auto-delete** — delete help messages after configurable seconds
- **Timeout** — interactive view timeout (default 3 minutes)

### 🏠 Home Page Extras
- **Custom fields** — add informational fields to the home embed
- **Home image** — large image on the home page
- **Category overview** — shows all categories with command counts

## 📋 Quick Start

```
[p]cog install EveCogs newhelpmenu
[p]load newhelpmenu
```

That's it! The default help command is now interactive. Customise further:

```
[p]helpmenu theme dark
[p]helpmenu colour #FF6B6B
[p]helpmenu title "🤖 {bot_name} Commands"
[p]helpmenu desc "Use the menu below to browse all commands!"
[p]helpmenu tagline "Powered by EveCogs"

[p]helpmenu cat create Moderation 🛡️ All moderation commands
[p]helpmenu cat addcog Moderation Mod
[p]helpmenu cat addcog Moderation AutoMod
[p]helpmenu cat colour Moderation #E74C3C

[p]helpmenu cat create Fun 🎮 Games and entertainment
[p]helpmenu cat addcog Fun Trivia
[p]helpmenu cat addcog Fun CustomCommands

[p]helpmenu quicklink add "Support" https://discord.gg/your-server 🔗
[p]helpmenu quicklink add "Docs" https://your-docs-site.com 📄

[p]helpmenu set selectmenu on
[p]helpmenu set buttons on
[p]helpmenu set aliases on
[p]helpmenu set dmhelp off
[p]helpmenu set maxperpage 10

[p]helpmenu preview
```

## 📖 Command Reference

### Main Settings (`[p]helpmenu` / `[p]hm`)
| Command | Description |
|---------|-------------|
| `helpmenu toggle` | Enable/disable the custom help menu |
| `helpmenu theme <name>` | Set theme: default, minimal, compact, dark, custom |
| `helpmenu colour <hex>` | Set accent colour |
| `helpmenu resetcolour` | Reset to bot default colour |
| `helpmenu thumbnail [url]` | Set/reset home thumbnail |
| `helpmenu title <text>` | Set title (supports `{bot_name}`, `{prefix}`) |
| `helpmenu description <text>` | Set home description |
| `helpmenu footer <text>` | Set footer text |
| `helpmenu footericon [url]` | Set footer icon |
| `helpmenu tagline [text]` | Set/clear tagline |
| `helpmenu homeimage [url]` | Set/reset home page image |
| `helpmenu buttonstyle <style>` | Set button style: primary, secondary, success, danger |
| `helpmenu pagestyle <style>` | Set pagination button style |
| `helpmenu uncatlabel <text>` | Set uncategorised section label |
| `helpmenu uncatdesc <text>` | Set uncategorised description |
| `helpmenu hideuncat` | Toggle hiding uncategorised section |
| `helpmenu preview` | Preview the help menu |
| `helpmenu settings` | Show all current settings |
| `helpmenu reset` | Reset everything to defaults |

### Toggle Settings (`[p]helpmenu set`)
| Setting | Description |
|---------|-------------|
| `aliases` | Show/hide command aliases |
| `cooldown` | Show/hide cooldown info |
| `permissions` | Show/hide required permissions |
| `signature` | Show/hide command signatures |
| `hidden` | Show/hide hidden commands |
| `timestamp` | Show/hide embed timestamps |
| `selectmenu` | Enable/disable select menu dropdown |
| `buttons` | Enable/disable category buttons |
| `dmhelp` | Send help to DMs |
| `ephemeral` | Ephemeral responses (slash commands) |
| `favourites` | Enable/disable favourites system |
| `search` | Enable/disable search |
| `sortcommands` | Sort commands alphabetically |
| `sortcategories` | Sort categories by order |
| `timeout` | View timeout in seconds (number) |
| `deleteafter` | Auto-delete after seconds (number, 0=never) |
| `maxperpage` | Commands per page (number) |

### Categories (`[p]helpmenu category` / `[p]hm cat`)
| Command | Description |
|---------|-------------|
| `cat create <name> [emoji] [desc]` | Create a new category |
| `cat delete <name>` | Delete a category |
| `cat rename <old> <new>` | Rename a category |
| `cat emoji <name> [emoji]` | Set/clear category emoji |
| `cat description <name> [desc]` | Set category description |
| `cat colour <name> <hex>` | Set category embed colour |
| `cat thumbnail <name> [url]` | Set category thumbnail |
| `cat image <name> [url]` | Set category large image |
| `cat order <name> <number>` | Set display order (lower = first) |
| `cat hide <name>` | Hide a category |
| `cat unhide <name>` | Show a hidden category |
| `cat requirerole <name> [role]` | Set/clear role requirement |
| `cat addcog <name> <CogName>` | Assign a cog to a category |
| `cat removecog <name> <CogName>` | Remove a cog from a category |
| `cat list` | List all categories |

### Visibility (`[p]helpmenu hide` / `unhide`)
| Command | Description |
|---------|-------------|
| `hide cog <CogName>` | Hide a cog from help |
| `hide command <name>` | Hide a command from help |
| `unhide cog <CogName>` | Unhide a cog |
| `unhide command <name>` | Unhide a command |
| `hide list` | List all hidden items |

### Quick Links (`[p]helpmenu quicklink` / `ql`)
| Command | Description |
|---------|-------------|
| `ql add <label> <url> [emoji]` | Add a quick link button |
| `ql remove <label>` | Remove a quick link |
| `ql list` | List all quick links |

### Home Fields (`[p]helpmenu field`)
| Command | Description |
|---------|-------------|
| `field add <name> <value>` | Add a field (append `--inline` for inline) |
| `field remove <name>` | Remove a field |
| `field clear` | Clear all fields |
| `field list` | List all fields |

### User Commands
| Command | Description |
|---------|-------------|
| `[p]favourite <command>` | Toggle a command in your favourites |
| `[p]favourites` | View your favourite commands |

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

Run `[p]wh help` in Discord for the full interactive reference.

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

---

## 📊 Repository Structure

```
EveCogs/
├── README.md
├── LICENSE (MIT)
├── info.json (repo metadata)
├── wormhole/
│   ├── __init__.py
│   ├── info.json
│   ├── utils.py
│   └── wormhole.py       (2,200+ lines, 50+ commands)
└── newhelpmenu/
    ├── __init__.py
    ├── info.json
    └── newhelpmenu.py     (1,100+ lines, 50+ commands)
```

## 📄 License

MIT — see [LICENSE](LICENSE).

## 🤝 Credits

Built by [everestmcarthur](https://github.com/everestmcarthur) with assistance from Viktor AI.
