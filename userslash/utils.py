"""
Shared utilities for UserSlash.
"""

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Generator, Optional

from discord.ext.commands import GroupMixin
from redbot.core import commands

if TYPE_CHECKING:
    from .context import InterContext

try:
    import regex as re
except ImportError:
    import re


# ContextVar holding the current InterContext for the active interaction
contexts: ContextVar["InterContext"] = ContextVar("userslash_contexts")


def valid_app_name(name: str) -> str:
    """Convert a display name into a valid slash-command name (lowercase, underscores, ≤32 chars)."""
    from discord.app_commands.commands import VALID_SLASH_COMMAND_NAME, validate_name

    name = "_".join(
        re.findall(VALID_SLASH_COMMAND_NAME.pattern.strip("^$"), name.lower())
    )
    return validate_name(name[:32])


class Thinking:
    """Async context-manager / awaitable that defers the interaction response once."""

    def __init__(self, ctx: "InterContext", *, ephemeral: bool = False):
        self.ctx = ctx
        self.ephemeral = ephemeral

    def __await__(self) -> Generator[Any, Any, None]:
        ctx = self.ctx
        interaction = ctx._interaction
        if not ctx._deferring and not interaction.response.is_done():
            ctx._deferring = True
            return (
                yield from interaction.response.defer(
                    ephemeral=self.ephemeral
                ).__await__()
            )

    async def __aenter__(self):
        await self

    async def __aexit__(self, *args):
        pass


def walk_aliases(
    group: GroupMixin[Any],
    /,
    *,
    parent: Optional[str] = "",
    show_hidden: bool = False,
) -> Generator[str, None, None]:
    """Yield every reachable command name (including aliases) in *group*."""
    for name, command in group.all_commands.items():
        if command.qualified_name == "help":
            continue
        if not command.enabled or (not show_hidden and command.hidden):
            continue
        yield f"{parent}{name}"
        if isinstance(command, commands.GroupMixin):
            yield from walk_aliases(
                command, parent=f"{parent}{name} ", show_hidden=show_hidden
            )
