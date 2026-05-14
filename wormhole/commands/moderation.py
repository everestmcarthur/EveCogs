"""Moderation commands — ban, unban, mute, unmute, purge, mod edit/delete, warnings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from redbot.core import commands

from ..models.permissions import Role, has_role, requires_role, role_name, get_role
from ..utils import ok_embed, err_embed, info_embed, warn_embed, truncate, COLOUR_INFO


class ModerationCommands:
    """Mixin — moderation tools (per-network, role-gated)."""

    @commands.group(name="wh-mod", aliases=["whmod"], invoke_without_command=True)
    async def wh_mod(self, ctx: commands.Context) -> None:
        """Network moderation tools."""
        await ctx.send_help(ctx.command)

    # ── User bans ──────────────────────────────────────────────────────────

    @wh_mod.command(name="ban")
    @requires_role(Role.MODERATOR)
    async def wh_mod_ban(self, ctx: commands.Context, name: str, user: discord.User, *, reason: str = "No reason") -> None:
        """Ban a user from the network."""
        nd = await self._net(name)
        if user.id == nd["owner_id"]:
            return await ctx.send(embed=err_embed("You can't ban the network owner."))
        target_role = get_role(nd, user.id)
        actor_role = get_role(nd, ctx.author.id)
        if target_role >= actor_role and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed(f"You can't ban a {role_name(target_role)} — your role: {role_name(actor_role)}"))
        async with self.config.networks() as ns:
            bans = ns[name].setdefault("banned_users", [])
            if user.id not in bans:
                bans.append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} banned from `{name}`.\nReason: {reason}"))
        await self._audit(name, "ban", str(ctx.author), str(user), reason)
        await self._log(nd, warn_embed(f"🔨 **{user}** banned by {ctx.author}\nReason: {reason}"))

    @wh_mod.command(name="unban")
    @requires_role(Role.MODERATOR)
    async def wh_mod_unban(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Unban a user from the network."""
        async with self.config.networks() as ns:
            bans = ns[name].get("banned_users", [])
            if user.id in bans:
                bans.remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} unbanned from `{name}`."))
        await self._audit(name, "unban", str(ctx.author), str(user))

    # ── User mutes ─────────────────────────────────────────────────────────

    @wh_mod.command(name="mute")
    @requires_role(Role.MODERATOR)
    async def wh_mod_mute(self, ctx: commands.Context, name: str, user: discord.User, *, reason: str = "No reason") -> None:
        """Mute a user in the network (messages won't relay)."""
        nd = await self._net(name)
        target_role = get_role(nd, user.id)
        actor_role = get_role(nd, ctx.author.id)
        if target_role >= actor_role and not await self.bot.is_owner(ctx.author):
            return await ctx.send(embed=err_embed(f"You can't mute a {role_name(target_role)}."))
        async with self.config.networks() as ns:
            mutes = ns[name].setdefault("muted_users", [])
            if user.id not in mutes:
                mutes.append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} muted in `{name}`.\nReason: {reason}"))
        await self._audit(name, "mute", str(ctx.author), str(user), reason)
        await self._log(nd, warn_embed(f"🔇 **{user}** muted by {ctx.author}\nReason: {reason}"))

    @wh_mod.command(name="unmute")
    @requires_role(Role.MODERATOR)
    async def wh_mod_unmute(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Unmute a user in the network."""
        async with self.config.networks() as ns:
            mutes = ns[name].get("muted_users", [])
            if user.id in mutes:
                mutes.remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} unmuted in `{name}`."))
        await self._audit(name, "unmute", str(ctx.author), str(user))

    # ── Server bans/mutes ──────────────────────────────────────────────────

    @wh_mod.command(name="banserver")
    @requires_role(Role.ADMIN)
    async def wh_mod_banserver(self, ctx: commands.Context, name: str, guild_id: int) -> None:
        """Ban a server from the network."""
        async with self.config.networks() as ns:
            bans = ns[name].setdefault("banned_servers", [])
            if guild_id not in bans:
                bans.append(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` banned from `{name}`."))
        await self._audit(name, "banserver", str(ctx.author), str(guild_id))

    @wh_mod.command(name="unbanserver")
    @requires_role(Role.ADMIN)
    async def wh_mod_unbanserver(self, ctx: commands.Context, name: str, guild_id: int) -> None:
        """Unban a server from the network."""
        async with self.config.networks() as ns:
            bans = ns[name].get("banned_servers", [])
            if guild_id in bans:
                bans.remove(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` unbanned from `{name}`."))
        await self._audit(name, "unbanserver", str(ctx.author), str(guild_id))

    @wh_mod.command(name="muteserver")
    @requires_role(Role.ADMIN)
    async def wh_mod_muteserver(self, ctx: commands.Context, name: str, guild_id: int) -> None:
        """Mute a server in the network."""
        async with self.config.networks() as ns:
            mutes = ns[name].setdefault("muted_servers", [])
            if guild_id not in mutes:
                mutes.append(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` muted in `{name}`."))
        await self._audit(name, "muteserver", str(ctx.author), str(guild_id))

    @wh_mod.command(name="unmuteserver")
    @requires_role(Role.ADMIN)
    async def wh_mod_unmuteserver(self, ctx: commands.Context, name: str, guild_id: int) -> None:
        """Unmute a server in the network."""
        async with self.config.networks() as ns:
            mutes = ns[name].get("muted_servers", [])
            if guild_id in mutes:
                mutes.remove(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` unmuted in `{name}`."))
        await self._audit(name, "unmuteserver", str(ctx.author), str(guild_id))

    # ── Allowlist ──────────────────────────────────────────────────────────

    @wh_mod.command(name="allowserver")
    @requires_role(Role.ADMIN)
    async def wh_mod_allowserver(self, ctx: commands.Context, name: str, guild_id: int) -> None:
        """Add a server to the allowlist."""
        async with self.config.networks() as ns:
            allow = ns[name].setdefault("allowlist_servers", [])
            if guild_id not in allow:
                allow.append(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` added to allowlist for `{name}`."))

    @wh_mod.command(name="removeallow")
    @requires_role(Role.ADMIN)
    async def wh_mod_removeallow(self, ctx: commands.Context, name: str, guild_id: int) -> None:
        """Remove a server from the allowlist."""
        async with self.config.networks() as ns:
            allow = ns[name].get("allowlist_servers", [])
            if guild_id in allow:
                allow.remove(guild_id)
        await ctx.send(embed=ok_embed(f"Server `{guild_id}` removed from allowlist for `{name}`."))

    # ── Purge ──────────────────────────────────────────────────────────────

    @wh_mod.command(name="purge")
    @requires_role(Role.MODERATOR)
    async def wh_mod_purge(self, ctx: commands.Context, name: str, count: int = 10) -> None:
        """Purge recent relayed messages across all channels (max 50)."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        count = min(count, 50)
        deleted = 0
        for ch_id in nd.get("channels", []):
            ch = self.bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                async for msg in ch.history(limit=count):
                    if msg.author.id == self.bot.user.id or (msg.webhook_id is not None):
                        try:
                            await msg.delete()
                            deleted += 1
                        except Exception:
                            pass
            except Exception:
                pass
        await ctx.send(embed=ok_embed(f"Purged {deleted} relayed messages across `{name}`."))
        await self._audit(name, "purge", str(ctx.author), details=f"count={count}")

    # ── Cross-network mod edit/delete ──────────────────────────────────────

    @wh_mod.command(name="edit")
    @requires_role(Role.MODERATOR)
    async def wh_mod_edit(self, ctx: commands.Context, name: str, message_id: int, *, new_content: str) -> None:
        """Edit a relayed message across all channels."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        orig_id = self.msg_map.get_original(name, message_id) or message_id
        relayed = self.msg_map.get_relayed(name, orig_id)
        edited = 0
        for ch_id, msg_id in relayed.items():
            ch = self.bot.get_channel(ch_id)
            if not ch:
                continue
            try:
                wh = await self._wh(ch)
                await wh.edit_message(msg_id, content=new_content)
                edited += 1
            except Exception:
                try:
                    msg = await ch.fetch_message(msg_id)
                    if msg.author.id == self.bot.user.id:
                        await msg.edit(content=new_content)
                        edited += 1
                except Exception:
                    pass
        await ctx.send(embed=ok_embed(f"Edited {edited} relayed copies."))
        await self._audit(name, "mod_edit", str(ctx.author), str(orig_id), truncate(new_content, 100))

    @wh_mod.command(name="nuke")
    @requires_role(Role.MODERATOR)
    async def wh_mod_nuke(self, ctx: commands.Context, name: str, message_id: int) -> None:
        """Delete a message and all its relayed copies across the network."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        orig_id = self.msg_map.get_original(name, message_id) or message_id
        relayed = self.msg_map.get_relayed(name, orig_id)
        deleted = 0
        for ch_id, msg_id in relayed.items():
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(msg_id)
                    await msg.delete()
                    deleted += 1
                except Exception:
                    pass
        # Also try to delete in source channels
        for ch_id in nd.get("channels", []):
            ch = self.bot.get_channel(ch_id)
            if ch:
                try:
                    msg = await ch.fetch_message(orig_id)
                    await msg.delete()
                    deleted += 1
                except Exception:
                    pass
        await ctx.send(embed=ok_embed(f"Nuked {deleted} message(s) across `{name}`."))
        await self._audit(name, "nuke", str(ctx.author), str(orig_id))

    # ── Audit log ──────────────────────────────────────────────────────────

    @wh_mod.command(name="audit")
    @requires_role(Role.HELPER)
    async def wh_mod_audit(self, ctx: commands.Context, name: str, count: int = 20) -> None:
        """View the network audit log."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        entries = nd.get("audit_log", [])[-count:]
        if not entries:
            return await ctx.send(embed=info_embed("Audit log is empty."))
        lines = []
        for e in reversed(entries):
            ts = e.get("timestamp", "?")[:16]
            act = e.get("action", "?")
            usr = e.get("user", "?")
            tgt = e.get("target", "")
            det = e.get("details", "")
            line = f"`{ts}` **{act}** by {usr}"
            if tgt:
                line += f" → {tgt}"
            if det:
                line += f" ({det})"
            lines.append(line)
        em = discord.Embed(
            title=f"📋 Audit Log — {name}",
            description="\n".join(lines),
            colour=COLOUR_INFO,
        )
        await ctx.send(embed=em)

    # ── Ban/mute lists ─────────────────────────────────────────────────────

    @wh_mod.command(name="bans")
    @requires_role(Role.HELPER)
    async def wh_mod_bans(self, ctx: commands.Context, name: str) -> None:
        """List banned users."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        bans = nd.get("banned_users", [])
        if not bans:
            return await ctx.send(embed=info_embed(f"No banned users in `{name}`."))
        lines = []
        for uid in bans:
            user = self.bot.get_user(uid)
            lines.append(f"• {user or uid}")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"🔨 Banned Users — {name}"))

    @wh_mod.command(name="mutes")
    @requires_role(Role.HELPER)
    async def wh_mod_mutes(self, ctx: commands.Context, name: str) -> None:
        """List muted users."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        mutes = nd.get("muted_users", [])
        if not mutes:
            return await ctx.send(embed=info_embed(f"No muted users in `{name}`."))
        lines = []
        for uid in mutes:
            user = self.bot.get_user(uid)
            lines.append(f"• {user or uid}")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"🔇 Muted Users — {name}"))
