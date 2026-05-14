"""Data models for Wormhole — config defaults, permissions, message mapping."""

from .config import DEFAULT_NETWORK, DEFAULT_GLOBAL, MAP_LIMIT
from .message_map import MessageMap
from .permissions import Role, has_role, requires_role, role_name

__all__ = [
    "DEFAULT_NETWORK",
    "DEFAULT_GLOBAL",
    "MAP_LIMIT",
    "MessageMap",
    "Role",
    "has_role",
    "requires_role",
    "role_name",
]
