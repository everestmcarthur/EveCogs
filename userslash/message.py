"""
InterMessage — lightweight ``discord.Message`` stand-in built from
a slash-command ``Interaction`` so Red's text-command pipeline can process it.

Enhanced from OneTrueSlash to handle user-install contexts (DMs, group DMs,
and guilds where the bot is not a member).
"""

import asyncio
from copy import copy
from typing import TypeVar

import discord

from .channel import InterChannel

_TT = TypeVar("_TT", bound=type)


def _noop_step(*_args, **_kwargs):
    """Coroutine that just yields to the event loop once."""
    return asyncio.sleep(0)


def neuter_coros(cls: _TT) -> _TT:
    """Replace every inherited coroutine with a harmless no-op."""
    for name in dir(cls):
        if name in cls.__dict__:
            continue
        if (attr := getattr(cls, name, None)) is None:
            continue
        if asyncio.iscoroutinefunction(attr):
            setattr(cls, name, property(lambda self: _noop_step))
    return cls


@neuter_coros
class InterMessage(discord.Message):
    __slots__ = ()

    def __init__(self, **kwargs) -> None:
        raise RuntimeError("InterMessage must be created via _from_interaction")

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def _from_interaction(
        cls, interaction: discord.Interaction, prefix: str
    ) -> "InterMessage":
        assert interaction.data
        assert interaction.client.user

        self = cls.__new__(cls)
        self._state = interaction._state
        self._edited_timestamp = None

        # Constant / default fields
        self.tts = False
        self.webhook_id = None
        self.mention_everyone = False
        self.embeds = []
        self.role_mentions = []
        self.id = interaction.id
        self.nonce = None
        self.pinned = False
        self.type = discord.MessageType.default
        self.flags = discord.MessageFlags()
        self.reactions = []
        self.reference = None
        self.application = None
        self.activity = None
        self.stickers = []
        self.components = []
        self.role_subscription = None
        self.application_id = None
        self.position = None

        channel = interaction.channel
        self.guild = interaction.guild

        # --- Determine author & channel based on context ---

        if interaction.guild_id and not interaction.guild:
            # Guild ID present but guild not in cache (e.g. user-install in a
            # server the bot hasn't joined).  Treat as DM so Red doesn't crash.
            if isinstance(interaction.user, discord.Member):
                self.author = interaction.user._user
            else:
                self.author = interaction.user
            channel = cls._make_dm_channel(interaction)

        elif not interaction.guild:
            # True DM or group DM from a user-install context.
            self.author = interaction.user
            if channel is None:
                channel = cls._make_dm_channel(interaction)
            else:
                channel = copy(channel)

        else:
            # Normal guild context — bot is a member.
            self.author = interaction.user
            if channel is not None:
                channel = copy(channel)
            else:
                channel = cls._make_dm_channel(interaction)

        # Mix InterChannel into the channel so send/typing route correctly
        if channel is not None:
            channel.__class__ = type(
                InterChannel.__name__,
                (InterChannel, channel.__class__),
                {"__slots__": ()},
            )
        self.channel = channel  # type: ignore

        self._recreate_from_interaction(interaction, prefix)
        return self

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_dm_channel(interaction: discord.Interaction) -> discord.DMChannel:
        """Fabricate a minimal DMChannel when the real one is unavailable."""
        assert interaction.client.user
        user = interaction.user
        user_json = (
            user._to_minimal_user_json()
            if hasattr(user, "_to_minimal_user_json")
            else {
                "id": str(user.id),
                "username": str(user),
                "discriminator": "0",
                "avatar": None,
            }
        )
        return discord.DMChannel(
            me=interaction.client.user,
            state=interaction._state,
            data={
                "id": interaction.channel_id or interaction.id,
                "name": f"DM with {user}",
                "type": 1,
                "last_message_id": None,
                "recipients": [
                    user_json,
                    interaction.client.user._to_minimal_user_json(),
                ],
            },
        )

    def _recreate_from_interaction(
        self, interaction: discord.Interaction, prefix: str
    ) -> None:
        assert interaction.data and interaction.client.user

        self.content = f"{prefix}{interaction.namespace.command}"
        if interaction.namespace.arguments:
            self.content = f"{self.content} {interaction.namespace.arguments}"
        if interaction.namespace.attachment:
            self.attachments = [interaction.namespace.attachment]
        else:
            self.attachments = []

        resolved = interaction.data.get("resolved", {})
        if self.guild:
            self.mentions = [
                discord.Member(data=d, guild=self.guild, state=self._state)
                for d in resolved.get("members", {}).values()
            ]
        else:
            self.mentions = [
                discord.User(data=d, state=self._state)
                for d in resolved.get("users", {}).values()
            ]

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def to_reference(self, *, fail_if_not_exists: bool = True):
        return None

    def to_message_reference_dict(self):
        return discord.utils.MISSING

    async def reply(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)

    def edit(self, *args, **kwargs):
        return asyncio.sleep(0, self)
