"""Discord UI modals for Wormhole (e.g. report form)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

from ..utils import ok_embed, truncate, warn_embed

if TYPE_CHECKING:
    from ..core import Wormhole


class ReportModal(discord.ui.Modal, title="Report Message"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Describe why you're reporting this message...",
        required=True,
        max_length=1000,
    )

    def __init__(self, cog: Wormhole, net_name: str, message: discord.Message) -> None:
        super().__init__()
        self.cog = cog
        self.net_name = net_name
        self.message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        # report_id must be computed and written inside the same locked
        # section — reading report_counter beforehand let two concurrent
        # reports land on the same id and left the counter not advanced.
        async with self.cog.config.networks() as ns:
            nd = ns.get(self.net_name)
            if not nd:
                await interaction.response.send_message("Network not found.", ephemeral=True)
                return

            report_id = nd.get("report_counter", 0) + 1
            report = {
                "id": report_id,
                "reporter_id": interaction.user.id,
                "author_id": self.message.author.id,
                "message_id": self.message.id,
                "channel_id": self.message.channel.id,
                "guild_id": self.message.guild.id if self.message.guild else None,
                "content_preview": truncate(self.message.content or "*[no text]*", 300),
                "jump_url": self.message.jump_url,
                "reason": self.reason.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "resolved": False,
                "resolved_by": None,
                "resolution": None,
            }
            nd.setdefault("reports", []).append(report)
            nd["report_counter"] = report_id

        owner = self.cog.bot.get_user(nd.get("owner_id"))
        if owner:
            try:
                await owner.send(
                    embed=warn_embed(
                        f"**Report #{report_id}** in `{self.net_name}`\n"
                        f"Reporter: {interaction.user} (`{interaction.user.id}`)\n"
                        f"Author: {self.message.author} (`{self.message.author.id}`)\n"
                        f"Reason: {self.reason.value}",
                        title="🚩 New Report",
                    )
                )
            except discord.Forbidden:
                pass

        await interaction.response.send_message(
            embed=ok_embed(f"Report #{report_id} submitted. Staff will review it."),
            ephemeral=True,
        )
