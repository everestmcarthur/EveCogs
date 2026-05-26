# Wormhole Module Map

## Quick Reference: Where to Find Code

### Core & Entry
| File | Purpose | Key Contents |
|------|---------|--------------|
| `__init__.py` | Red entry point | `setup()` function |
| `core.py` | Main cog class | Wormhole class, `__init__()`, `_init()`, helper methods |
| `utils.py` | Shared utilities | Embed builders, formatters, detectors |

### Commands (all in `commands/`)
| Module | Commands | Description |
|--------|----------|-------------|
| `_base.py` | `wh` + subgroups | Root command group definitions |
| `network.py` | `create`, `delete`, `info`, `list` | Network CRUD |
| `settings.py` | `set`, `mode`, `rate-limit`, `slowmode` | Network configuration |
| `moderation.py` | `freeze`, `ban`, `kick`, `mute`, `purge` | Moderation tools |
| `staff.py` | `promote`, `demote`, `staff-list`, `invite-create` | Staff management |
| `filters.py` | `filter add/remove`, `automod enable/disable` | Content filtering |
| `social.py` | `starboard`, `karma`, `profile`, `highlight` | Social features |
| `dm.py` | `dm-relay`, `dm-send` | DM relay |
| `mentions.py` | `mentions set/status/exempt` | Mention policy |
| `tos.py` | `tos enable/set/accepted` | Terms of Service |
| `reports.py` | `report message/list/resolve` | User reports |
| `bridge.py` | `bridge add/remove/list` | Network bridging |
| `advanced.py` | `poll`, `afk`, `autoreply`, `bookmark` | Advanced features |
| `debug.py` | `debug`, `trace`, `health`, `analytics` | Debugging tools |

### Listeners (all in `listeners/`)
| Module | Events | Description |
|--------|--------|-------------|
| `relay.py` | `on_message`, `on_message_delete` | Main relay pipeline |
| `sync.py` | `on_message_edit`, `on_reaction_add/remove` | Edit/delete/reaction sync |
| `misc.py` | `on_guild_join`, `on_member_join` | Miscellaneous events |

### Models (all in `models/`)
| Module | Contents | Purpose |
|--------|----------|---------|
| `config.py` | `DEFAULT_GLOBAL`, `DEFAULT_NETWORK` | Config schemas |
| `message_map.py` | `MessageMap` class | Message ID tracking |
| `permissions.py` | `Role` enum, role helpers | Staff hierarchy |

### Services (all in `services/`)
| Module | Functions | Purpose |
|--------|-----------|---------|
| `emoji.py` | `resolve_foreign_emojis()`, `build_emoji_embeds_and_files()` | Emoji relay |

### UI (all in `ui/`)
| Module | Classes | Purpose |
|--------|---------|---------|
| `modals.py` | `ReportModal` | Report submission form |
| `views.py` | `reply_jump_view()` | Reply jump buttons |

---

## Command Flow Example

**User runs**: `[p]wh create mynetwork`

1. Red routes to `wh` command group (defined in `commands/_base.py`)
2. Red dispatches to `create` subcommand
3. `NetworkCommands.wh_create()` in `commands/network.py` executes
4. Method accesses `self.config` (initialized in `core.py.__init__()`)
5. Calls `self._log()` helper (defined in `core.py`)
6. Sends response embed using `ok_embed()` from `utils.py`

---

## Relay Flow Example

**User sends message** in linked channel:

1. `RelayListener.on_message()` in `listeners/relay.py` fires
2. Checks `self._ready.wait()` (initialized in `core.py`)
3. Fetches network data via `self._net()` (defined in `core.py`)
4. Checks filters, automod, cooldowns (state in `core.py`)
5. Resolves foreign emojis via `services/emoji.py`
6. Builds relay embed with `utils.py` helpers
7. Gets webhook from `self.webhook_cache` (in `core.py`)
8. Sends to all linked channels
9. Updates `self.msg_map` (MessageMap from `models/message_map.py`)

---

## Inheritance Hierarchy

```
commands.Cog
    ↑
Wormhole (core.py)
    ↑ inherits from all:
    ├── RelayListener (listeners/relay.py)
    ├── SyncListener (listeners/sync.py)
    ├── MiscListener (listeners/misc.py)
    ├── NetworkCommands (commands/network.py)
    ├── SettingsCommands (commands/settings.py)
    ├── ModerationCommands (commands/moderation.py)
    ├── StaffCommands (commands/staff.py)
    ├── FilterCommands (commands/filters.py)
    ├── SocialCommands (commands/social.py)
    ├── DMCommands (commands/dm.py)
    ├── AdvancedCommands (commands/advanced.py)
    ├── MentionCommands (commands/mentions.py)
    ├── ToSCommands (commands/tos.py)
    ├── ReportCommands (commands/reports.py)
    ├── BridgeCommands (commands/bridge.py)
    └── DebugCommands (commands/debug.py)
         ↑ all inherit from
         WormholeBase (commands/_base.py)
```

---

## State Management

All mutable state lives in `core.py`:

```python
class Wormhole(...):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(...)
        
        # Caches
        self.webhook_cache: Dict[int, discord.Webhook] = {}
        
        # Rate limiting
        self.cooldowns: Dict[str, CooldownBucket] = {}
        self.slowmode_tracker: Dict[str, Dict[int, float]] = {}
        
        # Anti-abuse
        self.dup_detectors: Dict[str, DuplicateDetector] = {}
        self.raid_detectors: Dict[str, RaidDetector] = {}
        
        # Message tracking
        self.msg_map = MessageMap()  # from models/message_map.py
        
        # Background tasks
        self._ready = asyncio.Event()
        self._bg_tasks: List[asyncio.Task] = []
        self._ctx_menus: List[app_commands.ContextMenu] = []
```

All command/listener mixins access this state via `self.<attribute>`.

---

## Adding New Features

### New Command Category

1. Create `commands/newcategory.py`:
```python
from ._base import WormholeBase

class NewCategoryCommands(WormholeBase):
    @WormholeBase.wh.group(name="newcat", invoke_without_command=True)
    async def wh_newcat(self, ctx):
        """New category commands."""
        await ctx.send_help(ctx.command)
    
    @wh_newcat.command(name="something")
    async def wh_newcat_something(self, ctx):
        """Do something."""
        await ctx.send("Done!")
```

2. Export in `commands/__init__.py`:
```python
from .newcategory import NewCategoryCommands
__all__ = [..., "NewCategoryCommands"]
```

3. Inherit in `core.py`:
```python
class Wormhole(
    ...,
    NewCategoryCommands,  # ← add here
    commands.Cog,
):
```

### New Listener

1. Add to existing `listeners/*.py` or create new:
```python
class NewListener:
    @commands.Cog.listener()
    async def on_some_event(self, ...):
        """Handle event."""
        ...
```

2. Export in `listeners/__init__.py`
3. Inherit in `core.py`

### New Service

1. Create `services/myservice.py`:
```python
async def do_something(param: str) -> str:
    """Service logic."""
    return result
```

2. Import in modules that need it:
```python
from ..services.myservice import do_something
```

---

## File Size Reference

```
Total: ~145 KB of code (excluding old monolith)

Largest modules:
  core.py:           32 KB  (731 lines)
  listeners/relay.py: 23 KB  (main relay logic)
  commands/settings.py: 19 KB  (352 lines)
  commands/advanced.py: 21 KB  (411 lines)
  utils.py:          18 KB  (shared utilities)

Average command module: 8-12 KB (100-200 lines)
Average listener: 2-23 KB (50-600 lines)
Average model: 2-12 KB (50-300 lines)
```

---

## Checklist: Before Committing Changes

- [ ] Run `python3 -m py_compile wormhole/**/*.py` (no syntax errors)
- [ ] Check imports in `__init__.py` files are up-to-date
- [ ] Verify `core.py` inherits from all mixins
- [ ] Test the changed command/listener in Discord
- [ ] Update this map if you added/removed modules
- [ ] Update `ARCHITECTURE.md` if structure changed

---

## Quick Grep Patterns

```bash
# Find all commands
grep -r "@.*\.command" wormhole/commands/

# Find all listeners
grep -r "@commands.Cog.listener" wormhole/listeners/

# Find where a helper method is defined
grep -rn "def _method_name" wormhole/

# Find all uses of config
grep -r "self.config" wormhole/ | grep -v ".pyc"

# Find all webhook operations
grep -r "webhook" wormhole/ --include="*.py"

# Find message relay code
grep -r "relay" wormhole/listeners/
```
