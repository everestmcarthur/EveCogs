# Support Cog - Quick Start

## What This Cog Does

**Automatically disables and replaces** Red's built-in `contact` and `dm` commands with a modernized system featuring:
- **Categories** - Route messages to different channels by topic
- **Customization** - Custom greetings, emojis, and messages
- **Logging** - Track all support interactions
- **User Management** - Block abusive users
- **Enhanced Features** - Embeds, anonymous mode, and more

## 5-Minute Setup

### 1. Load the Cog
```
[p]load support
```
*(This automatically disables Red's core `contact` and `dm` commands)*

### 2. Enable It
```
[p]supportset enable
```

### 3. Create Your First Category
```
[p]supportset addcategory general #support General support questions
```

### 4. Set as Default
```
[p]supportset defaultcategory general
```

### 5. Done! 
Users can now use `[p]contact <message>` in DMs to contact staff!

## Quick Commands Reference

### Users
- `[p]contact <message>` - Contact server staff (DM only)

### Staff  
- `[p]dm <user> <message>` - Reply to users

### Admin
- `[p]supportset enable` - Turn it on
- `[p]supportset addcategory <name> <channel> [desc]` - Add category
- `[p]supportset list` - View settings
- `[p]supportset block <user>` - Block a user
- `[p]supportset logchannel <channel>` - Set logging

## Example Multi-Category Setup

```bash
# Create categories
[p]supportset addcategory general #general-support General questions
[p]supportset addcategory billing #billing Billing support
[p]supportset addcategory technical #tech-support Tech issues

# Add emojis
[p]supportset setemoji general 💬
[p]supportset setemoji billing 💳
[p]supportset setemoji technical 🔧

# Add custom greetings
[p]supportset setgreeting billing We'll respond within 24 hours!
[p]supportset setgreeting technical Our tech team will assist you shortly.

# Require category selection
[p]supportset requirecategory true

# Enable logging
[p]supportset logchannel #support-logs
```

## Key Features

### For Users
- Clean DM interface
- Category selection dropdown
- Custom greetings per category
- Knows which server to contact

### For Staff
- Messages organized by category
- See user info (roles, join date, ID)
- Reply with enhanced `[p]dm` command
- Block abusive users easily
- Optional anonymous replies

### For Admins
- Full customization
- Multiple categories
- Per-category channels
- Comprehensive logging
- Flexible permissions

## Need Help?

See the full [README.md](README.md) for detailed documentation and examples.
