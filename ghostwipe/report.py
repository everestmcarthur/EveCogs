"""
GhostWipe HTML report generator.

Builds a single self-contained HTML file (no external resources, no required
JavaScript) that lets a moderator browse every message GhostWipe deleted for
a departing member. All content — stats, avatar, channel list, and every
message — is rendered server-side directly into the HTML/CSS, using a pure
CSS radio/label technique for channel switching. This way the report
displays correctly even in minimal viewers that don't execute scripts or
load remote network resources (a common failure mode for local file://
HTML viewers). A small script is layered on top purely as a progressive
enhancement for live search filtering; if it never runs, everything is
still fully visible via the CSS tab switcher.
"""

from __future__ import annotations

import html as html_lib
from typing import Any, Dict, List, Optional

STYLE = r"""
:root {
  --bg: #0e0f13;
  --bg-alt: #15171d;
  --panel: #1a1d24;
  --panel-alt: #20232b;
  --border: #2a2e38;
  --text: #e7e9ee;
  --text-dim: #9096a3;
  --text-faint: #5b6270;
  --accent: #8b5cf6;
  --accent-soft: rgba(139, 92, 246, 0.15);
  --danger: #f04747;
  --warn: #faa61a;
  --ok: #3ba55d;
  --radius: 10px;
  --shadow: 0 8px 24px rgba(0,0,0,0.35);
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f4f5f8; --bg-alt: #ffffff; --panel: #ffffff; --panel-alt: #f0f1f5;
    --border: #e1e3e9; --text: #1a1d24; --text-dim: #565c6a; --text-faint: #8b909c;
    --accent: #7c3aed; --accent-soft: rgba(124, 58, 237, 0.10); --shadow: 0 8px 24px rgba(0,0,0,0.08);
  }
}
:root[data-theme="dark"] {
  --bg: #0e0f13; --bg-alt: #15171d; --panel: #1a1d24; --panel-alt: #20232b;
  --border: #2a2e38; --text: #e7e9ee; --text-dim: #9096a3; --text-faint: #5b6270;
  --accent: #8b5cf6; --accent-soft: rgba(139, 92, 246, 0.15); --shadow: 0 8px 24px rgba(0,0,0,0.35);
}
:root[data-theme="light"] {
  --bg: #f4f5f8; --bg-alt: #ffffff; --panel: #ffffff; --panel-alt: #f0f1f5;
  --border: #e1e3e9; --text: #1a1d24; --text-dim: #565c6a; --text-faint: #8b909c;
  --accent: #7c3aed; --accent-soft: rgba(124, 58, 237, 0.10); --shadow: 0 8px 24px rgba(0,0,0,0.08);
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; min-height: 100%;
  background: var(--bg); color: var(--text);
  font-family: "gg sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 14px;
}
#app { display: flex; flex-direction: column; min-height: 100vh; }

/* Header */
#header {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 20px; background: var(--bg-alt);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
  flex-wrap: wrap;
}
.avatar, .avatar-fallback {
  width: 48px; height: 48px; border-radius: 50%; flex-shrink: 0;
  border: 2px solid var(--border); background: var(--panel-alt);
}
.avatar-fallback {
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 18px; color: var(--accent);
}
#header .id-block { min-width: 180px; }
#header .username { font-weight: 700; font-size: 16px; }
#header .userid { color: var(--text-faint); font-size: 12px; }
.badge {
  display: inline-block; padding: 3px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase;
}
.badge-left { background: rgba(120,120,130,0.18); color: #b7bcc7; }
.badge-kicked { background: rgba(250,166,26,0.16); color: var(--warn); }
.badge-banned { background: rgba(240,71,71,0.16); color: var(--danger); }
.badge-manual { background: var(--accent-soft); color: var(--accent); }
.badge-dryrun { background: var(--accent-soft); color: var(--accent); margin-left: 6px; }

#header .stats { display: flex; gap: 22px; margin-left: auto; flex-wrap: wrap; }
#header .stat { text-align: center; }
#header .stat .num { font-size: 20px; font-weight: 700; }
#header .stat .lbl { font-size: 10px; color: var(--text-faint); text-transform: uppercase; letter-spacing: .05em; }
#header .meta-row { width: 100%; font-size: 12px; color: var(--text-dim); margin-top: 2px; }

/* Body layout */
#body { flex: 1; display: flex; min-height: 0; }

#sidebar {
  width: 280px; flex-shrink: 0; background: var(--bg-alt);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column; min-height: 0;
}
#sidebar .sidebar-title {
  padding: 12px 16px 6px; font-size: 11px; text-transform: uppercase;
  letter-spacing: .06em; color: var(--text-faint); font-weight: 700;
}
#channel-list { list-style: none; margin: 0; padding: 4px 8px; overflow-y: auto; flex: 1; }
.ch-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 2px;
  color: var(--text-dim); transition: background .1s ease;
}
.ch-item:hover { background: var(--panel-alt); color: var(--text); }
.ch-item .ch-name { display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-item .ch-icon { opacity: .6; flex-shrink: 0; }
.ch-item .ch-count {
  background: var(--panel-alt); color: var(--text-faint); font-size: 11px;
  font-weight: 700; padding: 1px 7px; border-radius: 999px; flex-shrink: 0;
}
.ch-item.skipped { opacity: .6; }
.ch-item .skip-tag { font-size: 10px; color: var(--danger); }

#search-wrap { padding: 10px; border-top: 1px solid var(--border); flex-shrink: 0; }
#search-wrap input {
  width: 100%; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--panel-alt); color: var(--text); font-size: 13px;
}
#search-wrap input:focus { outline: 2px solid var(--accent); }
.js-only-note { display: none; font-size: 10px; color: var(--text-faint); margin-top: 6px; }

/* Main pane */
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.panel { display: none; flex-direction: column; flex: 1; min-height: 0; }
.panel-header {
  padding: 12px 20px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}
.panel-header h2 { margin: 0; font-size: 15px; font-weight: 700; }
.count-pill {
  background: var(--panel-alt); border: 1px solid var(--border); border-radius: 999px;
  padding: 2px 10px; font-size: 12px; color: var(--text-dim);
}
.panel-body { flex: 1; overflow-y: auto; padding: 16px 20px; }
.msg {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px 14px; margin-bottom: 10px;
}
.msg.hidden-by-search { display: none; }
.msg .msg-top { display: flex; justify-content: space-between; color: var(--text-faint); font-size: 11px; margin-bottom: 6px; }
.msg .msg-content { white-space: pre-wrap; word-break: break-word; line-height: 1.45; }
.msg .msg-content.redacted { color: var(--text-faint); font-style: italic; }
.attachments { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.attachment-chip {
  display: flex; align-items: center; gap: 6px; background: var(--panel-alt);
  border: 1px solid var(--border); border-radius: 8px; padding: 5px 10px; font-size: 12px;
  color: var(--text-dim); text-decoration: none; max-width: 260px;
}
.attachment-chip:hover { border-color: var(--accent); color: var(--text); }
.attachment-img { max-width: 320px; max-height: 240px; border-radius: 8px; margin-top: 8px; display: block; border: 1px solid var(--border); }
.sticker-chip { background: var(--accent-soft); color: var(--accent); border-radius: 8px; padding: 4px 9px; font-size: 12px; margin-top: 6px; display: inline-block; }
.empty-state { text-align: center; color: var(--text-faint); padding: 60px 20px; }
.skip-banner {
  background: rgba(250,166,26,0.10); border: 1px solid rgba(250,166,26,0.3); color: var(--warn);
  border-radius: var(--radius); padding: 14px 16px; margin-bottom: 12px; font-size: 13px;
}
#footer {
  padding: 8px 20px; border-top: 1px solid var(--border); color: var(--text-faint);
  font-size: 11px; text-align: center; flex-shrink: 0;
}
::-webkit-scrollbar { width: 10px; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 6px; }
::-webkit-scrollbar-track { background: transparent; }
@media (max-width: 720px) {
  #sidebar { width: 200px; }
  #header .stats { gap: 12px; }
}
"""

SEARCH_SCRIPT = r"""
(function () {
  var box = document.getElementById('search');
  var note = document.getElementById('js-only-note');
  if (!box) return;
  if (note) note.style.display = 'block';
  box.addEventListener('input', function () {
    var term = box.value.toLowerCase();
    var msgs = document.querySelectorAll('.msg[data-content]');
    for (var i = 0; i < msgs.length; i++) {
      var el = msgs[i];
      var match = !term || el.getAttribute('data-content').indexOf(term) !== -1;
      el.classList.toggle('hidden-by-search', !match);
    }
  });
})();
"""


def _badge_class(reason: str) -> str:
    return {
        "left": "badge-left",
        "kicked": "badge-kicked",
        "banned": "badge-banned",
        "manual": "badge-manual",
    }.get(reason, "badge-left")


def _badge_label(reason: str) -> str:
    return {
        "left": "Left",
        "kicked": "Kicked",
        "banned": "Banned",
        "manual": "Manual",
    }.get(reason, reason.title())


CHANNEL_ICON = {"text": "#", "thread": "\U0001F9F5", "voice": "\U0001F50A"}


def _esc(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


def _render_message(msg: Dict[str, Any], redact: bool) -> str:
    content = msg.get("content") or ""
    search_key = _esc(content.lower()) if not redact else ""
    parts = [f'<div class="msg" data-content="{search_key}">']
    parts.append(
        f'<div class="msg-top"><span>{_esc(msg.get("timestamp", ""))}</span>'
        f'<span>#{_esc(msg.get("id", ""))}</span></div>'
    )
    if redact:
        parts.append('<div class="msg-content redacted">[content redacted by server configuration]</div>')
    else:
        text = content if content else ("" if msg.get("attachments") else "[no text content]")
        parts.append(f'<div class="msg-content">{_esc(text)}</div>')

        attachments = msg.get("attachments") or []
        if attachments:
            parts.append('<div class="attachments">')
            for att in attachments:
                if att.get("is_image"):
                    parts.append(
                        f'<img class="attachment-img" src="{_esc(att.get("url", ""))}" '
                        f'alt="{_esc(att.get("filename", "image"))}" loading="lazy" '
                        f'onerror="this.style.display=\'none\'">'
                    )
                else:
                    size = att.get("size", "")
                    parts.append(
                        f'<a class="attachment-chip" href="{_esc(att.get("url", ""))}" '
                        f'target="_blank" rel="noopener noreferrer">'
                        f'\U0001F4CE {_esc(att.get("filename", "file"))}'
                        f'{f" ({_esc(size)})" if size else ""}</a>'
                    )
            parts.append("</div>")

        for sticker in msg.get("stickers") or []:
            parts.append(f'<span class="sticker-chip">✨ {_esc(sticker)}</span>')

    parts.append("</div>")
    return "".join(parts)


def _render_channel_panel(channel: Dict[str, Any], redact: bool) -> str:
    cid = _esc(channel["id"])
    icon = CHANNEL_ICON.get(channel.get("type"), "#")
    name = _esc(channel.get("name", cid))
    count = channel.get("message_count", 0)

    body_parts = []
    if channel.get("skipped"):
        reason = _esc(channel.get("skip_reason") or "unknown reason")
        body_parts.append(f'<div class="skip-banner">This channel was skipped: {reason}</div>')
    else:
        messages = channel.get("messages") or []
        if not messages:
            body_parts.append('<div class="empty-state">No messages recorded for this channel.</div>')
        else:
            for msg in messages:
                body_parts.append(_render_message(msg, redact))

    return (
        f'<div class="panel" id="panel-{cid}">'
        f'<div class="panel-header"><h2>{icon} {name}</h2>'
        f'<span class="count-pill">{count} message{"s" if count != 1 else ""}</span></div>'
        f'<div class="panel-body">{"".join(body_parts)}</div>'
        f"</div>"
    )


def _render_sidebar_item(channel: Dict[str, Any]) -> str:
    cid = _esc(channel["id"])
    icon = CHANNEL_ICON.get(channel.get("type"), "#")
    name = _esc(channel.get("name", cid))
    if channel.get("skipped"):
        right = '<span class="skip-tag">skipped</span>'
        cls = "ch-item skipped"
    else:
        count = channel.get("message_count", 0)
        right = f'<span class="ch-count">{count}</span>'
        cls = "ch-item"
    return (
        f'<label class="{cls}" for="tab-{cid}">'
        f'<span class="ch-name"><span class="ch-icon">{icon}</span>{name}</span>{right}'
        f"</label>"
    )


def generate_report_html(
    *,
    guild_name: str,
    member_name: str,
    member_id: int,
    reason: str,
    event_time_str: str,
    channels: List[Dict[str, Any]],
    avatar_data_uri: Optional[str] = None,
    moderator: str = None,
    mod_reason: str = None,
    dry_run: bool = False,
    reveal_content: bool = True,
    version: str = "1.0.0",
    generated_at: str = "",
) -> str:
    """Build the standalone HTML report string.

    Everything (stats, avatar, channel list, messages) is rendered directly
    into the markup here in Python — there is no client-side rendering step,
    so the report displays fully correctly even with JavaScript disabled or
    blocked. ``channels`` is a list of dicts shaped like:
        {
            "id": str, "name": str, "type": "text"|"thread"|"voice",
            "skipped": bool, "skip_reason": str | None,
            "message_count": int,
            "messages": [
                {"id": str, "timestamp": str, "content": str,
                 "attachments": [{"filename", "url", "size", "is_image"}],
                 "stickers": [str]},
                ...
            ],
        }
    """
    total_deleted = sum(c["message_count"] for c in channels if not c.get("skipped"))
    channels_affected = sum(1 for c in channels if not c.get("skipped") and c["message_count"] > 0)
    channels_skipped = sum(1 for c in channels if c.get("skipped"))

    # Only list channels that are actually relevant to this event — a full
    # server-wide sidebar of untouched channels adds nothing but clutter.
    # Affected channels (by message count, descending) come first; skipped ones last.
    relevant = [c for c in channels if c.get("skipped") or c.get("message_count", 0) > 0]
    relevant.sort(key=lambda c: (c.get("skipped", False), -c.get("message_count", 0)))

    meta_bits = [f"Server: {html_lib.escape(guild_name)}"]
    if moderator:
        meta_bits.append(f"By: {html_lib.escape(moderator)}")
    if mod_reason:
        meta_bits.append(f"Reason: {html_lib.escape(mod_reason)}")
    meta_line = "  •  ".join(meta_bits)

    if avatar_data_uri:
        avatar_html = f'<img class="avatar" src="{_esc(avatar_data_uri)}" alt="avatar">'
    else:
        initial = (member_name.strip()[:1] or "?").upper()
        avatar_html = f'<div class="avatar-fallback">{_esc(initial)}</div>'

    dryrun_badge = ' <span class="badge badge-dryrun">Dry Run</span>' if dry_run else ""

    radios = []
    sidebar_items = []
    panels = []
    for i, channel in enumerate(relevant):
        cid = _esc(channel["id"])
        checked = " checked" if i == 0 else ""
        radios.append(f'<input type="radio" name="chantabs" id="tab-{cid}" class="tab-radio"{checked}>')
        sidebar_items.append(_render_sidebar_item(channel))
        panels.append(_render_channel_panel(channel, not reveal_content))

    # The radio inputs are siblings of #app (both direct children of <body>) —
    # #body/#main/#sidebar are all nested *inside* #app, not siblings of the
    # radios themselves, so the `~` combinator has to anchor on #app.
    tab_css_rules = []
    for channel in relevant:
        cid = _esc(channel["id"])
        tab_css_rules.append(
            f'#tab-{cid}:checked ~ #app #main #panel-{cid} {{ display: flex; }}\n'
            f'#tab-{cid}:checked ~ #app #sidebar label[for="tab-{cid}"] {{ '
            f'background: var(--accent-soft); color: var(--text); }}'
        )

    if relevant:
        main_content = "".join(panels)
        sidebar_content = "".join(sidebar_items)
    else:
        main_content = '<div class="empty-state">Nothing was deleted for this event.</div>'
        sidebar_content = '<div class="empty-state" style="padding:20px 10px;">No channels affected.</div>'

    title = f"GhostWipe Report — {html_lib.escape(member_name)}"

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{STYLE}
{"".join(tab_css_rules)}
</style>
</head>
<body>
{"".join(radios)}
<div id="app">
  <div id="header">
    {avatar_html}
    <div class="id-block">
      <div class="username">{_esc(member_name)} <span class="badge {_badge_class(reason)}">{_badge_label(reason)}</span>{dryrun_badge}</div>
      <div class="userid">ID: {member_id}</div>
    </div>
    <div class="stats">
      <div class="stat"><div class="num">{total_deleted}</div><div class="lbl">Deleted</div></div>
      <div class="stat"><div class="num">{channels_affected}</div><div class="lbl">Channels</div></div>
      <div class="stat"><div class="num">{channels_skipped}</div><div class="lbl">Skipped</div></div>
    </div>
    <div class="meta-row">{meta_line}</div>
  </div>
  <div id="body">
    <div id="sidebar">
      <div class="sidebar-title">Channels</div>
      <div id="channel-list">
        {sidebar_content}
      </div>
      <div id="search-wrap">
        <input id="search" type="text" placeholder="Search message content...">
        <div id="js-only-note" class="js-only-note">Live filtering active</div>
      </div>
    </div>
    <div id="main">
      {main_content}
    </div>
  </div>
  <div id="footer">Generated by GhostWipe {html_lib.escape(version)} &middot; {html_lib.escape(generated_at or event_time_str)}</div>
</div>
<script>{SEARCH_SCRIPT}</script>
</body>
</html>
"""
    return doc

