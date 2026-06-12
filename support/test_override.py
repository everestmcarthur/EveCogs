"""
Test script to verify command override mechanism works correctly.

This script demonstrates how the Support cog disables and re-enables
Red's core commands.

Usage: This is for reference/testing only. The actual override happens
automatically when the cog loads.
"""

class CommandOverrideTest:
    """
    Simulates the command override process that happens in the Support cog.
    """

    def __init__(self, bot):
        self.bot = bot
        self._disabled_core_commands = []

    def test_disable_commands(self):
        """Test disabling core commands."""
        print("🔧 Testing command disable mechanism...")

        # Get Core cog
        core_cog = self.bot.get_cog("Core")
        if not core_cog:
            print("❌ Core cog not found")
            return False

        print("✅ Core cog found")

        # Commands to disable
        commands_to_disable = ["contact", "dm"]

        for cmd_name in commands_to_disable:
            cmd = self.bot.get_command(cmd_name)

            if not cmd:
                print(f"⚠️  Command '{cmd_name}' not found")
                continue

            if cmd.cog_name != "Core":
                print(f"⚠️  Command '{cmd_name}' belongs to {cmd.cog_name}, not Core")
                continue

            # Store original state
            original_state = cmd.enabled

            # Disable command
            cmd.enabled = False
            self._disabled_core_commands.append(cmd_name)

            print(f"✅ Disabled '{cmd_name}' (was: {original_state}, now: {cmd.enabled})")

        return True

    def test_enable_commands(self):
        """Test re-enabling core commands."""
        print("\n🔧 Testing command re-enable mechanism...")

        for cmd_name in self._disabled_core_commands:
            cmd = self.bot.get_command(cmd_name)

            if not cmd:
                print(f"⚠️  Command '{cmd_name}' not found")
                continue

            # Store original state
            original_state = cmd.enabled

            # Re-enable command
            cmd.enabled = True

            print(f"✅ Re-enabled '{cmd_name}' (was: {original_state}, now: {cmd.enabled})")

        self._disabled_core_commands.clear()
        return True

    def verify_override(self):
        """Verify that override worked."""
        print("\n🔍 Verifying override state...")

        contact_cmd = self.bot.get_command("contact")
        dm_cmd = self.bot.get_command("dm")

        results = {
            "contact": {
                "exists": contact_cmd is not None,
                "enabled": contact_cmd.enabled if contact_cmd else None,
                "cog": contact_cmd.cog_name if contact_cmd else None
            },
            "dm": {
                "exists": dm_cmd is not None,
                "enabled": dm_cmd.enabled if dm_cmd else None,
                "cog": dm_cmd.cog_name if dm_cmd else None
            }
        }

        print(f"📋 Contact command: {results['contact']}")
        print(f"📋 DM command: {results['dm']}")

        return results


# Example usage documentation
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║              SUPPORT COG - COMMAND OVERRIDE TEST                     ║
╚══════════════════════════════════════════════════════════════════════╝

This script demonstrates the command override mechanism used by the
Support cog to replace Red's built-in 'contact' and 'dm' commands.

WHAT HAPPENS WHEN THE COG LOADS:
─────────────────────────────────────
1. Support cog loads
2. cog_load() is called automatically
3. _disable_core_commands() runs:
   - Finds Core cog
   - Gets 'contact' command
   - Sets contact.enabled = False
   - Gets 'dm' command
   - Sets dm.enabled = False
   - Tracks disabled commands
4. Support's own commands are now available
5. Users see the enhanced versions

WHAT HAPPENS WHEN THE COG UNLOADS:
───────────────────────────────────
1. Support cog unloads
2. cog_unload() is called automatically
3. _enable_core_commands() runs:
   - Gets 'contact' command
   - Sets contact.enabled = True
   - Gets 'dm' command
   - Sets dm.enabled = True
   - Clears tracking list
4. Core commands are restored
5. Users see the original versions

WHY THIS APPROACH:
──────────────────
✅ Clean - No monkey-patching or hacks
✅ Safe - Automatically restores on unload
✅ Compatible - Works with Red's permission system
✅ Familiar - Users keep using same command names
✅ Reversible - Easy to unload without breaking things

TESTING IN RED:
───────────────
1. Before loading:
   [p]help contact  # Shows core version
   [p]help dm       # Shows core version

2. Load Support cog:
   [p]load support
   [p]help contact  # Shows Support version
   [p]help dm       # Shows Support version

3. Unload Support cog:
   [p]unload support
   [p]help contact  # Back to core version
   [p]help dm       # Back to core version

VERIFICATION:
─────────────
Run these in your Red instance:

# Check which cog owns a command:
[p]eval await ctx.bot.get_command('contact').cog_name

# Check if command is enabled:
[p]eval await ctx.bot.get_command('contact').enabled

# List all commands from Support cog:
[p]help Support
""")
