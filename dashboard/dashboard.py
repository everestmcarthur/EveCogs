"""
EveDash — A modern, self-contained web dashboard for Red-DiscordBot.

Inspired by AAA3A's Dashboard, rebuilt from the ground up with:
  • Embedded aiohttp server (no external packages needed)
  • Modern SPA frontend with Discord-inspired dark theme
  • Real-time WebSocket updates
  • Third-party cog integration SDK
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import typing

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

from .sdk import ThirdPartyManager
from .server import DashboardServer

log = logging.getLogger("red.evecogs.dashboard")


class EveDash(commands.Cog):
    """🖥️ A modern web dashboard for Red-DiscordBot.

    Manage your bot from a beautiful web interface — configure guilds,
    manage cogs, toggle commands, and more. Third-party cogs can register
    their own settings pages using the EveDash SDK.

    **Quick Setup:**
    1. `[p]evedash setup` — guided setup wizard
    2. Open the dashboard URL in your browser
    3. Log in with Discord

    **For cog developers:** See `dashboard/sdk.py` for the integration guide.
    """

    __author__ = "EveCogs"
    __version__ = "1.0.0"

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=784917823648172,
            force_registration=True,
        )
        self.config.register_global(
            # Localhost-only by default — loading this cog with zero config
            # shouldn't immediately expose an unauthenticated-until-login web
            # server on every network interface. Owners who want it reachable
            # externally (e.g. no reverse proxy) can opt in with
            # `[p]evedash host 0.0.0.0`.
            host="127.0.0.1",
            port=42356,
            client_id=None,
            client_secret=None,
            redirect_uri=None,
            secret_key=None,
            blacklist=[],
            support_url=None,
            meta_title=None,
            meta_description=None,
        )

        self.server: DashboardServer = DashboardServer(self)
        self.third_parties: ThirdPartyManager = ThirdPartyManager(bot)
        self._ready = asyncio.Event()

    async def cog_load(self) -> None:
        # Generate secret key if not set
        if not await self.config.secret_key():
            await self.config.secret_key.set(secrets.token_urlsafe(64))

        asyncio.create_task(self._start_server())

    async def _start_server(self) -> None:
        await self.bot.wait_until_red_ready()

        host = await self.config.host()
        port = await self.config.port()

        try:
            await self.server.start(host, port)
            self._ready.set()
            self.bot.dispatch("dashboard_cog_add", self)
            log.info(f"EveDash v{self.__version__} ready on http://{host}:{port}")
        except Exception as e:
            log.error(f"Failed to start EveDash server: {e}")

    async def cog_unload(self) -> None:
        self.bot.dispatch("dashboard_cog_remove", self)
        await self.server.stop()

    # ── Listeners ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_cog_add(self, cog: commands.Cog) -> None:
        """Notify newly-loaded cogs that the dashboard is available."""
        if not self._ready.is_set():
            return
        ev = "on_dashboard_cog_add"
        for listener_name, listener_func in cog.get_listeners():
            if listener_name == ev:
                try:
                    self.bot._schedule_event(listener_func, ev, self)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_cog_remove(self, cog: commands.Cog) -> None:
        """Clean up when a third-party cog is unloaded."""
        self.third_parties.remove_third_party(cog)

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        self.server._command_count += 1

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.author.bot:
            self.server._message_count += 1

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self.server.ws_manager.broadcast("member_join", {
            "guild_id": str(member.guild.id),
            "user": str(member),
        })

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.server.ws_manager.broadcast("member_remove", {
            "guild_id": str(member.guild.id),
            "user": str(member),
        })

    # ── Commands ─────────────────────────────────────────────────────────

    @commands.group(name="evedash", aliases=["dashboard", "dash"])
    async def evedash(self, ctx: commands.Context) -> None:
        """🖥️ EveDash — Web Dashboard for Red-DiscordBot."""
        if ctx.invoked_subcommand is None:
            port = await self.config.port()
            redirect_uri = await self.config.redirect_uri()
            if redirect_uri:
                base_url = redirect_uri.rsplit("/api/", 1)[0]
                embed = discord.Embed(
                    title="🖥️ EveDash",
                    description=f"Your bot's web dashboard is live!\n\n**[Open Dashboard]({base_url})**",
                    color=discord.Color.blurple(),
                )
                embed.add_field(name="Status", value="🟢 Online", inline=True)
                embed.add_field(name="Port", value=str(port), inline=True)
                embed.add_field(
                    name="Third Parties",
                    value=str(len(self.third_parties.third_parties)),
                    inline=True,
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send(
                    "⚠️ EveDash is not configured yet.\n"
                    f"Run `{ctx.prefix}evedash setup` to get started!"
                )

    @evedash.command(name="setup")
    @checks.is_owner()
    async def evedash_setup(self, ctx: commands.Context) -> None:
        """🔧 Guided setup wizard for EveDash.

        You'll need:
        1. A Discord application with OAuth2 configured
        2. Your Client ID and Client Secret
        3. A redirect URI (your domain + /api/auth/callback)
        """
        embed = discord.Embed(
            title="🔧 EveDash Setup Wizard",
            description=(
                "Let's configure your dashboard!\n\n"
                "**Step 1:** Go to the [Discord Developer Portal](https://discord.com/developers/applications)\n"
                "**Step 2:** Select your bot's application\n"
                "**Step 3:** Go to **OAuth2** and note your **Client ID** and **Client Secret**\n"
                "**Step 4:** Add a redirect URI: `http://YOUR_DOMAIN:PORT/api/auth/callback`\n\n"
                "Ready? Reply with your **Client ID** (just the number)."
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # Client ID
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=120)
            client_id = msg.content.strip()
            await self.config.client_id.set(client_id)
            await ctx.send("✅ Client ID saved! Now send your **Client Secret**:")
        except asyncio.TimeoutError:
            return await ctx.send("⏰ Setup timed out.")

        # Client Secret
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=120)
            client_secret = msg.content.strip()
            await self.config.client_secret.set(client_secret)
            try:
                await msg.delete()
            except Exception:
                pass
            await ctx.send("✅ Client Secret saved (message deleted for safety)! Now send your **Redirect URI**:\n"
                           f"Example: `http://yourdomain.com:{await self.config.port()}/api/auth/callback`")
        except asyncio.TimeoutError:
            return await ctx.send("⏰ Setup timed out.")

        # Redirect URI
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=120)
            redirect_uri = msg.content.strip()
            await self.config.redirect_uri.set(redirect_uri)
        except asyncio.TimeoutError:
            return await ctx.send("⏰ Setup timed out.")

        base_url = redirect_uri.rsplit("/api/", 1)[0]
        embed = discord.Embed(
            title="🎉 EveDash Setup Complete!",
            description=(
                f"Your dashboard is ready!\n\n"
                f"**🌐 URL:** {base_url}\n"
                f"**🔌 Port:** {await self.config.port()}\n\n"
                f"Open the link above and log in with Discord.\n"
                f"Only bot owners and server admins/managers can access it."
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="Tip: Use [p]evedash port <number> to change the port")
        await ctx.send(embed=embed)

    @evedash.command(name="port")
    @checks.is_owner()
    async def evedash_port(self, ctx: commands.Context, port: int) -> None:
        """Change the dashboard port. Requires a cog reload."""
        if not 1024 <= port <= 65535:
            return await ctx.send("❌ Port must be between 1024 and 65535.")
        await self.config.port.set(port)
        await ctx.send(f"✅ Port set to **{port}**. Reload the cog (`{ctx.prefix}reload dashboard`) for it to take effect.")

    @evedash.command(name="host")
    @checks.is_owner()
    async def evedash_host(self, ctx: commands.Context, host: str) -> None:
        """Change the dashboard bind address (default: 0.0.0.0)."""
        await self.config.host.set(host)
        await ctx.send(f"✅ Host set to **{host}**. Reload the cog for it to take effect.")

    @evedash.command(name="secret")
    @checks.is_owner()
    async def evedash_secret(self, ctx: commands.Context, *, secret: str) -> None:
        """Set the Discord OAuth2 client secret."""
        await self.config.client_secret.set(secret)
        try:
            await ctx.message.delete()
        except Exception:
            pass
        await ctx.send("✅ Client secret updated.")

    @evedash.command(name="clientid")
    @checks.is_owner()
    async def evedash_clientid(self, ctx: commands.Context, client_id: str) -> None:
        """Set the Discord OAuth2 client ID."""
        await self.config.client_id.set(client_id)
        await ctx.send(f"✅ Client ID set to `{client_id}`.")

    @evedash.command(name="redirect")
    @checks.is_owner()
    async def evedash_redirect(self, ctx: commands.Context, *, uri: str) -> None:
        """Set the OAuth2 redirect URI."""
        if not uri.endswith("/api/auth/callback"):
            return await ctx.send("⚠️ Redirect URI must end with `/api/auth/callback`.")
        await self.config.redirect_uri.set(uri)
        await ctx.send(f"✅ Redirect URI set to `{uri}`.")

    @evedash.command(name="blacklist")
    @checks.is_owner()
    async def evedash_blacklist(self, ctx: commands.Context, user: discord.User) -> None:
        """Toggle a user on the dashboard blacklist."""
        async with self.config.blacklist() as bl:
            if user.id in bl:
                bl.remove(user.id)
                await ctx.send(f"✅ **{user}** removed from dashboard blacklist.")
            else:
                bl.append(user.id)
                await ctx.send(f"✅ **{user}** added to dashboard blacklist.")

    @evedash.command(name="info")
    async def evedash_info(self, ctx: commands.Context) -> None:
        """Show dashboard status and info."""
        redirect_uri = await self.config.redirect_uri()
        port = await self.config.port()
        host = await self.config.host()
        tp_count = len(self.third_parties.third_parties)

        embed = discord.Embed(
            title="🖥️ EveDash Info",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Status",
            value="🟢 Online" if self._ready.is_set() else "🔴 Offline",
            inline=True,
        )
        embed.add_field(name="Host", value=f"`{host}:{port}`", inline=True)
        embed.add_field(name="Third Parties", value=str(tp_count), inline=True)
        embed.add_field(name="Version", value=f"v{self.__version__}", inline=True)
        embed.add_field(
            name="Messages Tracked",
            value=f"{self.server._message_count:,}",
            inline=True,
        )
        embed.add_field(
            name="Commands Tracked",
            value=f"{self.server._command_count:,}",
            inline=True,
        )

        if redirect_uri:
            base_url = redirect_uri.rsplit("/api/", 1)[0]
            embed.add_field(name="URL", value=base_url, inline=False)

        if tp_count:
            tp_names = ", ".join(self.third_parties.third_parties.keys())
            embed.add_field(name="Registered Cogs", value=tp_names, inline=False)

        embed.set_footer(text="EveDash — Web Dashboard for Red-DiscordBot")
        await ctx.send(embed=embed)
