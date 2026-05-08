"""NexusCore — Dashboard Integration: web-based config for all 8 modules."""

from __future__ import annotations

import typing

import discord
from redbot.core import commands

if typing.TYPE_CHECKING:
    pass

# Try importing the dashboard SDK (graceful if not installed)
try:
    from dashboard.sdk import dashboard_page
except ImportError:
    # Stub if dashboard cog isn't loaded
    def dashboard_page(**kwargs):
        def decorator(func):
            return func
        return decorator

from .utils import ts_now


class DashboardMixin:
    """Dashboard integration mixin — registers pages for all NexusCore modules."""

    # ── Lifecycle listeners ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog):
        dashboard_cog.rpc.add_third_party(self)

    @commands.Cog.listener()
    async def on_dashboard_cog_remove(self, dashboard_cog):
        dashboard_cog.rpc.remove_third_party(self)

    # ══════════════════════════════════════════════════════════════════════════
    # OVERVIEW PAGE
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="overview", description="NexusCore Overview & Dashboard", icon="fas fa-home", order=0)
    async def dashboard_overview(self, user, guild, **kwargs):
        # Gather stats from all modules
        ticket_data = await self.ticket_config.guild(guild).all()
        app_data = await self.app_config.guild(guild).all()
        suggest_data = await self.suggest_config.guild(guild).all()
        rr_data = await self.rr_config.guild(guild).all()
        give_data = await self.give_config.guild(guild).all()
        log_data = await self.log_config.guild(guild).all()
        mod_data = await self.mod_config.guild(guild).all()
        eco_data = await self.eco_config.guild(guild).all()

        open_tickets = len(ticket_data.get("open_tickets", {}))
        pending_apps = sum(1 for s in app_data.get("submissions", {}).values() if s.get("status") == "pending")
        total_suggestions = len(suggest_data.get("suggestions", {}))
        active_giveaways = sum(1 for g in give_data.get("giveaways", {}).values() if not g.get("ended"))
        total_cases = len(mod_data.get("cases", {}))
        rr_panels = len(rr_data.get("panels", {}))
        shop_items = len(eco_data.get("shop_items", {}))

        return {
            "status": 0,
            "web_content": {
                "source": "NexusCore overview",
                "stats": {
                    "open_tickets": open_tickets,
                    "pending_applications": pending_apps,
                    "total_suggestions": total_suggestions,
                    "active_giveaways": active_giveaways,
                    "moderation_cases": total_cases,
                    "reaction_role_panels": rr_panels,
                    "shop_items": shop_items,
                },
                "modules": {
                    "tickets": {"enabled": ticket_data.get("enabled", False), "icon": "fas fa-ticket-alt"},
                    "applications": {"enabled": app_data.get("enabled", False), "icon": "fas fa-clipboard-list"},
                    "suggestions": {"enabled": suggest_data.get("enabled", False), "icon": "fas fa-lightbulb"},
                    "reaction_roles": {"enabled": rr_data.get("enabled", True), "icon": "fas fa-theater-masks"},
                    "giveaways": {"enabled": give_data.get("enabled", True), "icon": "fas fa-gift"},
                    "logging": {"enabled": log_data.get("enabled", False), "icon": "fas fa-clipboard"},
                    "moderation": {"enabled": mod_data.get("enabled", True), "icon": "fas fa-shield-alt"},
                    "economy": {"enabled": eco_data.get("enabled", True), "icon": "fas fa-coins"},
                },
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # TICKETS DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="tickets", description="Ticket System Settings", methods=("GET", "POST"), icon="fas fa-ticket-alt", order=1)
    async def dashboard_tickets(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            mapping = {
                "enabled": ("enabled", bool),
                "log_channel": ("log_channel", lambda x: int(x) if x else None),
                "category_id": ("category_id", lambda x: int(x) if x else None),
                "transcript_channel": ("transcript_channel", lambda x: int(x) if x else None),
                "max_per_user": ("max_per_user", int),
                "claim_enabled": ("claim_enabled", bool),
                "feedback_enabled": ("feedback_enabled", bool),
                "dm_on_open": ("dm_on_open", bool),
                "dm_on_close": ("dm_on_close", bool),
                "allow_user_close": ("allow_user_close", bool),
                "auto_pin_first": ("auto_pin_first", bool),
                "thread_mode": ("thread_mode", bool),
                "auto_close_hours": ("auto_close_hours", int),
                "custom_open_msg": ("custom_open_msg", str),
                "custom_close_msg": ("custom_close_msg", str),
            }
            for key, (config_key, converter) in mapping.items():
                if key in data:
                    try:
                        val = converter(data[key])
                        await getattr(self.ticket_config.guild(guild), config_key).set(val)
                    except (ValueError, TypeError):
                        pass
            return {"status": 0, "notifications": [{"type": "success", "message": "Ticket settings saved!"}]}

        current = await self.ticket_config.guild(guild).all()
        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Tickets", "value": current.get("enabled", False)},
                    {"id": "log_channel", "type": "channel_select", "label": "Log Channel", "value": current.get("log_channel")},
                    {"id": "category_id", "type": "channel_select", "label": "Ticket Category", "value": current.get("category_id")},
                    {"id": "transcript_channel", "type": "channel_select", "label": "Transcript Channel", "value": current.get("transcript_channel")},
                    {"id": "max_per_user", "type": "number", "label": "Max Tickets Per User", "value": current.get("max_per_user", 3), "min": 1, "max": 25},
                    {"id": "claim_enabled", "type": "toggle", "label": "Staff Claim System", "value": current.get("claim_enabled", True)},
                    {"id": "feedback_enabled", "type": "toggle", "label": "Feedback on Close", "value": current.get("feedback_enabled", True)},
                    {"id": "dm_on_open", "type": "toggle", "label": "DM on Open", "value": current.get("dm_on_open", True)},
                    {"id": "dm_on_close", "type": "toggle", "label": "DM on Close", "value": current.get("dm_on_close", True)},
                    {"id": "allow_user_close", "type": "toggle", "label": "Users Can Close", "value": current.get("allow_user_close", True)},
                    {"id": "auto_pin_first", "type": "toggle", "label": "Auto-Pin First Message", "value": current.get("auto_pin_first", True)},
                    {"id": "thread_mode", "type": "toggle", "label": "Thread Mode", "value": current.get("thread_mode", False)},
                    {"id": "auto_close_hours", "type": "number", "label": "Auto-Close After (hours, 0=off)", "value": current.get("auto_close_hours", 0), "min": 0, "max": 720},
                    {"id": "custom_open_msg", "type": "textarea", "label": "Custom Open Message", "description": "Vars: {user}, {category}, {ticket_id}", "value": current.get("custom_open_msg", "")},
                    {"id": "custom_close_msg", "type": "textarea", "label": "Custom Close Message", "value": current.get("custom_close_msg", "")},
                ],
                "categories": current.get("categories", {}),
                "open_tickets": len(current.get("open_tickets", {})),
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # APPLICATIONS DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="applications", description="Application System Settings", methods=("GET", "POST"), icon="fas fa-clipboard-list", order=2)
    async def dashboard_applications(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            for key in ("enabled", "review_channel", "dm_on_accept", "dm_on_deny"):
                if key in data:
                    val = data[key]
                    if key == "review_channel":
                        val = int(val) if val else None
                    elif key == "enabled":
                        val = bool(val)
                    await getattr(self.app_config.guild(guild), key).set(val)
            return {"status": 0, "notifications": [{"type": "success", "message": "Application settings saved!"}]}

        current = await self.app_config.guild(guild).all()
        pending = sum(1 for s in current.get("submissions", {}).values() if s.get("status") == "pending")
        accepted = sum(1 for s in current.get("submissions", {}).values() if s.get("status") == "accepted")
        denied = sum(1 for s in current.get("submissions", {}).values() if s.get("status") == "denied")

        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Applications", "value": current.get("enabled", False)},
                    {"id": "review_channel", "type": "channel_select", "label": "Review Channel", "value": current.get("review_channel")},
                    {"id": "dm_on_accept", "type": "toggle", "label": "DM on Accept", "value": current.get("dm_on_accept", True)},
                    {"id": "dm_on_deny", "type": "toggle", "label": "DM on Deny", "value": current.get("dm_on_deny", True)},
                ],
                "types": current.get("types", {}),
                "stats": {"pending": pending, "accepted": accepted, "denied": denied, "total": len(current.get("submissions", {}))},
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # SUGGESTIONS DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="suggestions", description="Suggestion System Settings", methods=("GET", "POST"), icon="fas fa-lightbulb", order=3)
    async def dashboard_suggestions(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            mapping = {
                "enabled": bool, "channel": lambda x: int(x) if x else None,
                "anonymous": bool, "auto_thread": bool,
                "min_length": int, "max_length": int,
                "auto_approve_threshold": int,
            }
            for key, converter in mapping.items():
                if key in data:
                    try:
                        await getattr(self.suggest_config.guild(guild), key).set(converter(data[key]))
                    except (ValueError, TypeError):
                        pass
            return {"status": 0, "notifications": [{"type": "success", "message": "Suggestion settings saved!"}]}

        current = await self.suggest_config.guild(guild).all()
        subs = current.get("suggestions", {})
        status_counts = {}
        for s in subs.values():
            st = s.get("status", "pending")
            status_counts[st] = status_counts.get(st, 0) + 1

        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Suggestions", "value": current.get("enabled", False)},
                    {"id": "channel", "type": "channel_select", "label": "Suggestions Channel", "value": current.get("channel")},
                    {"id": "anonymous", "type": "toggle", "label": "Anonymous Mode", "value": current.get("anonymous", False)},
                    {"id": "auto_thread", "type": "toggle", "label": "Auto-Thread", "value": current.get("auto_thread", True)},
                    {"id": "min_length", "type": "number", "label": "Min Length", "value": current.get("min_length", 10), "min": 1, "max": 500},
                    {"id": "max_length", "type": "number", "label": "Max Length", "value": current.get("max_length", 2000), "min": 10, "max": 4000},
                    {"id": "auto_approve_threshold", "type": "number", "label": "Auto-Approve at X Upvotes (0=off)", "value": current.get("auto_approve_threshold", 0), "min": 0, "max": 1000},
                ],
                "stats": {"total": len(subs), "by_status": status_counts},
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # REACTION ROLES DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="reaction_roles", description="Reaction Role Panel Settings", methods=("GET", "POST"), icon="fas fa-theater-masks", order=4)
    async def dashboard_reaction_roles(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            if data.get("action") == "toggle":
                await self.rr_config.guild(guild).enabled.set(bool(data.get("enabled", True)))
            return {"status": 0, "notifications": [{"type": "success", "message": "Reaction role settings saved!"}]}

        current = await self.rr_config.guild(guild).all()
        panels_info = {}
        for pid, p in current.get("panels", {}).items():
            ch = guild.get_channel(p["channel_id"])
            panels_info[pid] = {
                "title": p.get("title", "Untitled"),
                "mode": p.get("mode", "button"),
                "channel": {"id": str(p["channel_id"]), "name": ch.name if ch else "deleted"},
                "roles_count": len(p.get("roles", [])),
                "sticky": p.get("sticky", False),
                "temp_minutes": p.get("temp_minutes", 0),
                "max_roles": p.get("max_roles", 0),
            }

        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Reaction Roles", "value": current.get("enabled", True)},
                ],
                "panels": panels_info,
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # GIVEAWAYS DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="giveaways", description="Giveaway System Settings", methods=("GET", "POST"), icon="fas fa-gift", order=5)
    async def dashboard_giveaways(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            for key in ("enabled", "dm_winners", "dm_host", "default_colour"):
                if key in data:
                    val = data[key]
                    if key in ("dm_winners", "dm_host", "enabled"):
                        val = bool(val)
                    await getattr(self.give_config.guild(guild), key).set(val)
            return {"status": 0, "notifications": [{"type": "success", "message": "Giveaway settings saved!"}]}

        current = await self.give_config.guild(guild).all()
        gws = current.get("giveaways", {})
        active = {k: v for k, v in gws.items() if not v.get("ended")}
        ended = {k: v for k, v in gws.items() if v.get("ended")}

        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Giveaways", "value": current.get("enabled", True)},
                    {"id": "dm_winners", "type": "toggle", "label": "DM Winners", "value": current.get("dm_winners", True)},
                    {"id": "dm_host", "type": "toggle", "label": "DM Host", "value": current.get("dm_host", True)},
                ],
                "stats": {"active": len(active), "ended": len(ended), "total_entries": sum(len(g.get("entries", [])) for g in gws.values())},
                "active_giveaways": [
                    {"id": k, "prize": v["prize"], "ends_at": v["ends_at"], "entries": len(v.get("entries", [])), "winners": v["winners_count"]}
                    for k, v in active.items()
                ],
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # LOGGING DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="logging", description="Server Logging Settings", methods=("GET", "POST"), icon="fas fa-clipboard", order=6)
    async def dashboard_logging(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            if "enabled" in data:
                await self.log_config.guild(guild).enabled.set(bool(data["enabled"]))
            if "default_channel" in data:
                await self.log_config.guild(guild).default_channel.set(int(data["default_channel"]) if data["default_channel"] else None)
            if "ignore_bots" in data:
                await self.log_config.guild(guild).ignore_bots.set(bool(data["ignore_bots"]))
            if "channels" in data and isinstance(data["channels"], dict):
                await self.log_config.guild(guild).channels.set(
                    {k: int(v) for k, v in data["channels"].items() if v}
                )
            return {"status": 0, "notifications": [{"type": "success", "message": "Logging settings saved!"}]}

        current = await self.log_config.guild(guild).all()
        from .serverlog import EVENT_TYPES
        channel_routing = {}
        for evt in EVENT_TYPES:
            ch_id = current.get("channels", {}).get(evt)
            ch = guild.get_channel(ch_id) if ch_id else None
            channel_routing[evt] = {"channel_id": str(ch_id) if ch_id else None, "channel_name": ch.name if ch else None}

        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Logging", "value": current.get("enabled", False)},
                    {"id": "default_channel", "type": "channel_select", "label": "Default Log Channel", "value": current.get("default_channel")},
                    {"id": "ignore_bots", "type": "toggle", "label": "Ignore Bots", "value": current.get("ignore_bots", True)},
                ],
                "event_types": EVENT_TYPES,
                "channel_routing": channel_routing,
                "ignore": {
                    "channels": current.get("ignore_channels", []),
                    "roles": current.get("ignore_roles", []),
                    "users": current.get("ignore_users", []),
                },
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # MODERATION DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="moderation", description="Moderation Settings & Cases", methods=("GET", "POST"), icon="fas fa-shield-alt", order=7)
    async def dashboard_moderation(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            simple_keys = {
                "enabled": bool, "modlog_channel": lambda x: int(x) if x else None,
                "dm_on_action": bool, "appeal_enabled": bool,
                "appeal_channel": lambda x: int(x) if x else None,
                "warn_decay_days": int,
            }
            for key, converter in simple_keys.items():
                if key in data:
                    try:
                        await getattr(self.mod_config.guild(guild), key).set(converter(data[key]))
                    except (ValueError, TypeError):
                        pass

            if "anti_raid" in data and isinstance(data["anti_raid"], dict):
                await self.mod_config.guild(guild).anti_raid.set(data["anti_raid"])
            if "anti_nuke" in data and isinstance(data["anti_nuke"], dict):
                await self.mod_config.guild(guild).anti_nuke.set(data["anti_nuke"])
            if "auto_mod" in data and isinstance(data["auto_mod"], dict):
                await self.mod_config.guild(guild).auto_mod.set(data["auto_mod"])
            if "escalation" in data and isinstance(data["escalation"], dict):
                await self.mod_config.guild(guild).escalation.set(data["escalation"])

            return {"status": 0, "notifications": [{"type": "success", "message": "Moderation settings saved!"}]}

        current = await self.mod_config.guild(guild).all()
        cases = current.get("cases", {})
        type_counts = {}
        for c in cases.values():
            t = c.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Moderation", "value": current.get("enabled", True)},
                    {"id": "modlog_channel", "type": "channel_select", "label": "Modlog Channel", "value": current.get("modlog_channel")},
                    {"id": "dm_on_action", "type": "toggle", "label": "DM Users on Action", "value": current.get("dm_on_action", True)},
                    {"id": "appeal_enabled", "type": "toggle", "label": "Enable Appeals", "value": current.get("appeal_enabled", False)},
                    {"id": "appeal_channel", "type": "channel_select", "label": "Appeal Channel", "value": current.get("appeal_channel")},
                    {"id": "warn_decay_days", "type": "number", "label": "Warning Decay (days, 0=never)", "value": current.get("warn_decay_days", 0), "min": 0, "max": 365},
                ],
                "stats": {"total_cases": len(cases), "by_type": type_counts},
                "anti_raid": current.get("anti_raid", {}),
                "anti_nuke": current.get("anti_nuke", {}),
                "auto_mod": current.get("auto_mod", {}),
                "escalation": current.get("escalation", {}),
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # ECONOMY DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="economy", description="Economy & Shop Settings", methods=("GET", "POST"), icon="fas fa-coins", order=8)
    async def dashboard_economy(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            simple_keys = {
                "enabled": bool, "currency_name": str, "currency_emoji": str,
                "currency_symbol": str, "starting_balance": int, "max_balance": int,
                "daily_amount": int, "daily_streak_bonus": int, "weekly_amount": int,
                "work_min": int, "work_max": int, "work_cooldown": int,
                "crime_min": int, "crime_max": int, "crime_cooldown": int,
                "crime_fail_chance": int, "rob_enabled": bool, "rob_cooldown": int,
                "rob_success_chance": int, "interest_rate": float, "tax_rate": float,
                "log_channel": lambda x: int(x) if x else None,
            }
            for key, converter in simple_keys.items():
                if key in data:
                    try:
                        await getattr(self.eco_config.guild(guild), key).set(converter(data[key]))
                    except (ValueError, TypeError, AttributeError):
                        pass

            if "gambling" in data and isinstance(data["gambling"], dict):
                await self.eco_config.guild(guild).gambling.set(data["gambling"])
            if "pets" in data and isinstance(data["pets"], dict):
                await self.eco_config.guild(guild).pets.set(data["pets"])

            # Shop item management
            if "add_item" in data:
                item = data["add_item"]
                from .utils import short_id
                item_id = short_id(8)
                async with self.eco_config.guild(guild).shop_items() as items:
                    items[item_id] = {
                        "name": item.get("name", "New Item"),
                        "description": item.get("description", ""),
                        "price": int(item.get("price", 100)),
                        "emoji": item.get("emoji", "📦"),
                        "role_id": int(item["role_id"]) if item.get("role_id") else None,
                        "stock": int(item.get("stock", -1)),
                        "max_per_user": int(item.get("max_per_user", 0)),
                        "type": item.get("type", "item"),
                        "usable": bool(item.get("usable", False)),
                    }

            if "remove_item" in data:
                async with self.eco_config.guild(guild).shop_items() as items:
                    items.pop(data["remove_item"], None)

            return {"status": 0, "notifications": [{"type": "success", "message": "Economy settings saved!"}]}

        current = await self.eco_config.guild(guild).all()
        all_members = await self.eco_config.all_members(guild)
        total_wealth = sum(d.get("wallet", 0) + d.get("bank", 0) for d in all_members.values())
        total_users = len(all_members)

        # Top 10 leaderboard
        rankings = sorted(
            [(uid, d.get("wallet", 0) + d.get("bank", 0)) for uid, d in all_members.items()],
            key=lambda x: x[1], reverse=True,
        )[:10]
        top_users = []
        for uid, total in rankings:
            member = guild.get_member(uid)
            top_users.append({
                "id": str(uid),
                "name": str(member) if member else f"Unknown#{uid}",
                "total": total,
            })

        return {
            "status": 0,
            "web_content": {
                "source": "EveDash auto-form",
                "settings": [
                    {"id": "enabled", "type": "toggle", "label": "Enable Economy", "value": current.get("enabled", True)},
                    {"id": "currency_name", "type": "text", "label": "Currency Name", "value": current.get("currency_name", "coins")},
                    {"id": "currency_emoji", "type": "text", "label": "Currency Emoji", "value": current.get("currency_emoji", "🪙")},
                    {"id": "currency_symbol", "type": "text", "label": "Currency Symbol", "value": current.get("currency_symbol", "$")},
                    {"id": "starting_balance", "type": "number", "label": "Starting Balance", "value": current.get("starting_balance", 100), "min": 0},
                    {"id": "max_balance", "type": "number", "label": "Max Balance", "value": current.get("max_balance", 10000000), "min": 0},
                    {"id": "daily_amount", "type": "number", "label": "Daily Amount", "value": current.get("daily_amount", 200), "min": 0},
                    {"id": "daily_streak_bonus", "type": "number", "label": "Streak Bonus/Day", "value": current.get("daily_streak_bonus", 50), "min": 0},
                    {"id": "weekly_amount", "type": "number", "label": "Weekly Amount", "value": current.get("weekly_amount", 1500), "min": 0},
                    {"id": "work_min", "type": "number", "label": "Work Min", "value": current.get("work_min", 50)},
                    {"id": "work_max", "type": "number", "label": "Work Max", "value": current.get("work_max", 300)},
                    {"id": "work_cooldown", "type": "number", "label": "Work Cooldown (sec)", "value": current.get("work_cooldown", 3600)},
                    {"id": "crime_min", "type": "number", "label": "Crime Min", "value": current.get("crime_min", 100)},
                    {"id": "crime_max", "type": "number", "label": "Crime Max", "value": current.get("crime_max", 800)},
                    {"id": "crime_fail_chance", "type": "slider", "label": "Crime Fail %", "value": current.get("crime_fail_chance", 40), "min": 0, "max": 100, "step": 5},
                    {"id": "rob_enabled", "type": "toggle", "label": "Enable Robbing", "value": current.get("rob_enabled", True)},
                    {"id": "rob_success_chance", "type": "slider", "label": "Rob Success %", "value": current.get("rob_success_chance", 45), "min": 0, "max": 100, "step": 5},
                    {"id": "tax_rate", "type": "slider", "label": "Transfer Tax %", "value": current.get("tax_rate", 0), "min": 0, "max": 50, "step": 1},
                    {"id": "log_channel", "type": "channel_select", "label": "Economy Log Channel", "value": current.get("log_channel")},
                ],
                "shop_items": current.get("shop_items", {}),
                "gambling": current.get("gambling", {}),
                "pets": current.get("pets", {}),
                "stats": {
                    "total_wealth": total_wealth,
                    "total_users": total_users,
                    "avg_balance": total_wealth // max(total_users, 1),
                },
                "leaderboard": top_users,
            },
        }

    # ══════════════════════════════════════════════════════════════════════════
    # EMBED BUILDER DASHBOARD
    # ══════════════════════════════════════════════════════════════════════════

    @dashboard_page(name="embed_builder", description="Webhook Embed Builder", methods=("GET", "POST"), icon="fas fa-paint-brush", order=9)
    async def dashboard_embed_builder(self, user, guild, method="GET", data=None, **kwargs):
        if method == "POST" and data:
            action = data.get("action")

            if action == "send":
                channel_id = int(data.get("channel_id", 0))
                channel = guild.get_channel(channel_id)
                if not channel:
                    return {"status": 1, "error": "Channel not found"}

                embeds_data = data.get("embeds", [])
                content = data.get("content", "")
                webhook_name = data.get("webhook_name", "NexusCore")
                webhook_avatar = data.get("webhook_avatar", "")

                webhook = None
                for wh in await channel.webhooks():
                    if wh.name == webhook_name:
                        webhook = wh
                        break
                if not webhook:
                    webhook = await channel.create_webhook(name=webhook_name)

                embeds = []
                for ed in embeds_data[:10]:
                    embed = self._build_embed_from_data(ed, guild)
                    embeds.append(embed)

                await webhook.send(
                    content=content or None,
                    embeds=embeds or None,
                    username=webhook_name,
                    avatar_url=webhook_avatar or None,
                )
                return {"status": 0, "notifications": [{"type": "success", "message": "Embed sent!"}]}

            if action == "save_template":
                template_name = data.get("template_name", "")
                if not template_name:
                    return {"status": 1, "error": "Template name required"}
                async with self.embed_config.guild(guild).templates() as templates:
                    templates[template_name] = {
                        "embeds": data.get("embeds", []),
                        "content": data.get("content", ""),
                        "webhook_name": data.get("webhook_name", "NexusCore"),
                        "saved_by": user.id,
                        "saved_at": ts_now(),
                    }
                return {"status": 0, "notifications": [{"type": "success", "message": f"Template '{template_name}' saved!"}]}

            return {"status": 1, "error": "Unknown action"}

        templates = await self.embed_config.guild(guild).templates()
        return {
            "status": 0,
            "web_content": {
                "source": "NexusCore embed builder",
                "templates": {k: {"embeds": v.get("embeds", []), "content": v.get("content", "")} for k, v in templates.items()},
                "channels": [
                    {"id": str(c.id), "name": c.name}
                    for c in sorted(guild.text_channels, key=lambda x: x.position)
                ],
            },
        }

    def _build_embed_from_data(self, data: dict, guild=None) -> discord.Embed:
        """Build a discord.Embed from a dict (dashboard/JSON input)."""
        embed = discord.Embed()
        if data.get("title"):
            embed.title = self._replace_vars(data["title"], guild)
        if data.get("description"):
            embed.description = self._replace_vars(data["description"], guild)
        if data.get("url"):
            embed.url = data["url"]
        if data.get("color") or data.get("colour"):
            color_val = data.get("color") or data.get("colour")
            if isinstance(color_val, str):
                color_val = int(color_val.lstrip("#"), 16)
            embed.colour = discord.Colour(color_val)
        if data.get("timestamp"):
            import datetime
            embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        if data.get("author"):
            a = data["author"]
            embed.set_author(name=a.get("name", ""), url=a.get("url", ""), icon_url=a.get("icon_url", ""))
        if data.get("footer"):
            f = data["footer"]
            embed.set_footer(text=f.get("text", ""), icon_url=f.get("icon_url", ""))
        if data.get("image"):
            embed.set_image(url=data["image"])
        if data.get("thumbnail"):
            embed.set_thumbnail(url=data["thumbnail"])
        for field in data.get("fields", [])[:25]:
            embed.add_field(
                name=field.get("name", "\u200b"),
                value=field.get("value", "\u200b"),
                inline=field.get("inline", True),
            )
        return embed

    def _replace_vars(self, text: str, guild=None) -> str:
        """Replace placeholders in text."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        replacements = {
            "{server}": guild.name if guild else "Server",
            "{server_name}": guild.name if guild else "Server",
            "{member_count}": str(guild.member_count) if guild else "0",
            "{channel_count}": str(len(guild.channels)) if guild else "0",
            "{role_count}": str(len(guild.roles)) if guild else "0",
            "{date}": now.strftime("%Y-%m-%d"),
            "{time}": now.strftime("%H:%M UTC"),
            "{datetime}": now.strftime("%Y-%m-%d %H:%M UTC"),
            "{boost_count}": str(guild.premium_subscription_count or 0) if guild else "0",
            "{boost_level}": str(guild.premium_tier) if guild else "0",
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        return text
