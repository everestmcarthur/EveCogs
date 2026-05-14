"""
In-memory bidirectional message map for tracking relayed messages.

Maps original message IDs ↔ relayed copies across channels within a network.
Capped at MAP_LIMIT entries per direction to bound memory usage.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Optional

from .config import MAP_LIMIT


class MessageMap:
    """Bidirectional map: original_id ↔ {channel_id: relayed_msg_id}.

    ``forward[net][original_id] = {ch_id: relayed_id, ...}``
    ``reverse[net][relayed_id]  = original_id``
    """

    def __init__(self) -> None:
        self.forward: Dict[str, OrderedDict[int, Dict[int, int]]] = {}
        self.reverse: Dict[str, OrderedDict[int, int]] = {}

    def add(self, network: str, original_id: int, mapping: Dict[int, int]) -> None:
        """Record that *original_id* was relayed to *mapping* channels."""
        fwd = self.forward.setdefault(network, OrderedDict())
        rev = self.reverse.setdefault(network, OrderedDict())

        fwd[original_id] = mapping
        for relayed_id in mapping.values():
            rev[relayed_id] = original_id

        # Prune oldest entries
        while len(fwd) > MAP_LIMIT:
            _old_orig, old_map = fwd.popitem(last=False)
            for rid in old_map.values():
                rev.pop(rid, None)
        while len(rev) > MAP_LIMIT * 2:
            rev.popitem(last=False)

    def get_relayed(self, network: str, original_id: int) -> Dict[int, int]:
        """Get ``{ch_id: relayed_id}`` for an original message."""
        return self.forward.get(network, {}).get(original_id, {})

    def get_original(self, network: str, relayed_id: int) -> Optional[int]:
        """Get the original message ID from a relayed copy ID."""
        return self.reverse.get(network, {}).get(relayed_id)

    def get_all_relayed_ids(self, network: str, original_id: int) -> List[int]:
        """Get all relayed message IDs for an original."""
        return list(self.get_relayed(network, original_id).values())
