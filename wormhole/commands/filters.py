"""Filter commands — word/regex filters, automod configuration, attachment filters."""

from __future__ import annotations

import discord
from redbot.core import commands

from ..models.permissions import Role, requires_role
from ..utils import ok_embed, err_embed, info_embed, COLOUR_INFO


class FilterCommands:
    """Mixin — content filters and automod configuration."""

    @commands.group(name="wh-filter", aliases=["whfilter"], invoke_without_command=True)
    async def wh_filter(self, ctx: commands.Context) -> None:
        """Manage content filters and automod."""
        await ctx.send_help(ctx.command)

    # ── Word filters ───────────────────────────────────────────────────────

    @wh_filter.command(name="addword")
    @requires_role(Role.MODERATOR)
    async def wh_filter_addword(self, ctx: commands.Context, name: str, *, word: str) -> None:
        """Add a word to the filter list."""
        async with self.config.networks() as ns:
            wf = ns[name].setdefault("word_filters", [])
            if word.lower() not in [w.lower() for w in wf]:
                wf.append(word)
        await ctx.send(embed=ok_embed(f"Word `{word}` added to filters for `{name}`."))
        await self._audit(name, "filter_add", str(ctx.author), word)

    @wh_filter.command(name="rmword")
    @requires_role(Role.MODERATOR)
    async def wh_filter_rmword(self, ctx: commands.Context, name: str, *, word: str) -> None:
        """Remove a word from the filter list."""
        async with self.config.networks() as ns:
            wf = ns[name].get("word_filters", [])
            ns[name]["word_filters"] = [w for w in wf if w.lower() != word.lower()]
        await ctx.send(embed=ok_embed(f"Word `{word}` removed from filters for `{name}`."))

    @wh_filter.command(name="addregex")
    @requires_role(Role.ADMIN)
    async def wh_filter_addregex(self, ctx: commands.Context, name: str, *, pattern: str) -> None:
        """Add a regex pattern to the filter list."""
        import re
        try:
            re.compile(pattern)
        except re.error as e:
            return await ctx.send(embed=err_embed(f"Invalid regex: {e}"))
        async with self.config.networks() as ns:
            rf = ns[name].setdefault("regex_filters", [])
            if pattern not in rf:
                rf.append(pattern)
        await ctx.send(embed=ok_embed(f"Regex `{pattern}` added to filters for `{name}`."))
        await self._audit(name, "regex_add", str(ctx.author), pattern)

    @wh_filter.command(name="rmregex")
    @requires_role(Role.ADMIN)
    async def wh_filter_rmregex(self, ctx: commands.Context, name: str, *, pattern: str) -> None:
        """Remove a regex pattern from the filter list."""
        async with self.config.networks() as ns:
            rf = ns[name].get("regex_filters", [])
            if pattern in rf:
                rf.remove(pattern)
        await ctx.send(embed=ok_embed(f"Regex removed from filters for `{name}`."))

    @wh_filter.command(name="list")
    @requires_role(Role.HELPER)
    async def wh_filter_list(self, ctx: commands.Context, name: str) -> None:
        """List all active filters."""
        nd = await self._net(name)
        if not nd:
            return await ctx.send(embed=err_embed(f"Network `{name}` not found."))
        words = nd.get("word_filters", [])
        regexes = nd.get("regex_filters", [])
        lines = []
        if words:
            lines.append("**Word Filters:**")
            for w in words:
                lines.append(f"  • `{w}`")
        if regexes:
            lines.append("**Regex Filters:**")
            for r in regexes:
                lines.append(f"  • `{r}`")
        if not lines:
            lines.append("No filters configured.")
        await ctx.send(embed=info_embed("\n".join(lines), title=f"🔍 Filters — {name}"))

    # ── Automod ────────────────────────────────────────────────────────────

    @wh_filter.command(name="automod")
    @requires_role(Role.ADMIN)
    async def wh_filter_automod(self, ctx: commands.Context, name: str, feature: str, enabled: bool) -> None:
        """Toggle automod features.

        Features: ``spam``, ``invite``, ``link``, ``caps``, ``mention_spam``,
        ``zalgo``, ``spoiler``, ``emote_spam``, ``newline_spam``, ``raid``
        """
        key_map = {
            "spam": "anti_spam", "invite": "anti_invite",
            "link": "anti_link", "caps": "anti_caps",
            "mention_spam": "anti_mention_spam", "zalgo": "anti_zalgo",
            "spoiler": "anti_spoiler", "emote_spam": "anti_emote_spam",
            "newline_spam": "anti_newline_spam", "raid": "anti_raid",
        }
        if feature not in key_map:
            return await ctx.send(embed=err_embed(f"Unknown feature. Options: {', '.join(key_map)}"))
        async with self.config.networks() as ns:
            am = ns[name].setdefault("automod", {})
            am[key_map[feature]] = enabled
            am["enabled"] = any(v for k, v in am.items() if k.startswith("anti_"))
        await ctx.send(embed=ok_embed(f"Automod `{feature}` {'enabled' if enabled else 'disabled'} for `{name}`."))
        await self._audit(name, f"automod_{feature}", str(ctx.author), details=str(enabled))

        # Update detectors
        if feature == "spam":
            if enabled:
                nd = await self._net(name)
                am = nd.get("automod", {})
                from ..utils import DuplicateDetector
                self.dup_detectors[name] = DuplicateDetector(am.get("spam_window", 30.0), am.get("spam_threshold", 3))
            else:
                self.dup_detectors.pop(name, None)
        elif feature == "raid":
            if enabled:
                nd = await self._net(name)
                am = nd.get("automod", {})
                from ..utils import RaidDetector
                self.raid_detectors[name] = RaidDetector(am.get("raid_window", 60.0), am.get("raid_threshold", 10))
            else:
                self.raid_detectors.pop(name, None)

    @wh_filter.command(name="automod-set")
    @requires_role(Role.ADMIN)
    async def wh_filter_automod_set(self, ctx: commands.Context, name: str, key: str, value: str) -> None:
        """Set an automod parameter.

        Keys: ``max_mentions``, ``caps_threshold``, ``spam_window``, ``spam_threshold``,
        ``max_emotes``, ``max_newlines``, ``raid_window``, ``raid_threshold``
        """
        valid_keys = {
            "max_mentions", "caps_threshold", "spam_window", "spam_threshold",
            "max_emotes", "max_newlines", "raid_window", "raid_threshold",
        }
        if key not in valid_keys:
            return await ctx.send(embed=err_embed(f"Unknown key. Options: {', '.join(valid_keys)}"))
        try:
            parsed = float(value) if "." in value else int(value)
        except ValueError:
            return await ctx.send(embed=err_embed("Value must be a number."))
        async with self.config.networks() as ns:
            ns[name].setdefault("automod", {})[key] = parsed
        await ctx.send(embed=ok_embed(f"Automod `{key}` set to `{parsed}` for `{name}`."))

    # ── Attachment filters ─────────────────────────────────────────────────

    @wh_filter.command(name="blockext")
    @requires_role(Role.ADMIN)
    async def wh_filter_blockext(self, ctx: commands.Context, name: str, ext: str) -> None:
        """Block a file extension (e.g. ``.exe``)."""
        if not ext.startswith("."):
            ext = "." + ext
        async with self.config.networks() as ns:
            exts = ns[name].setdefault("blocked_extensions", [])
            if ext not in exts:
                exts.append(ext)
        await ctx.send(embed=ok_embed(f"Extension `{ext}` blocked for `{name}`."))

    @wh_filter.command(name="unblockext")
    @requires_role(Role.ADMIN)
    async def wh_filter_unblockext(self, ctx: commands.Context, name: str, ext: str) -> None:
        """Unblock a file extension."""
        if not ext.startswith("."):
            ext = "." + ext
        async with self.config.networks() as ns:
            exts = ns[name].get("blocked_extensions", [])
            if ext in exts:
                exts.remove(ext)
        await ctx.send(embed=ok_embed(f"Extension `{ext}` unblocked for `{name}`."))

    @wh_filter.command(name="maxfilesize")
    @requires_role(Role.ADMIN)
    async def wh_filter_maxfilesize(self, ctx: commands.Context, name: str, mb: float = 0) -> None:
        """Set max file size in MB (0 to disable)."""
        async with self.config.networks() as ns:
            ns[name]["max_filesize"] = int(mb * 1024 * 1024) if mb > 0 else None
        await ctx.send(embed=ok_embed(f"Max file size {'set to ' + str(mb) + ' MB' if mb > 0 else 'disabled'} for `{name}`."))
