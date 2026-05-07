"""
EveDash SDK — Add dashboard support to any Red-DiscordBot cog.

Quick Start
-----------
1. Import the decorator and listener mixin:

    from dashboard.sdk import dashboard_page

2. Add a listener so the dashboard discovers your cog:

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog):
        dashboard_cog.rpc.add_third_party(self)

    @commands.Cog.listener()
    async def on_dashboard_cog_remove(self, dashboard_cog):
        dashboard_cog.rpc.remove_third_party(self)

3. Decorate methods with @dashboard_page to expose them:

    @dashboard_page(
        name="settings",
        description="Configure MyCog settings",
        methods=("GET", "POST"),
        is_owner=False,
    )
    async def dashboard_settings_page(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            # Save settings
            await self.config.guild(guild).welcome_channel.set(data.get("welcome_channel"))
            return {"status": 0, "notifications": [{"type": "success", "message": "Settings saved!"}]}

        # Return settings schema for the dashboard to auto-render
        current = await self.config.guild(guild).all()
        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {
                        "id": "welcome_channel",
                        "type": "channel_select",
                        "label": "Welcome Channel",
                        "description": "Channel where welcome messages are sent",
                        "value": current.get("welcome_channel"),
                    },
                    {
                        "id": "welcome_message",
                        "type": "textarea",
                        "label": "Welcome Message",
                        "description": "Supports {user}, {server}, {member_count}",
                        "value": current.get("welcome_message", ""),
                        "placeholder": "Welcome {user} to {server}!",
                    },
                    {
                        "id": "enabled",
                        "type": "toggle",
                        "label": "Enable Welcome Messages",
                        "value": current.get("enabled", False),
                    },
                    {
                        "id": "auto_role",
                        "type": "role_select",
                        "label": "Auto Role",
                        "description": "Role assigned to new members",
                        "value": current.get("auto_role"),
                    },
                    {
                        "id": "log_channel",
                        "type": "channel_select",
                        "label": "Log Channel",
                        "value": current.get("log_channel"),
                    },
                ],
            },
        }

Setting Types
-------------
- ``text``           — Single-line text input
- ``textarea``       — Multi-line text input
- ``number``         — Numeric input (supports min/max)
- ``toggle``         — Boolean on/off switch
- ``select``         — Dropdown with options: [{"label": "...", "value": "..."}]
- ``multi_select``   — Multi-select dropdown
- ``channel_select`` — Discord channel picker
- ``role_select``    — Discord role picker
- ``color``          — Color picker
- ``slider``         — Range slider (supports min/max/step)
"""

from __future__ import annotations

import inspect
import typing

if typing.TYPE_CHECKING:
    from redbot.core import commands


def dashboard_page(
    name: str | None = None,
    description: str | None = None,
    methods: tuple[str, ...] = ("GET",),
    is_owner: bool = False,
    hidden: bool = False,
    icon: str | None = None,
    order: int = 0,
):
    """Decorator to register a cog method as a dashboard page.

    Parameters
    ----------
    name:
        URL-safe page name (e.g. ``"settings"``). Defaults to function name.
    description:
        Human-readable page description shown in the dashboard sidebar.
    methods:
        HTTP methods this page handles (``"GET"``, ``"POST"``, etc.).
    is_owner:
        If ``True``, only bot owners can access this page.
    hidden:
        If ``True``, the page won't appear in navigation but is still accessible.
    icon:
        Icon class for sidebar (e.g. ``"fas fa-cog"``). Defaults to a gear icon.
    order:
        Sort order in the sidebar. Lower numbers appear first.
    """

    def decorator(func: typing.Callable):
        if not inspect.iscoroutinefunction(func):
            raise TypeError("Dashboard page handler must be a coroutine function.")

        func.__dashboard_params__ = {
            "name": name or func.__name__,
            "description": description or func.__doc__ or "No description",
            "methods": methods,
            "is_owner": is_owner,
            "hidden": hidden,
            "icon": icon or "fas fa-puzzle-piece",
            "order": order,
        }
        return func

    return decorator


class ThirdPartyManager:
    """Manages third-party cog registrations for the dashboard."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.third_parties: dict[str, dict] = {}
        self.third_party_cogs: dict[str, commands.Cog] = {}

    def add_third_party(self, cog) -> None:
        """Register a cog's dashboard pages."""
        name = cog.qualified_name
        pages: dict[str, dict] = {}

        for attr_name in dir(cog):
            try:
                func = getattr(cog, attr_name)
                if hasattr(func, "__dashboard_params__"):
                    params = func.__dashboard_params__
                    page_name = params["name"]
                    pages[page_name] = {
                        "func": func,
                        "params": params,
                    }
            except (TypeError, AttributeError):
                continue

        if not pages:
            return

        self.third_parties[name] = pages
        self.third_party_cogs[name] = cog

    def remove_third_party(self, cog) -> None:
        """Unregister a cog's dashboard pages."""
        name = cog.qualified_name
        self.third_parties.pop(name, None)
        self.third_party_cogs.pop(name, None)

    def get_third_parties_info(self) -> dict:
        """Get info about all registered third parties for the API."""
        result = {}
        for name, pages in self.third_parties.items():
            cog = self.third_party_cogs.get(name)
            result[name] = {
                "name": name,
                "description": getattr(cog, "__doc__", None) or "No description",
                "author": getattr(cog, "__author__", "Unknown"),
                "pages": {
                    page_name: {
                        k: v
                        for k, v in page_data["params"].items()
                    }
                    for page_name, page_data in pages.items()
                },
            }
        return result

    async def call_page(
        self,
        cog_name: str,
        page_name: str,
        *,
        user=None,
        guild=None,
        method: str = "GET",
        data: dict | None = None,
    ) -> dict:
        """Call a third-party page handler."""
        if cog_name not in self.third_parties:
            return {"status": 1, "error": "Third party not found"}
        pages = self.third_parties[cog_name]
        if page_name not in pages:
            return {"status": 1, "error": "Page not found"}

        page = pages[page_name]
        params = page["params"]

        if params["is_owner"]:
            if user is None or user.id not in self.bot.owner_ids:
                return {"status": 1, "error": "Forbidden — owner only"}

        if method not in params["methods"]:
            return {"status": 1, "error": f"Method {method} not allowed"}

        handler = page["func"]
        kwargs = {}
        sig = inspect.signature(handler)
        for param_name in sig.parameters:
            if param_name == "self":
                continue
            if param_name == "user":
                kwargs["user"] = user
            elif param_name == "guild":
                kwargs["guild"] = guild
            elif param_name == "method":
                kwargs["method"] = method
            elif param_name == "data":
                kwargs["data"] = data or {}

        try:
            result = await handler(**kwargs)
            return result
        except Exception as e:
            return {"status": 1, "error": str(e)}
