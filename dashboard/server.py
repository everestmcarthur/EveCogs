"""
EveDash — aiohttp web server with REST API, WebSocket, and static file serving.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import json
import logging
import os
import pathlib
import secrets
import time
import typing

import aiohttp
import discord
from aiohttp import web

if typing.TYPE_CHECKING:
    from .dashboard import EveDash

log = logging.getLogger("red.evecogs.dashboard.server")

WEB_DIR = pathlib.Path(__file__).parent / "web"

# ── helpers ──────────────────────────────────────────────────────────────

def _json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _err(msg: str, status: int = 400) -> web.Response:
    return _json({"error": msg}, status=status)


def _make_token(user_id: int, secret: str) -> str:
    ts = str(int(time.time()))
    payload = f"{user_id}:{ts}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_token(token: str, secret: str, max_age: int = 86400 * 7) -> int | None:
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id, ts, sig = int(parts[0]), int(parts[1]), parts[2]
        expected = hmac.new(secret.encode(), f"{user_id}:{ts}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if time.time() - ts > max_age:
            return None
        return user_id
    except Exception:
        return None


# ── middleware ────────────────────────────────────────────────────────────

def _build_auth_middleware(cog: EveDash):
    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        request["user_id"] = None
        request["is_owner"] = False

        # Skip auth for static, login, callback, and health
        path = request.path
        if (
            not path.startswith("/api/")
            and not path.startswith("/ws")
        ):
            return await handler(request)
        if path in ("/api/auth/login", "/api/auth/callback", "/api/health"):
            return await handler(request)

        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get("eve_token")

        if token:
            secret = await cog.config.secret_key()
            user_id = _verify_token(token, secret)
            if user_id:
                request["user_id"] = user_id
                request["is_owner"] = user_id in cog.bot.owner_ids

        return await handler(request)

    return auth_middleware


def _require_auth(handler):
    async def wrapper(request: web.Request):
        if request["user_id"] is None:
            return _err("Unauthorized", 401)
        return await handler(request)
    wrapper.__name__ = handler.__name__
    return wrapper


def _require_owner(handler):
    async def wrapper(request: web.Request):
        if request["user_id"] is None:
            return _err("Unauthorized", 401)
        if not request["is_owner"]:
            return _err("Forbidden — bot owner only", 403)
        return await handler(request)
    wrapper.__name__ = handler.__name__
    return wrapper


# ── WebSocket manager ────────────────────────────────────────────────────

class WebSocketManager:
    def __init__(self):
        self.connections: dict[int, list[web.WebSocketResponse]] = {}

    async def add(self, user_id: int, ws: web.WebSocketResponse):
        self.connections.setdefault(user_id, []).append(ws)

    async def remove(self, user_id: int, ws: web.WebSocketResponse):
        if user_id in self.connections:
            self.connections[user_id] = [c for c in self.connections[user_id] if c is not ws]
            if not self.connections[user_id]:
                del self.connections[user_id]

    async def broadcast(self, event: str, data: dict, owner_only: bool = False):
        msg = json.dumps({"event": event, "data": data})
        dead = []
        for uid, conns in self.connections.items():
            for ws in conns:
                try:
                    await ws.send_str(msg)
                except Exception:
                    dead.append((uid, ws))
        for uid, ws in dead:
            await self.remove(uid, ws)

    async def send_to(self, user_id: int, event: str, data: dict):
        msg = json.dumps({"event": event, "data": data})
        for ws in self.connections.get(user_id, []):
            try:
                await ws.send_str(msg)
            except Exception:
                pass


# ── Server class ─────────────────────────────────────────────────────────

class DashboardServer:
    def __init__(self, cog: EveDash):
        self.cog = cog
        self.bot = cog.bot
        self.app: web.Application | None = None
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.ws_manager = WebSocketManager()
        self._start_time = time.time()
        self._command_count = 0
        self._message_count = 0

    async def start(self, host: str, port: int):
        self.app = web.Application(middlewares=[_build_auth_middleware(self.cog)])
        self._register_routes()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()
        log.info(f"EveDash server started on http://{host}:{port}")

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            log.info("EveDash server stopped")

    def _register_routes(self):
        r = self.app.router

        # Health
        r.add_get("/api/health", self._health)

        # Auth
        r.add_get("/api/auth/login", self._auth_login)
        r.add_get("/api/auth/callback", self._auth_callback)
        r.add_get("/api/auth/me", _require_auth(self._auth_me))
        r.add_post("/api/auth/logout", self._auth_logout)

        # Bot
        r.add_get("/api/bot/info", _require_auth(self._bot_info))
        r.add_get("/api/bot/stats", _require_auth(self._bot_stats))

        # Guilds
        r.add_get("/api/guilds", _require_auth(self._guilds_list))
        r.add_get("/api/guilds/{guild_id}", _require_auth(self._guild_detail))
        r.add_get("/api/guilds/{guild_id}/channels", _require_auth(self._guild_channels))
        r.add_get("/api/guilds/{guild_id}/roles", _require_auth(self._guild_roles))

        # Guild settings
        r.add_get("/api/guilds/{guild_id}/settings", _require_auth(self._guild_settings_get))
        r.add_put("/api/guilds/{guild_id}/settings", _require_auth(self._guild_settings_update))

        # Commands
        r.add_get("/api/guilds/{guild_id}/commands", _require_auth(self._guild_commands))
        r.add_put("/api/guilds/{guild_id}/commands/{command}", _require_auth(self._guild_command_toggle))

        # Cog management (owner only)
        r.add_get("/api/cogs", _require_owner(self._cogs_list))
        r.add_post("/api/cogs/{cog_name}/load", _require_owner(self._cog_load))
        r.add_post("/api/cogs/{cog_name}/unload", _require_owner(self._cog_unload))
        r.add_post("/api/cogs/{cog_name}/reload", _require_owner(self._cog_reload))

        # Third-party
        r.add_get("/api/guilds/{guild_id}/third-parties", _require_auth(self._third_parties_list))
        r.add_get("/api/guilds/{guild_id}/third-parties/{cog_name}/{page}", _require_auth(self._third_party_page))
        r.add_post("/api/guilds/{guild_id}/third-parties/{cog_name}/{page}", _require_auth(self._third_party_page))

        # Admin
        r.add_get("/api/admin/config", _require_owner(self._admin_config))
        r.add_put("/api/admin/config", _require_owner(self._admin_config_update))
        r.add_get("/api/admin/blacklist", _require_owner(self._admin_blacklist))
        r.add_post("/api/admin/blacklist", _require_owner(self._admin_blacklist_add))
        r.add_delete("/api/admin/blacklist/{user_id}", _require_owner(self._admin_blacklist_remove))
        r.add_get("/api/admin/whitelist", _require_owner(self._admin_whitelist))

        # WebSocket
        r.add_get("/ws", self._ws_handler)

        # Static files (SPA)
        r.add_get("/", self._serve_index)
        r.add_static("/static/", path=str(WEB_DIR), name="static", show_index=False)
        # Catch-all for SPA routing
        r.add_get("/{path:.*}", self._serve_spa)

    # ── Health ───────────────────────────────────────────────────────────

    async def _health(self, request: web.Request) -> web.Response:
        return _json({"status": "ok", "uptime": int(time.time() - self._start_time)})

    # ── Auth ─────────────────────────────────────────────────────────────

    async def _auth_login(self, request: web.Request) -> web.Response:
        client_id = await self.cog.config.client_id()
        redirect_uri = await self.cog.config.redirect_uri()
        if not client_id or not redirect_uri:
            return _err("Dashboard not configured. Run [p]evedash setup", 500)
        state = secrets.token_urlsafe(32)
        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope=identify+guilds"
            f"&state={state}"
        )
        resp = _json({"url": url, "state": state})
        # Bind this state to the browser that requested it via a short-lived
        # cookie, so the callback can confirm the redirect actually belongs
        # to a login flow we started — otherwise an attacker's own
        # authorization code could be handed to a victim's browser and get
        # bound to the victim's session (login CSRF / session fixation).
        resp.set_cookie(
            "oauth_state", state,
            max_age=600,
            httponly=True,
            samesite="Lax",
        )
        return resp

    async def _auth_callback(self, request: web.Request) -> web.Response:
        code = request.query.get("code")
        if not code:
            return _err("Missing authorization code")

        state = request.query.get("state")
        expected_state = request.cookies.get("oauth_state")
        if not state or not expected_state or not hmac.compare_digest(state, expected_state):
            return _err("Invalid or missing state parameter", 400)

        client_id = await self.cog.config.client_id()
        client_secret = await self.cog.config.client_secret()
        redirect_uri = await self.cog.config.redirect_uri()

        # Exchange code for token
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status != 200:
                return _err("Failed to exchange authorization code")
            token_data = await resp.json()

            # Get user info
            resp2 = await session.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            if resp2.status != 200:
                return _err("Failed to fetch user info")
            user_data = await resp2.json()

        user_id = int(user_data["id"])

        # Check access: must be bot owner or share a guild
        is_owner = user_id in self.bot.owner_ids
        has_guild = any(g.get_member(user_id) for g in self.bot.guilds)
        if not is_owner and not has_guild:
            # Cache miss rather than genuinely no shared guilds? This only
            # runs once per login (not a hot path), so it's worth confirming
            # with a live check before denying a real user access.
            for g in self.bot.guilds:
                try:
                    if await g.fetch_member(user_id):
                        has_guild = True
                        break
                except (discord.NotFound, discord.HTTPException):
                    continue
        if not is_owner and not has_guild:
            return _err("You don't share any servers with this bot", 403)

        # Check blacklist
        blacklist = await self.cog.config.blacklist()
        if user_id in blacklist:
            return _err("You are blacklisted from the dashboard", 403)

        # Generate token
        secret = await self.cog.config.secret_key()
        token = _make_token(user_id, secret)

        # Redirect to frontend with token
        base_url = redirect_uri.rsplit("/api/", 1)[0]  # Remove /api/auth/callback
        resp = web.HTTPFound(f"{base_url}/#/callback?token={token}")
        resp.set_cookie(
            "eve_token", token,
            max_age=86400 * 7,
            httponly=True,
            samesite="Lax",
        )
        resp.del_cookie("oauth_state")
        return resp

    async def _auth_me(self, request: web.Request) -> web.Response:
        user_id = request["user_id"]
        user = self.bot.get_user(user_id)
        if not user:
            # Try to fetch
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                return _err("User not found", 404)

        return _json({
            "id": str(user.id),
            "username": user.name,
            "display_name": user.display_name,
            "avatar": str(user.display_avatar.url) if user.display_avatar else None,
            "is_owner": user.id in self.bot.owner_ids,
        })

    async def _auth_logout(self, request: web.Request) -> web.Response:
        resp = _json({"status": "ok"})
        resp.del_cookie("eve_token")
        return resp

    # ── Bot info ─────────────────────────────────────────────────────────

    async def _bot_info(self, request: web.Request) -> web.Response:
        bot = self.bot
        app_info = await bot.application_info()
        prefixes = await bot.get_valid_prefixes()
        return _json({
            "name": bot.user.name,
            "id": str(bot.user.id),
            "avatar": str(bot.user.display_avatar.url),
            "discriminator": bot.user.discriminator,
            "guild_count": len(bot.guilds),
            "user_count": sum(g.member_count or 0 for g in bot.guilds),
            "channel_count": sum(len(g.channels) for g in bot.guilds),
            "cog_count": len(bot.cogs),
            "command_count": len(set(bot.walk_commands())),
            "prefixes": prefixes[:5],
            "description": app_info.description or "",
            "owner": {
                "id": str(app_info.owner.id) if app_info.owner else None,
                "name": str(app_info.owner) if app_info.owner else None,
            },
            "latency_ms": round(bot.latency * 1000, 1),
            "uptime_seconds": int(time.time() - self._start_time),
            "red_version": getattr(bot, "_red_version", "Unknown"),
        })

    async def _bot_stats(self, request: web.Request) -> web.Response:
        bot = self.bot
        guilds_by_size = sorted(bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        top_guilds = [
            {"name": g.name, "id": str(g.id), "members": g.member_count or 0, "icon": str(g.icon.url) if g.icon else None}
            for g in guilds_by_size[:10]
        ]

        # Channel type breakdown
        text_channels = sum(len(g.text_channels) for g in bot.guilds)
        voice_channels = sum(len(g.voice_channels) for g in bot.guilds)
        categories = sum(len(g.categories) for g in bot.guilds)

        return _json({
            "guilds": len(bot.guilds),
            "users": sum(g.member_count or 0 for g in bot.guilds),
            "text_channels": text_channels,
            "voice_channels": voice_channels,
            "categories": categories,
            "cogs_loaded": len(bot.cogs),
            "commands": len(set(bot.walk_commands())),
            "latency_ms": round(bot.latency * 1000, 1),
            "uptime_seconds": int(time.time() - self._start_time),
            "top_guilds": top_guilds,
            "message_count": self._message_count,
            "command_count": self._command_count,
        })

    # ── Guilds ───────────────────────────────────────────────────────────

    async def _guilds_list(self, request: web.Request) -> web.Response:
        user_id = request["user_id"]
        is_owner = request["is_owner"]
        query = request.query.get("q", "").lower()

        guilds = []
        for g in self.bot.guilds:
            if not is_owner:
                member = g.get_member(user_id)
                if not member:
                    continue
                if not (member.guild_permissions.manage_guild or member.guild_permissions.administrator):
                    continue
            if query and query not in g.name.lower():
                continue
            guilds.append({
                "id": str(g.id),
                "name": g.name,
                "icon": str(g.icon.url) if g.icon else None,
                "member_count": g.member_count or 0,
                "channel_count": len(g.channels),
                "role_count": len(g.roles),
                "owner_id": str(g.owner_id),
            })

        guilds.sort(key=lambda x: x["member_count"], reverse=True)
        return _json({"guilds": guilds})

    async def _guild_detail(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)

        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        return _json({
            "id": str(guild.id),
            "name": guild.name,
            "icon": str(guild.icon.url) if guild.icon else None,
            "banner": str(guild.banner.url) if guild.banner else None,
            "member_count": guild.member_count or 0,
            "channel_count": len(guild.channels),
            "text_channels": len(guild.text_channels),
            "voice_channels": len(guild.voice_channels),
            "role_count": len(guild.roles),
            "emoji_count": len(guild.emojis),
            "boost_level": guild.premium_tier,
            "boost_count": guild.premium_subscription_count or 0,
            "owner": {"id": str(guild.owner_id), "name": str(guild.owner) if guild.owner else "Unknown"},
            "created_at": guild.created_at.isoformat(),
            "features": list(guild.features),
        })

    async def _guild_channels(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        channels = []
        for c in sorted(guild.channels, key=lambda x: (x.position, x.name)):
            channels.append({
                "id": str(c.id),
                "name": c.name,
                "type": str(c.type),
                "position": c.position,
                "category": str(c.category_id) if c.category_id else None,
            })
        return _json({"channels": channels})

    async def _guild_roles(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        roles = []
        for r in sorted(guild.roles, key=lambda x: x.position, reverse=True):
            roles.append({
                "id": str(r.id),
                "name": r.name,
                "color": str(r.color),
                "position": r.position,
                "mentionable": r.mentionable,
                "hoist": r.hoist,
                "managed": r.managed,
                "member_count": len(r.members),
            })
        return _json({"roles": roles})

    # ── Guild settings ───────────────────────────────────────────────────

    async def _guild_settings_get(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        prefixes = await self.bot.get_valid_prefixes(guild)
        # Get admin/mod roles from Red's config
        admin_role_ids = await self.bot._config.guild(guild).admin_role()
        mod_role_ids = await self.bot._config.guild(guild).mod_role()

        # Ignored status
        ignored = await self.bot._config.guild(guild).ignored()

        # Disabled commands
        disabled_cmds = await self.bot._config.guild(guild).disabled_commands()

        # Bot nickname
        bot_member = guild.get_member(self.bot.user.id)
        bot_nick = bot_member.nick if bot_member else None

        return _json({
            "prefixes": prefixes,
            "admin_roles": [str(r) for r in admin_role_ids],
            "mod_roles": [str(r) for r in mod_role_ids],
            "ignored": ignored,
            "disabled_commands": list(disabled_cmds),
            "bot_nickname": bot_nick,
        })

    async def _guild_settings_update(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        data = await request.json()

        if "prefixes" in data:
            prefixes = data["prefixes"]
            if isinstance(prefixes, list) and prefixes:
                await self.bot._config.guild(guild).prefix.set(prefixes)

        if "admin_roles" in data:
            role_ids = [int(r) for r in data["admin_roles"] if r]
            await self.bot._config.guild(guild).admin_role.set(role_ids)

        if "mod_roles" in data:
            role_ids = [int(r) for r in data["mod_roles"] if r]
            await self.bot._config.guild(guild).mod_role.set(role_ids)

        if "bot_nickname" in data:
            bot_member = guild.get_member(self.bot.user.id)
            if bot_member:
                try:
                    await bot_member.edit(nick=data["bot_nickname"] or None)
                except Exception:
                    pass

        return _json({"status": "ok"})

    # ── Commands ─────────────────────────────────────────────────────────

    async def _guild_commands(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        disabled_cmds = await self.bot._config.guild(guild).disabled_commands()

        cogs_data = {}
        for cmd in sorted(self.bot.walk_commands(), key=lambda c: c.qualified_name):
            cog_name = cmd.cog_name or "No Category"
            if cog_name not in cogs_data:
                cog = cmd.cog
                cogs_data[cog_name] = {
                    "name": cog_name,
                    "description": (cog.__doc__ or "").strip().split("\n")[0] if cog else "",
                    "commands": [],
                }

            cogs_data[cog_name]["commands"].append({
                "name": cmd.qualified_name,
                "description": cmd.short_doc or "",
                "enabled": cmd.qualified_name not in disabled_cmds,
                "hidden": cmd.hidden,
                "aliases": list(cmd.aliases),
                "signature": cmd.signature,
                "parent": cmd.parent.qualified_name if cmd.parent else None,
            })

        return _json({"cogs": cogs_data})

    async def _guild_command_toggle(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        cmd_name = request.match_info["command"]
        data = await request.json()
        enabled = data.get("enabled", True)

        async with self.bot._config.guild(guild).disabled_commands() as disabled:
            if enabled and cmd_name in disabled:
                disabled.remove(cmd_name)
            elif not enabled and cmd_name not in disabled:
                disabled.append(cmd_name)

        return _json({"status": "ok", "command": cmd_name, "enabled": enabled})

    # ── Cog management ───────────────────────────────────────────────────

    async def _cogs_list(self, request: web.Request) -> web.Response:
        loaded = {}
        for name, cog in self.bot.cogs.items():
            loaded[name] = {
                "name": name,
                "loaded": True,
                "description": (cog.__doc__ or "").strip().split("\n")[0],
                "author": getattr(cog, "__author__", "Unknown"),
                "commands": [c.qualified_name for c in cog.get_commands()],
            }

        # Get available cogs from downloader if available
        available = []
        downloader = self.bot.get_cog("Downloader")
        if downloader:
            try:
                installed = await downloader.installed_cogs()
                for inst_cog in installed:
                    cog_name = inst_cog.name
                    if cog_name not in loaded:
                        available.append({
                            "name": cog_name,
                            "loaded": False,
                            "description": "",
                            "repo": str(getattr(inst_cog, "repo_name", "unknown")),
                        })
            except Exception:
                pass

        return _json({"loaded": loaded, "available": available})

    async def _cog_load(self, request: web.Request) -> web.Response:
        cog_name = request.match_info["cog_name"]
        try:
            await self.bot.load_extension(f"cogs.{cog_name}")
            return _json({"status": "ok", "message": f"{cog_name} loaded"})
        except Exception as e:
            # Try Red's cog loading
            try:
                spec = await self.bot._cog_mgr.find_cog(cog_name)
                if spec:
                    await self.bot.load_extension(spec)
                    return _json({"status": "ok", "message": f"{cog_name} loaded"})
            except Exception as e2:
                return _err(f"Failed to load {cog_name}: {e2}")
            return _err(f"Failed to load {cog_name}: {e}")

    async def _cog_unload(self, request: web.Request) -> web.Response:
        cog_name = request.match_info["cog_name"]
        if cog_name.lower() == "dashboard":
            return _err("Cannot unload the Dashboard cog from the dashboard")
        try:
            await self.bot.remove_cog(cog_name)
            return _json({"status": "ok", "message": f"{cog_name} unloaded"})
        except Exception as e:
            return _err(f"Failed to unload {cog_name}: {e}")

    async def _cog_reload(self, request: web.Request) -> web.Response:
        cog_name = request.match_info["cog_name"]
        try:
            cog = self.bot.get_cog(cog_name)
            if cog:
                module = cog.__module__
                await self.bot.remove_cog(cog_name)
                await self.bot.load_extension(module)
                return _json({"status": "ok", "message": f"{cog_name} reloaded"})
            return _err(f"Cog {cog_name} not found")
        except Exception as e:
            return _err(f"Failed to reload {cog_name}: {e}")

    # ── Third-party integration ──────────────────────────────────────────

    async def _third_parties_list(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        tp_info = self.cog.third_parties.get_third_parties_info()
        return _json({"third_parties": tp_info})

    async def _third_party_page(self, request: web.Request) -> web.Response:
        guild = self._get_guild(request)
        if not guild:
            return _err("Guild not found", 404)
        if not await self._check_guild_access(request, guild):
            return _err("Forbidden", 403)

        cog_name = request.match_info["cog_name"]
        page_name = request.match_info["page"]
        user = self.bot.get_user(request["user_id"])

        data = None
        if request.method == "POST":
            data = await request.json()

        result = await self.cog.third_parties.call_page(
            cog_name, page_name,
            user=user, guild=guild,
            method=request.method, data=data,
        )
        return _json(result)

    # ── Admin ────────────────────────────────────────────────────────────

    async def _admin_config(self, request: web.Request) -> web.Response:
        prefixes = await self.bot._config.prefix()
        return _json({
            "global_prefixes": prefixes,
            "owner_ids": [str(uid) for uid in self.bot.owner_ids],
            "embeds": await self.bot._config.embeds(),
            "color": await self.bot._config.color(),
            "fuzzy": await self.bot._config.fuzzy(),
            "invite_public": await self.bot._config.invite_public(),
            "invite_perm": await self.bot._config.invite_perm(),
            "disabled_commands": list(await self.bot._config.disabled_commands()),
            "locale": await self.bot._config.locale(),
        })

    async def _admin_config_update(self, request: web.Request) -> web.Response:
        data = await request.json()

        if "global_prefixes" in data:
            prefixes = data["global_prefixes"]
            if isinstance(prefixes, list) and prefixes:
                await self.bot._config.prefix.set(prefixes)

        if "embeds" in data:
            await self.bot._config.embeds.set(bool(data["embeds"]))

        if "fuzzy" in data:
            await self.bot._config.fuzzy.set(bool(data["fuzzy"]))

        if "invite_public" in data:
            await self.bot._config.invite_public.set(bool(data["invite_public"]))

        if "locale" in data:
            await self.bot._config.locale.set(data["locale"])

        return _json({"status": "ok"})

    async def _admin_blacklist(self, request: web.Request) -> web.Response:
        blacklist = await self.cog.config.blacklist()
        users = []
        for uid in blacklist:
            user = self.bot.get_user(uid)
            users.append({
                "id": str(uid),
                "name": str(user) if user else f"Unknown#{uid}",
                "avatar": str(user.display_avatar.url) if user and user.display_avatar else None,
            })
        return _json({"blacklist": users})

    async def _admin_blacklist_add(self, request: web.Request) -> web.Response:
        data = await request.json()
        user_id = int(data.get("user_id", 0))
        if not user_id:
            return _err("Invalid user ID")
        async with self.cog.config.blacklist() as bl:
            if user_id not in bl:
                bl.append(user_id)
        return _json({"status": "ok"})

    async def _admin_blacklist_remove(self, request: web.Request) -> web.Response:
        user_id = int(request.match_info["user_id"])
        async with self.cog.config.blacklist() as bl:
            if user_id in bl:
                bl.remove(user_id)
        return _json({"status": "ok"})

    async def _admin_whitelist(self, request: web.Request) -> web.Response:
        # Red's global whitelist
        try:
            whitelist = await self.bot._config.whitelist()
            users = []
            for uid in whitelist:
                user = self.bot.get_user(uid)
                users.append({
                    "id": str(uid),
                    "name": str(user) if user else f"Unknown#{uid}",
                })
            return _json({"whitelist": users})
        except Exception:
            return _json({"whitelist": []})

    # ── WebSocket ────────────────────────────────────────────────────────

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Authenticate via first message
        user_id = request["user_id"]
        if not user_id:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=10)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    secret = await self.cog.config.secret_key()
                    user_id = _verify_token(data.get("token", ""), secret)
            except Exception:
                pass

        if not user_id:
            await ws.close(message=b"Unauthorized")
            return ws

        await self.ws_manager.add(user_id, ws)
        await ws.send_json({"event": "connected", "data": {"user_id": str(user_id)}})

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "ping":
                        await ws.send_json({"event": "pong", "data": {}})
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            await self.ws_manager.remove(user_id, ws)

        return ws

    # ── Static serving ───────────────────────────────────────────────────

    async def _serve_index(self, request: web.Request) -> web.Response:
        index_path = WEB_DIR / "index.html"
        if index_path.exists():
            return web.FileResponse(index_path)
        return _err("Frontend not found", 500)

    async def _serve_spa(self, request: web.Request) -> web.Response:
        path = request.match_info.get("path", "")

        # Resolve and verify the final path stays inside WEB_DIR before ever
        # touching the filesystem — rejects `../`, percent-encoded traversal
        # (e.g. `..%2f`), and symlink escapes alike. This route is reachable
        # with no authentication (see the auth middleware's path allowlist),
        # so this check is the only thing standing between it and arbitrary
        # file read on the host.
        try:
            file_path = (WEB_DIR / path).resolve()
            file_path.relative_to(WEB_DIR.resolve())
        except (ValueError, OSError):
            return _err("Not found", 404)

        # Serve actual files if they exist
        if file_path.is_file():
            return web.FileResponse(file_path)

        # Otherwise serve index.html (SPA routing)
        index_path = WEB_DIR / "index.html"
        if index_path.exists():
            return web.FileResponse(index_path)
        return _err("Not found", 404)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_guild(self, request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
            return self.bot.get_guild(guild_id)
        except (KeyError, ValueError):
            return None

    async def _check_guild_access(self, request: web.Request, guild) -> bool:
        if request["is_owner"]:
            return True
        user_id = request["user_id"]
        member = guild.get_member(user_id)
        if not member:
            # Cache miss (e.g. Members intent not warmed for this guild yet)
            # shouldn't wrongly deny a real admin — fall back to a live fetch.
            # Only done for single-guild endpoints (this method), never in
            # bulk over every guild the bot is in — see _guilds_list.
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                return False
        return member.guild_permissions.manage_guild or member.guild_permissions.administrator
