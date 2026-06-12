# Support

A modernized DM/contact system that **replaces Red's built-in `contact` and `dm` commands** with enhanced features including categories, channels, custom greetings, logging, and more.

> **⚠️ Important:** When loaded, this cog **automatically disables** Red's core `contact` and `dm` commands, replacing them with its own enhanced versions. The core commands are re-enabled if you unload this cog.

## Features

### Core Features
- 🎯 **Category System** - Organize support messages by department/topic
- 📂 **Custom Channels** - Route different categories to specific channels
- 💬 **Enhanced DM System** - More powerful than the built-in dm command
- 🔒 **User Blocking** - Block abusive users from contacting staff
- 📝 **Logging** - Track all support interactions in a dedicated log channel
- 🎨 **Customizable** - Custom greetings, emojis, and messages per category

### Advanced Options
- 👻 **Anonymous Mode** - Hide staff names in replies
- 📋 **Category Selection** - Optional or required category selection
- 💎 **Embed Replies** - Beautiful embed formatting for messages
- ⏱️ **Thread Timeout** - Auto-close inactive support threads
- 🎭 **Role Permissions** - Category-specific staff roles

## Installation

```
[p]repo add evecogs https://github.com/yourusername/EveCogs
[p]cog install evecogs support
[p]load support
```

When you load this cog, it will:
1. ✅ Disable Red's core `contact` command
2. ✅ Disable Red's core `dm` command  
3. ✅ Register its own enhanced versions of these commands

If you unload the cog, the original core commands are automatically restored.

## Setup

### Basic Setup

1. **Enable the system:**
   ```
   [p]supportset enable
   ```

2. **Create a category:**
   ```
   [p]supportset addcategory general #support-general General support questions
   ```

3. **Set default category (optional):**
   ```
   [p]supportset defaultcategory general
   ```

4. **Configure logging (optional):**
   ```
   [p]supportset logchannel #support-logs
   ```

### Advanced Setup

**Add multiple categories:**
```
[p]supportset addcategory billing #billing-support Billing and payment questions
[p]supportset addcategory technical #tech-support Technical issues
[p]supportset addcategory reports #reports User reports and moderation
```

**Customize categories:**
```
[p]supportset setemoji billing 💳
[p]supportset setemoji technical 🔧
[p]supportset setgreeting billing Thank you for contacting billing support!
```

**Configure options:**
```
[p]supportset anonymous true          # Hide staff names in replies
[p]supportset requirecategory true    # Force users to select a category
[p]supportset embed true              # Use embeds for replies
[p]supportset showinfo true           # Show staff info in replies
```

## Commands

### User Commands

#### `[p]contact <message>`
*Can only be used in DMs*

Send a message to server staff. Users will be prompted to select a category if multiple are available.

**Examples:**
```
[p]contact I need help with my account
[p]contact Bug report: commands not working
```

### Staff Commands

#### `[p]dm <user> <message>`
*Requires: Manage Server permission*

Send a DM to a user from the server. Replaces Red's built-in dm command with enhanced logging and formatting.

**Examples:**
```
[p]dm @User Hello! We received your support request
[p]dm 123456789012345678 Your issue has been resolved
```

### Admin Commands

All admin commands require Manage Server permission.

#### `[p]supportset enable`
Enable the support system for your server.

#### `[p]supportset disable`
Disable the support system for your server.

#### `[p]supportset addcategory <name> <channel> [description]`
Create a new support category.

**Example:**
```
[p]supportset addcategory billing #billing "Billing questions and payment issues"
```

#### `[p]supportset removecategory <name>`
Remove a support category.

#### `[p]supportset setemoji <category> <emoji>`
Set an emoji for a category (shown in category selection).

**Example:**
```
[p]supportset setemoji billing 💳
```

#### `[p]supportset setgreeting <category> <message>`
Set a custom greeting shown to users when they contact this category.

**Example:**
```
[p]supportset setgreeting billing Thanks for contacting billing! We'll respond within 24 hours.
```

#### `[p]supportset defaultcategory <name>`
Set the default category (used if only one category or user preference).

#### `[p]supportset logchannel [channel]`
Set or clear the log channel for support messages.

**Examples:**
```
[p]supportset logchannel #support-logs
[p]supportset logchannel              # Clear log channel
```

#### `[p]supportset anonymous <true/false>`
Toggle anonymous mode (hides staff member names in replies).

#### `[p]supportset requirecategory <true/false>`
Toggle whether users must select a category.

#### `[p]supportset embed <true/false>`
Toggle using embeds for replies.

#### `[p]supportset showinfo <true/false>`
Toggle showing staff member info in replies.

#### `[p]supportset list`
Display all categories and current settings.

#### `[p]supportset block <user>`
Block a user from using the support system.

#### `[p]supportset unblock <user>`
Unblock a user from using the support system.

## Usage Examples

### Example 1: Simple Support Setup

Single category for all support:
```
[p]supportset enable
[p]supportset addcategory support #support-tickets General support
[p]supportset defaultcategory support
```

### Example 2: Multi-Category Setup

Different departments:
```
[p]supportset enable
[p]supportset addcategory general #general-support General questions
[p]supportset addcategory billing #billing Billing and payments
[p]supportset addcategory technical #tech-support Technical issues
[p]supportset addcategory reports #reports Report users or content

[p]supportset setemoji general 📝
[p]supportset setemoji billing 💳
[p]supportset setemoji technical 🔧
[p]supportset setemoji reports 🚨

[p]supportset requirecategory true
[p]supportset logchannel #support-logs
```

### Example 3: Anonymous Support

For servers that want anonymous staff replies:
```
[p]supportset enable
[p]supportset addcategory anonymous #anon-support Anonymous support
[p]supportset anonymous true
[p]supportset showinfo false
```

## How It Works

### User Experience

1. User sends `[p]contact <message>` in DMs
2. If multiple categories exist, they select one from a dropdown
3. Message is sent to the configured channel for that category
4. Staff can reply using `[p]dm <user> <message>`
5. User receives the reply in DMs

### Staff Experience

1. Support messages appear in category-specific channels
2. Each message shows user info, category, roles, join date
3. Staff reply with `[p]dm @user message`
4. All interactions are logged (if log channel is set)
5. Staff can block abusive users with control buttons

## Configuration Storage

- **Guild Settings**: Categories, channels, logging, options
- **User Settings**: Block status, category preferences, last contact time

## Comparison to Built-in Commands

| Feature | Red Built-in | Support Cog |
|---------|-------------|-------------|
| Basic contact/dm | ✅ | ✅ |
| Categories | ❌ | ✅ |
| Custom channels | ❌ | ✅ |
| Custom greetings | ❌ | ✅ |
| User blocking | ❌ | ✅ |
| Logging | Limited | ✅ Full |
| Embeds | Basic | ✅ Enhanced |
| Anonymous mode | ❌ | ✅ |
| Category emojis | ❌ | ✅ |
| Multi-server | Limited | ✅ Better |

## Tips

- **Use categories** to organize by department (billing, tech, general)
- **Set custom greetings** to set response time expectations
- **Enable logging** to keep track of all support interactions
- **Use anonymous mode** if staff prefer to keep names private
- **Block abusive users** to prevent spam

## Support & Feedback

For issues, suggestions, or contributions, please visit the [EveCogs repository](https://github.com/yourusername/EveCogs).

## Credits

Created for Red-DiscordBot V3 as a modernized replacement for the built-in contact/dm system.
