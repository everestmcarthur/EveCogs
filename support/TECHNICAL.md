# Support Cog - Technical Documentation

## Command Override Mechanism

### How It Works

This cog replaces Red-DiscordBot's built-in `contact` and `dm` commands by disabling them when the cog loads and re-enabling them when it unloads.

### Implementation Details

#### On Load (`cog_load`)

```python
async def _disable_core_commands(self):
    """Disable Red's built-in contact and dm commands."""
    core_cog = self.bot.get_cog("Core")
    if not core_cog:
        return

    commands_to_disable = ["contact", "dm"]

    for cmd_name in commands_to_disable:
        cmd = self.bot.get_command(cmd_name)
        if cmd and cmd.cog_name == "Core":
            cmd.enabled = False
            self._disabled_core_commands.append(cmd_name)
```

**What happens:**
1. Gets the Core cog from Red
2. Finds the `contact` and `dm` commands
3. Verifies they belong to Core (not another cog)
4. Sets `enabled = False` on each command
5. Tracks which commands were disabled

#### On Unload (`cog_unload`)

```python
async def _enable_core_commands(self):
    """Re-enable Red's core commands when this cog unloads."""
    for cmd_name in self._disabled_core_commands:
        cmd = self.bot.get_command(cmd_name)
        if cmd:
            cmd.enabled = True
    self._disabled_core_commands.clear()
```

**What happens:**
1. Iterates through disabled commands
2. Finds each command
3. Sets `enabled = True` to restore them
4. Clears the tracking list

### Command Registration

The cog registers its own versions of these commands with the same names:

```python
@commands.command(name="contact")
@commands.dm_only()
async def contact(self, ctx: commands.Context, *, message: str):
    """Enhanced contact command"""
    # ... implementation

@commands.command(name="dm")
@commands.guild_only()
@commands.admin_or_permissions(manage_guild=True)
async def dm_command(self, ctx: commands.Context, user: discord.User, *, message: str):
    """Enhanced dm command"""
    # ... implementation
```

### Why This Approach?

**Pros:**
- ✅ Clean override without modifying Red's core
- ✅ Automatic restoration when unloaded
- ✅ No conflicts with other cogs
- ✅ Preserves command names users are familiar with
- ✅ Works with Red's permission system

**Alternatives considered:**
- ❌ Command name collision (Red would error)
- ❌ Monkey-patching (fragile and unsafe)
- ❌ Different command names (breaks user familiarity)

## Architecture

### Data Storage (Config)

#### Guild Settings
```python
DEFAULT_GUILD = {
    "enabled": False,
    "categories": {},  # name -> {channel_id, description, emoji, roles, greeting}
    "default_category": None,
    "log_channel": None,
    "mod_roles": [],
    "reply_with_embed": True,
    "show_author_info": True,
    "anonymous_mode": False,
    "thread_mode": False,
    "dm_on_reply": True,
    "active_threads": {},  # channel_id -> {user_id, category, started_at, message_count}
    "thread_timeout": 3600,
    "custom_greeting": "",
    "require_category": False,
}
```

#### User Settings
```python
DEFAULT_USER = {
    "blocked": False,
    "preference_category": None,
    "last_contact": 0,
}
```

### Message Flow

#### User → Staff

```
User (DM) → [p]contact message
    ↓
Check blocked status
    ↓
Select category (if multiple)
    ↓
Get category channel
    ↓
Send to staff channel (embed with user info)
    ↓
Log to log channel (if configured)
    ↓
Send confirmation to user
```

#### Staff → User

```
Staff (Guild) → [p]dm @user message
    ↓
Check permissions
    ↓
Format message (embed/plain, anonymous/named)
    ↓
Send DM to user
    ↓
Log to log channel (if configured)
    ↓
Confirm to staff
```

### UI Components

#### CategorySelectView
- Discord UI Select dropdown
- Shows up to 25 categories
- Includes emoji, name, and description
- 180 second timeout
- Returns selected category

#### SupportControlView
- Persistent view (timeout=None)
- Custom IDs for persistence across restarts
- Buttons: Close Thread, Block User
- Staff-only controls

#### ReplyModal
- Text input for staff replies
- Paragraph style (multi-line)
- 1900 character limit
- Sends reply on submit

### Background Tasks

#### Thread Cleanup Loop
```python
async def _thread_cleanup_loop(self):
    """Background task to clean up inactive threads."""
    # Runs every 5 minutes
    # Checks thread_timeout setting
    # Removes stale threads from active_threads
```

**Purpose:** Clean up inactive support threads based on guild settings

**Interval:** 5 minutes

**Action:** Removes threads older than `thread_timeout` seconds

## Security Considerations

### Permission Checks

1. **contact command:**
   - DM-only (`@commands.dm_only()`)
   - Checks user blocked status
   - Validates guild membership

2. **dm command:**
   - Guild-only (`@commands.guild_only()`)
   - Requires Manage Guild permission
   - Validates target user exists

3. **supportset commands:**
   - Guild-only
   - Requires Manage Guild permission
   - Validates input data

### Data Privacy

- User IDs stored (not usernames - they can change)
- Message content not stored (only transmitted)
- Last contact timestamp for rate limiting
- Blocked status for abuse prevention

### Error Handling

- `discord.Forbidden` - User has DMs disabled
- `discord.HTTPException` - Network/API errors
- Missing channels - Graceful degradation
- Invalid config - Falls back to defaults

## Performance

### Optimizations

1. **Config Caching:**
   - Red's Config system caches values
   - Only writes on changes

2. **Async Operations:**
   - All I/O is async
   - Background tasks don't block

3. **View Persistence:**
   - Views registered once at load
   - Reused across all interactions

4. **Minimal Database Writes:**
   - Bulk operations where possible
   - Async context managers for safety

### Scalability

- **Small servers (<100 members):** No issues
- **Medium servers (100-1000 members):** Optimized for this
- **Large servers (1000+ members):** Thread cleanup may need tuning

**Recommendations for large servers:**
- Increase `thread_timeout` to reduce cleanup frequency
- Use separate log channel (not same as support channel)
- Consider rate limiting (future feature)

## Compatibility

### Red-DiscordBot Versions
- **Minimum:** 3.5.0
- **Tested on:** 3.5.0+
- **Max:** Latest

### Python Versions
- **Minimum:** 3.8
- **Recommended:** 3.9+

### Discord.py Version
- Matches Red's discord.py version
- Uses discord.py 2.x features (UI components)

## Debugging

### Enable Debug Logging

```python
import logging
logging.getLogger("red.evecogs.support").setLevel(logging.DEBUG)
```

### Common Issues

**"Commands not found after loading"**
- Check if Core cog is loaded
- Verify `[p]load support` succeeded
- Try `[p]reload support`

**"Core commands still work"**
- Check cog load order
- Ensure no errors in console during load
- Try `[p]unload core` then `[p]load core` and `[p]load support`

**"Messages not showing up"**
- Verify channel exists: `[p]supportset list`
- Check bot permissions in target channel
- Ensure category is properly configured

**"Can't send DMs"**
- User likely has DMs disabled
- Check bot can DM users (not always possible)
- Verify user hasn't blocked the bot

## Testing

### Manual Testing Checklist

- [ ] Load cog successfully
- [ ] Core commands disabled
- [ ] `[p]contact` works in DMs
- [ ] Category selection appears (if multiple categories)
- [ ] Messages reach staff channel
- [ ] User info displays correctly
- [ ] `[p]dm` sends to users
- [ ] Logging works (if configured)
- [ ] Blocking works
- [ ] Unload restores core commands

### Test Cases

1. **Single Category:**
   - Create one category
   - Contact should go directly there
   - No category selection shown

2. **Multiple Categories:**
   - Create 2+ categories
   - Contact should show selection dropdown
   - Messages route to correct channels

3. **Blocked User:**
   - Block a user
   - User cannot contact
   - Error message shown

4. **Anonymous Mode:**
   - Enable anonymous mode
   - Staff replies hide names
   - Shows "Server Name Staff" instead

## Future Enhancements

Potential features for future versions:

- Rate limiting (X messages per hour)
- Priority queues
- Auto-responses
- Ticket numbers/IDs
- Thread persistence
- Multi-server support (user chooses)
- Attachment support
- Transcript generation
- Staff assignments
- SLA tracking
- Analytics dashboard

## Contributing

When contributing to this cog:

1. Maintain async/await patterns
2. Use type hints
3. Follow existing code style
4. Test with multiple guilds
5. Ensure commands still override properly
6. Update documentation

## License

Follows EveCogs repository license.
