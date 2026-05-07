# EveCogs

> A curated collection of advanced, professional-grade cogs for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot).

---

## 📦 Installation

```
[p]repo add EveCogs https://github.com/everestmcarthur/EveCogs
[p]cog install EveCogs <cog_name>
[p]load <cog_name>
```

---

## 🌀 Wormhole

**The most advanced cross-server relay system for Red-DiscordBot.**

Connect channels across unlimited servers into named networks. Every message, edit, delete, reaction, reply, sticker, embed, and file is relayed in real-time via webhooks — with full moderation, staff roles, filters, rate-limiting, and per-network customisation.

### Highlights

| Feature | Description |
|---|---|
| **Named Networks** | Create unlimited named networks — each with its own config, staff, and channels |
| **Webhook Relay** | Messages appear under the sender's name and avatar (or server icon, or custom) |
| **Edit & Delete Sync** | Edits and deletes propagate across every linked channel instantly |
| **Reply Context** | Replies include a preview of the referenced message |
| **Reaction Sync** | Reactions mirror across channels |
| **Sticker & Embed Forwarding** | Stickers, rich embeds, and file attachments are all relayed |
| **Staff System** | Network owner + unlimited staff with moderation access |
| **User Ban / Mute** | Ban or mute individual users from the network |
| **Server Ban / Mute** | Block or silence entire servers |
| **Server Allowlist** | Restrict which servers may join a network |
| **Word & Regex Filters** | Auto-delete messages that match filters before relay |
| **Rate Limiting** | Token-bucket per-user per-network spam protection |
| **Logging Channel** | Designate a channel to receive moderation logs |
| **Custom Identity** | Name mode (user / server / both / custom template), image mode, custom icon |
| **Server Nicknames** | Override how your server's name appears on the network |
| **Freeze / Pause** | Temporarily halt all relay on a network |
| **Silent Mode** | Suppress join/leave announcements |
| **NSFW Gating** | Block relay from NSFW channels |
| **Thread Support** | Optionally relay messages from threads |
| **Ownership Transfer** | Hand a network to another user |
| **Statistics** | Track total messages relayed, channels linked, and more |

### Quick Start

```
[p]wh create my-network A cool global chat
[p]wh open my-network          (run in each channel you want linked)
[p]wh set webhooks my-network true
[p]wh set name-mode my-network both
[p]wh info my-network
[p]wh help
```

### Command Overview

| Group | Commands |
|---|---|
| `[p]wh` | `create`, `delete`, `open`, `close`, `list`, `info`, `stats`, `transfer`, `help` |
| `[p]wh set` | `webhooks`, `name-mode`, `image-mode`, `custom-icon`, `custom-name`, `description`, `colour`, `ratelimit`, `log-channel`, `nickname`, `freeze`, `silent`, `nsfw-gate`, `sync-edits`, `sync-deletes`, `sync-reactions`, `sync-replies`, `sync-stickers`, `sync-threads`, `forward-embeds` |
| `[p]wh staff` | `add`, `remove`, `list` |
| `[p]wh mod` | `ban`, `unban`, `mute`, `unmute`, `ban-server`, `unban-server`, `mute-server`, `unmute-server`, `allowlist-add`, `allowlist-remove` |
| `[p]wh filter` | `add-word`, `remove-word`, `add-regex`, `remove-regex`, `list` |

---

## 📄 License

MIT — do whatever you want.

---

*Made with ❤️ by everestmcarthur*
