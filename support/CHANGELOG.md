# Changelog

All notable changes to the Support cog will be documented in this file.

## [1.0.0] - 2026-06-12

### Initial Release

#### Core Features
- ✅ Replaces Red's built-in `contact` command with enhanced version
- ✅ Replaces Red's built-in `dm` command with enhanced version
- ✅ Automatic command override system (disables core commands on load)
- ✅ Automatic restoration (re-enables core commands on unload)

#### Category System
- Multiple support categories with dedicated channels
- Custom emojis per category
- Custom descriptions per category
- Custom greetings per category
- Category selection dropdown UI
- Default category setting
- Optional/required category selection

#### User Features
- `[p]contact <message>` - Send messages to staff from DMs
- Category selection (if multiple categories configured)
- Custom greeting messages
- Block status checking
- Last contact tracking

#### Staff Features
- `[p]dm <user> <message>` - Enhanced DM system
- Rich user information in messages (roles, join date, ID)
- Embed formatting for professional appearance
- Anonymous mode support
- Logging to dedicated log channel

#### Admin Commands
- `[p]supportset enable/disable` - Toggle system
- `[p]supportset addcategory` - Create categories
- `[p]supportset removecategory` - Remove categories
- `[p]supportset setemoji` - Set category emojis
- `[p]supportset setgreeting` - Set category greetings
- `[p]supportset defaultcategory` - Set default category
- `[p]supportset logchannel` - Configure logging
- `[p]supportset anonymous` - Toggle anonymous mode
- `[p]supportset requirecategory` - Require category selection
- `[p]supportset embed` - Toggle embed formatting
- `[p]supportset showinfo` - Toggle author info display
- `[p]supportset list` - View all settings
- `[p]supportset block/unblock` - User blocking

#### UI Components
- Category selection dropdown with emojis and descriptions
- Support control buttons (Close Thread, Block User)
- Reply modal for staff responses
- Persistent views with custom IDs

#### Configuration
- Per-guild settings
- Per-user settings (blocked status, preferences)
- Active thread tracking
- Comprehensive logging system

#### Technical
- Full async/await implementation
- Background thread cleanup task
- Config-based data storage
- Type hints throughout
- Error handling for all Discord API calls
- Permission validation
- Red 3.5.0+ compatibility

#### Documentation
- README.md - Full documentation
- QUICKSTART.md - Quick setup guide
- EXAMPLES.md - Configuration examples
- TECHNICAL.md - Technical documentation
- CHANGELOG.md - Version history

### Command Override Implementation

The cog uses a clean override mechanism:
```python
async def _disable_core_commands(self):
    """Disable Red's built-in contact and dm commands."""
    core_cog = self.bot.get_cog("Core")
    commands_to_disable = ["contact", "dm"]
    for cmd_name in commands_to_disable:
        cmd = self.bot.get_command(cmd_name)
        if cmd and cmd.cog_name == "Core":
            cmd.enabled = False
```

### Known Limitations

- Users must be in the server to use contact (by design)
- DMs must be enabled for user to receive replies
- Maximum 25 categories (Discord dropdown limit)
- Thread cleanup runs every 5 minutes (configurable in code)

### Future Considerations

Potential features for future versions:
- Rate limiting
- Priority queues
- Auto-responses
- Ticket numbers
- Transcript generation
- Staff assignments
- Analytics

---

## Version Numbering

This project follows [Semantic Versioning](https://semver.org/):
- MAJOR version for incompatible API changes
- MINOR version for new functionality in a backward compatible manner
- PATCH version for backward compatible bug fixes

## Release Notes Format

Each version includes:
- **Added** - New features
- **Changed** - Changes to existing functionality
- **Deprecated** - Soon-to-be removed features
- **Removed** - Removed features
- **Fixed** - Bug fixes
- **Security** - Security vulnerability fixes
