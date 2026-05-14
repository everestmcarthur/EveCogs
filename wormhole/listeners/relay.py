"""
on_message → relay pipeline and _do_relay core logic.

This is the heart of Wormhole — every message in a network channel flows
through on_message → gate checks → _do_relay → send to all target channels.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional

import discord
from redbot.core import commands

from ..models.permissions import Role
from ..services.emoji import resolve_foreign_emojis, build_emoji_embeds_and_files
from ..ui.views import reply_jump_view
from ..utils import (
    apply_mention_policy,
    build_relay_embed,
    check_attachment_filters,
    check_automod,
    check_filters,
    compact_format,
    info_embed,
    sanitise_mentions,
    truncate,
    warn_embed,
)

log = logging.getLogger("red.evecogs.wormhole")


class RelayListener:
    """Mixin — on_message listener and _do_relay engine."""

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._ready.wait()
        if not message.guild or message.author.bot:
            return
        if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return

        _tracing = message.channel.id in self._trace_channels
        trace: list[str] = []
        if _tracing:
            trace.append("✅ Guild text-channel message from non-bot")

        eff_ch = message.channel.id
        is_thread = isinstance(message.channel, discord.Thread)
        if is_thread:
            eff_ch = message.channel.parent_id

        nets = await self.config.networks()
        net_name = None
        nd = None
        for n, d in nets.items():
            if eff_ch in d.get("channels", []):
                net_name = n
                nd = d
                break
        if not net_name:
            if _tracing:
                trace.append(f"❌ **Channel `{eff_ch}` not in any network**")
                try:
                    await message.channel.send(embed=info_embed("\n".join(trace), title="🔍 Trace"))
                except Exception:
                    pass
            return

        if _tracing:
            trace.append(f"✅ Network: `{net_name}`")

        # ── Gate checks ────────────────────────────────────────────────────

        if is_thread and not nd.get("sync_threads"):
            if _tracing:
                trace.append("❌ **Blocked: thread sync disabled**")
                try:
                    await message.channel.send(embed=info_embed("\n".join(trace), title="🔍 Trace"))
                except Exception:
                    pass
            return

        if nd.get("frozen"):
            if _tracing:
                trace.append("❌ **Blocked: network frozen**")
                try:
                    await message.channel.send(embed=info_embed("\n".join(trace), title="🔍 Trace"))
                except Exception:
                    pass
            return

        # Command filtering
        if message.content:
            try:
                ctx = await self.bot.get_context(message)
                if ctx.valid:
                    if _tracing:
                        trace.append(f"❌ **Blocked: command filter** prefix=`{ctx.prefix!r}` cmd=`{ctx.command}`")
                        try:
                            await message.channel.send(embed=info_embed("\n".join(trace), title="🔍 Trace"))
                        except Exception:
                            pass
                    return
            except Exception:
                pass

        # Mirror channel (receive-only)
        if eff_ch in nd.get("mirror_channels", []):
            return

        # Media-only filter
        if nd.get("media_only"):
            if not message.attachments and not message.stickers and not (
                message.embeds and any(e.type in ("image", "video", "gifv") for e in message.embeds)
            ):
                return

        # NSFW gate
        if nd.get("nsfw_gate") and hasattr(message.channel, "is_nsfw") and message.channel.is_nsfw():
            return

        # Global blocklists
        if message.author.id in await self.config.global_banned_users():
            return
        if message.guild.id in await self.config.global_banned_servers():
            return

        # Per-network blocklists
        if message.author.id in nd.get("banned_users", []):
            return
        if message.author.id in nd.get("muted_users", []):
            return
        if message.guild.id in nd.get("banned_servers", []):
            return
        if message.guild.id in nd.get("muted_servers", []):
            return

        # Rules acceptance gate
        if nd.get("rules_required"):
            accepted = nd.get("rules_accepted", {})
            if str(message.author.id) not in accepted:
                try:
                    prefix = await self.bot.get_prefix(message)
                    if isinstance(prefix, list):
                        prefix = prefix[0]
                    await message.channel.send(
                        embed=warn_embed(
                            f"{message.author.mention}, you must accept the network rules before messaging.\n"
                            f"Use `{prefix}wh accept {net_name}` to view and accept."
                        ),
                        delete_after=15,
                    )
                except Exception:
                    pass
                return

        # Content filters
        if message.content:
            if check_filters(message.content, nd.get("word_filters", []), nd.get("regex_filters", [])):
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=warn_embed(f"{message.author.mention}, blocked by filter."), delete_after=5
                    )
                except Exception:
                    pass
                return

        # Attachment filters
        if message.attachments:
            exts = set(nd.get("blocked_extensions", []))
            reason = check_attachment_filters(message.attachments, exts, nd.get("max_filesize"))
            if reason:
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=warn_embed(f"{message.author.mention}, {reason}"), delete_after=5
                    )
                except Exception:
                    pass
                return

        # Auto-moderation
        am = nd.get("automod", {})
        if am.get("enabled") and message.content:
            if am.get("anti_spam"):
                det = self.dup_detectors.get(net_name)
                if det and det.is_duplicate(net_name, message.author.id, message.content):
                    try:
                        await message.delete()
                        await message.channel.send(embed=warn_embed("Spam detected."), delete_after=5)
                    except Exception:
                        pass
                    await self._log(nd, warn_embed(f"Auto-mod spam: {message.author}"))
                    return
            if am.get("anti_raid"):
                rd = self.raid_detectors.get(net_name)
                if rd and rd.record(net_name, message.author.id):
                    async with self.config.networks() as ns:
                        if net_name in ns:
                            ns[net_name]["frozen"] = True
                    await self._log(nd, warn_embed("🚨 Raid detected! Network auto-frozen."))
                    await self._status(
                        net_name, nd, None,
                        "🚨 **Raid detected — network auto-frozen!** Staff: use `wh set unfreeze` to unfreeze.",
                    )
                    return
            reason = check_automod(message.content, am)
            if reason:
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=warn_embed(f"{message.author.mention}: {reason}"), delete_after=5
                    )
                except Exception:
                    pass
                await self._log(nd, warn_embed(f"Auto-mod: {reason} — {message.author}"))
                return

        # Rate limit
        bucket = self.cooldowns.get(net_name)
        if bucket and bucket.is_rate_limited(message.author.id, net_name):
            try:
                await message.add_reaction("🕐")
            except Exception:
                pass
            return

        # Slowmode
        sm = nd.get("slowmode", 0)
        if sm > 0:
            last = self.slowmode_tracker.get(net_name, {}).get(message.author.id, 0)
            if time.monotonic() - last < sm:
                try:
                    await message.add_reaction("🐌")
                except Exception:
                    pass
                return
            self.slowmode_tracker.setdefault(net_name, {})[message.author.id] = time.monotonic()

        # Relay delay
        delay = nd.get("relay_delay", 0)
        if delay > 0:
            await asyncio.sleep(min(delay, 30))

        # AFK system
        try:
            await self._check_afk(net_name, nd, message)
        except Exception as exc:
            log.debug("AFK check error (relay continues): %s", exc)

        # Auto-responses
        try:
            await self._check_auto_responses(net_name, nd, message)
        except Exception as exc:
            log.debug("Auto-response error (relay continues): %s", exc)

        # ── Relay ──────────────────────────────────────────────────────────
        if _tracing:
            trace.append("✅ All gate checks passed — calling _do_relay")
        try:
            await self._do_relay(net_name, nd, nets, message, eff_ch)
            if _tracing:
                trace.append("✅ **_do_relay completed successfully**")
                try:
                    await message.channel.send(embed=info_embed("\n".join(trace), title="🔍 Trace — RELAYED"))
                except Exception:
                    pass
        except Exception as exc:
            log.error("Relay engine error net=%s ch=%s: %s", net_name, message.channel.id, exc, exc_info=True)
            if _tracing:
                trace.append(f"❌ **_do_relay EXCEPTION: `{exc}`**")
                try:
                    await message.channel.send(embed=info_embed("\n".join(trace), title="🔍 Trace — ERROR"))
                except Exception:
                    pass

    async def _do_relay(
        self, net_name: str, nd: dict, nets: dict, message: discord.Message, eff_ch: int
    ) -> None:
        """Core relay logic — build payload, send to all target channels."""

        relay_mode = nd.get("relay_mode", "webhook")
        nick = nd.get("server_nicknames", {}).get(str(message.guild.id))

        # ── Mention policy ─────────────────────────────────────────────────
        mp = nd.get("mention_policy", {})
        server_overrides = nd.get("server_mention_overrides", {}).get(str(message.guild.id))
        active_policy = server_overrides if server_overrides else mp
        exempt = nd.get("mention_exempt_users", [])
        optouts = set(nd.get("mention_optout_users", []))
        if active_policy:
            content = apply_mention_policy(
                message.content or "", active_policy, message.author.id, exempt, optouts
            )
        else:
            mc = nd.get("mention_control", {})
            content = sanitise_mentions(message.content or "", mc)

        # ── Identity ───────────────────────────────────────────────────────
        is_anon = nd.get("anonymous", False)
        if is_anon:
            anon_name = self._anon_name(nd, message.author.id)
            avatar = self._anon_avatar(message.author.id)
            uname = anon_name
        else:
            avatar = self._avatar(message, nd.get("image_mode", "user"), nd.get("custom_icon"))
            uname = self._name(message, nd.get("name_mode", "both"), nd.get("custom_name"), nick)

        user_colour = nd.get("user_colours", {}).get(str(message.author.id))

        # ── Reply context ──────────────────────────────────────────────────
        reply_jump_urls: Dict[int, str] = {}
        reply_fallback_url: Optional[str] = None
        if nd.get("sync_replies") and message.reference and message.reference.message_id:
            try:
                ref = message.reference.cached_message or await message.channel.fetch_message(
                    message.reference.message_id
                )
                ref_name = self._anon_name(nd, ref.author.id) if is_anon else ref.author.display_name
                preview = truncate(ref.content, 100) if ref.content else "*[attachment]*"
                content = f"> **↩ {ref_name}:** {preview}\n{content}"

                if ref.guild:
                    reply_fallback_url = (
                        f"https://discord.com/channels/{ref.guild.id}/{ref.channel.id}/{ref.id}"
                    )
                    orig_ref_id = self.msg_map.get_original(net_name, ref.id)
                    ref_relayed = (
                        self.msg_map.forward.get(net_name, {}).get(orig_ref_id, {})
                        if orig_ref_id
                        else self.msg_map.forward.get(net_name, {}).get(ref.id, {})
                    )
                    for cid, mid in ref_relayed.items():
                        target_ch = self.bot.get_channel(cid)
                        if target_ch and target_ch.guild:
                            reply_jump_urls[cid] = (
                                f"https://discord.com/channels/{target_ch.guild.id}/{cid}/{mid}"
                            )
                    if orig_ref_id:
                        relayed_ch_ids = set(ref_relayed.keys())
                        for net_ch_id in nd.get("channels", []):
                            if net_ch_id not in relayed_ch_ids and net_ch_id not in reply_jump_urls:
                                net_ch = self.bot.get_channel(net_ch_id)
                                if net_ch and net_ch.guild:
                                    reply_jump_urls[net_ch_id] = (
                                        f"https://discord.com/channels/{net_ch.guild.id}/{net_ch_id}/{orig_ref_id}"
                                    )
                    reply_jump_urls.setdefault(ref.channel.id, reply_fallback_url)
            except Exception:
                content = f"> ↩ *[reply]*\n{content}"

        # ── Stickers ───────────────────────────────────────────────────────
        if nd.get("sync_stickers") and message.stickers:
            sl = [f"[Sticker: {s.name}]({s.url})" for s in message.stickers]
            content = (content + "\n" if content else "") + "\n".join(sl)

        # ── Forward embeds ─────────────────────────────────────────────────
        extra_embeds: list[discord.Embed] = []
        if nd.get("forward_embeds") and message.embeds:
            extra_embeds = [e for e in message.embeds if e.type == "rich"]

        # ── Resolve foreign emojis ─────────────────────────────────────────
        emoji_img_data: list[tuple[str, bytes]] = []
        if content:
            content, emoji_img_data = await resolve_foreign_emojis(self.bot, content)

        # ── Build target list ──────────────────────────────────────────────
        relay_targets = [cid for cid in nd["channels"] if cid != eff_ch]
        for bridge_net in nd.get("bridge_to", []):
            bd = nets.get(bridge_net)
            if bd and not bd.get("frozen"):
                relay_targets.extend(bd.get("channels", []))

        # ── Send to each target channel ────────────────────────────────────
        mapping: Dict[int, int] = {}
        for ch_id in relay_targets:
            if ch_id == eff_ch:
                continue
            ch = self.bot.get_channel(ch_id)
            if not ch:
                continue
            ch_mode = self._get_override(nd, ch_id, "relay_mode") or relay_mode

            # Reply jump button
            jump_url = reply_jump_urls.get(ch_id) or reply_fallback_url
            _reply_view = reply_jump_view(jump_url) if jump_url else None
            _view_kw = {"view": _reply_view} if _reply_view else {}

            # Fresh emoji embeds/files (File objects are single-use)
            emoji_embeds, emoji_files = build_emoji_embeds_and_files(emoji_img_data)

            try:
                sent_msg = None
                if ch_mode == "webhook":
                    sent_msg = await self._relay_webhook(
                        ch, message, content, uname, avatar, extra_embeds,
                        emoji_embeds, emoji_files, emoji_img_data, _view_kw, nick, nd,
                    )
                elif ch_mode == "embed":
                    ee, ef = build_emoji_embeds_and_files(emoji_img_data)
                    em = build_relay_embed(message, nick, user_colour or nd.get("colour"))
                    all_embeds = [em] + (extra_embeds or []) + ee
                    sent_msg = await ch.send(embeds=all_embeds[:10], files=ef or None, **_view_kw)
                elif ch_mode == "compact":
                    g = nick or message.guild.name
                    display = anon_name if is_anon else message.author.display_name
                    files = []
                    for a in message.attachments:
                        try:
                            files.append(await a.to_file())
                        except Exception:
                            pass
                    ce, cf = build_emoji_embeds_and_files(emoji_img_data)
                    files.extend(cf)
                    sent_msg = await ch.send(
                        content=compact_format(g, display, content),
                        files=files or None,
                        embeds=ce[:10] or None,
                        **_view_kw,
                    )

                if sent_msg:
                    mapping[ch_id] = sent_msg.id
                    if nd.get("ephemeral_delay", 0) > 0:
                        await self._schedule_ephemeral_delete(sent_msg, nd["ephemeral_delay"])

            except Exception as exc:
                log.error("Relay fail ch=%s net=%s: %s", ch_id, net_name, exc, exc_info=True)

        if mapping:
            self.msg_map.add(net_name, message.id, mapping)

        # Stats + profile + analytics
        async with self.config.networks() as ns:
            if net_name in ns:
                ns[net_name]["total_messages"] = ns[net_name].get("total_messages", 0) + 1
        await self._update_profile(net_name, message.author, message.guild.id)
        await self._record_analytics(net_name, message.author.id)

        # DM relay + highlights
        await self._relay_to_dm_subs(net_name, nd, message)
        await self._check_highlights(net_name, nd, message.content, message.author.id)

    async def _relay_webhook(
        self, ch, message, content, uname, avatar, extra_embeds,
        emoji_embeds, emoji_files, emoji_img_data, view_kw, nick, nd,
    ) -> Optional[discord.Message]:
        """Send via webhook with automatic retry/fallback."""
        files = []
        for a in message.attachments:
            try:
                files.append(await a.to_file())
            except Exception:
                pass
        files.extend(emoji_files)
        all_embeds = (extra_embeds or []) + emoji_embeds
        send_content = content if content else None
        if not send_content and not files and not all_embeds:
            send_content = "*[empty message]*"

        try:
            wh = await self._wh(ch)
            return await wh.send(
                content=send_content,
                username=truncate(uname, 80),
                avatar_url=avatar,
                files=files or discord.utils.MISSING,
                embeds=all_embeds[:10] or discord.utils.MISSING,
                wait=True,
                **view_kw,
            )
        except (discord.NotFound, discord.InvalidData):
            # Webhook stale — retry with fresh one
            try:
                wh = await self._wh(ch, force_refresh=True)
                files2 = []
                for a in message.attachments:
                    try:
                        files2.append(await a.to_file())
                    except Exception:
                        pass
                ee2, ef2 = build_emoji_embeds_and_files(emoji_img_data)
                files2.extend(ef2)
                all_embeds2 = (extra_embeds or []) + ee2
                send_content2 = content if content else None
                if not send_content2 and not files2 and not all_embeds2:
                    send_content2 = "*[empty message]*"
                return await wh.send(
                    content=send_content2,
                    username=truncate(uname, 80),
                    avatar_url=avatar,
                    files=files2 or discord.utils.MISSING,
                    embeds=all_embeds2[:10] or discord.utils.MISSING,
                    wait=True,
                    **view_kw,
                )
            except Exception:
                log.warning("Webhook retry failed for %s, falling back to embed", ch.id)
                em = build_relay_embed(message, nick, nd.get("colour"))
                return await ch.send(embeds=[em] + (extra_embeds or [])[:9], **view_kw)
        except discord.Forbidden:
            log.warning("No webhook perms in %s, falling back to embed", ch.id)
            em = build_relay_embed(message, nick, nd.get("colour"))
            return await ch.send(embeds=[em] + (extra_embeds or [])[:9], **view_kw)
