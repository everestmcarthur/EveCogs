"""Mention policy commands — granular per-network, per-server, per-user controls."""

from __future__ import annotations

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role
from ..utils import ok_embed, err_embed, info_embed, COLOUR_INFO


class MentionCommands:
    """Mixin — mention policy management."""

    @commands.group(name="wh-mention", aliases=["whmention"], invoke_without_command=True)
    async def wh_mention(self, ctx: commands.Context) -> None:
        """Configure mention behaviour."""
        await ctx.send_help(ctx.command)

    @wh_mention.command(name="set")
    @requires_role(Role.ADMIN)
    async def wh_mention_set(self, ctx: commands.Context, name: str, kind: str, allowed: bool) -> None:
        """Set a mention policy.

        Kinds: ``user``, ``role``, ``everyone``, ``here``
        """
        key_map = {
            "user": "allow_user_mentions",
            "role": "allow_role_mentions",
            "everyone": "allow_everyone",
            "here": "allow_here",
        }
        if kind not in key_map:
            return await ctx.send(embed=err_embed(f"Unknown kind. Options: {', '.join(key_map)}"))
        async with self.config.networks() as ns:
            policy = ns[name].setdefault("mention_policy", {})
            policy[key_map[kind]] = allowed
        await ctx.send(embed=ok_embed(f"`{kind}` mentions {'allowed' if allowed else 'blocked'} in `{name}`."))
        await self._audit(name, f"mention_{kind}", str(ctx.author), details=str(allowed))

    @wh_mention.command(name="exempt")
    @requires_role(Role.ADMIN)
    async def wh_mention_exempt(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Exempt a user from mention restrictions."""
        async with self.config.networks() as ns:
            exempt = ns[name].setdefault("mention_exempt_users", [])
            if user.id not in exempt:
                exempt.append(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} exempted from mention restrictions in `{name}`."))

    @wh_mention.command(name="unexempt")
    @requires_role(Role.ADMIN)
    async def wh_mention_unexempt(self, ctx: commands.Context, name: str, user: discord.User) -> None:
        """Remove a user's mention exemption."""
        async with self.config.networks() as ns:
            exempt = ns[name].get("mention_exempt_users", [])
            if user.id in exempt:
                exempt.remove(user.id)
        await ctx.send(embed=ok_embed(f"{user.mention} exemption removed in `{name}`."))

    @wh_mention.command(name="optout")
    async def wh_mention_optout(self, ctx: commands.Context, name: str) -> None:
        """Opt out of being pinged via relay."""
        async with self.config.networks() as ns:
            optout = ns[name].setdefault("mention_optout_users", [])
            if ctx.author.id not in optout:
                optout.append(ctx.author.id)
        await ctx.send(embed=ok_embed("You've opted out of relay pings."))

    @wh_mention.command(name="optin")
    async def wh_mention_optin(self, ctx: commands.Context, name: str) -> None:
        """Opt back in to relay pings."""
        async with self.config.networks() as ns:
            optout = ns[name].get("mention_optout_users", [])
            if ctx.author.id in optout:
                optout.remove(ctx.author.id)
        await ctx.send(embed=ok_embed("You've opted back in to relay pings."))

    @wh_mention.command(name="serveroverride")
    @requires_role(Role.ADMIN)
    async def wh_mention_serveroverride(self, ctx: commands.Context, name: str, guild_id: int, kind: str, allowed: bool) -> None:
        """Set per-server mention override."""
        key_map = {
            "user": "allow_user_mentions",
            "role": "allow_role_mentions",
            "everyone": "allow_everyone",
            "here": "allow_here",
        }
        if kind not in key_map:
            return await ctx.send(embed=err_embed(f"Unknown kind. Options: {', '.join(key_map)}"))
        async with self.config.networks() as ns:
            so = ns[name].setdefault("server_mention_overrides", {})
            gid_str = str(guild_id)
            so.setdefault(gid_str, {})[key_map[kind]] = allowed
        await ctx.send(embed=ok_embed(f"Server override set for `{guild_id}` in `{name}`."))

    @wh_mention.command(name="show")
    @requires_role(Role.HELPER)
    async def wh_mention_show(self, ctx: commands.Context, name: str) -> None:
        """Show current mention policy."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        policy = nd.get("mention_policy", {})
        em = discord.Embed(title=f"📢 Mention Policy — {name}", colour=COLOUR_INFO)
        em.add_field(name="User mentions", value="✅" if policy.get("allow_user_mentions") else "❌", inline=True)
        em.add_field(name="Role mentions", value="✅" if policy.get("allow_role_mentions") else "❌", inline=True)
        em.add_field(name="@everyone", value="✅" if policy.get("allow_everyone") else "❌", inline=True)
        em.add_field(name="@here", value="✅" if policy.get("allow_here") else "❌", inline=True)
        em.add_field(name="Exempt users", value=str(len(nd.get("mention_exempt_users", []))), inline=True)
        em.add_field(name="Opted out", value=str(len(nd.get("mention_optout_users", []))), inline=True)
        await ctx.send(embed=em)
