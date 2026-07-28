"""
GhostWipe HTML report generator.

Builds a single self-contained HTML file (no external resources) that lets a
moderator browse every message GhostWipe deleted for a departing member,
switching between channels, searching content, and inspecting attachments.
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, List

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__PAGE_TITLE__</title>
<style>
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
    --bg: #f4f5f8;
    --bg-alt: #ffffff;
    --panel: #ffffff;
    --panel-alt: #f0f1f5;
    --border: #e1e3e9;
    --text: #1a1d24;
    --text-dim: #565c6a;
    --text-faint: #8b909c;
    --accent: #7c3aed;
    --accent-soft: rgba(124, 58, 237, 0.10);
    --shadow: 0 8px 24px rgba(0,0,0,0.08);
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
  margin: 0; padding: 0; height: 100%;
  background: var(--bg); color: var(--text);
  font-family: "gg sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 14px;
  overflow: hidden;
}
#app { display: flex; flex-direction: column; height: 100vh; }

/* Header */
#header {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 20px; background: var(--bg-alt);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
  flex-wrap: wrap;
}
#header img.avatar {
  width: 48px; height: 48px; border-radius: 50%; flex-shrink: 0;
  border: 2px solid var(--border); background: var(--panel-alt);
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
#channel-list li {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 2px;
  color: var(--text-dim); transition: background .1s ease;
}
#channel-list li:hover { background: var(--panel-alt); color: var(--text); }
#channel-list li.active { background: var(--accent-soft); color: var(--text); }
#channel-list li .ch-name { display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#channel-list li .ch-icon { opacity: .6; flex-shrink: 0; }
#channel-list li .ch-count {
  background: var(--panel-alt); color: var(--text-faint); font-size: 11px;
  font-weight: 700; padding: 1px 7px; border-radius: 999px; flex-shrink: 0;
}
#channel-list li.active .ch-count { background: var(--accent); color: #fff; }
#channel-list li.skipped { opacity: .5; }
#channel-list li .skip-tag { font-size: 10px; color: var(--danger); }

#search-wrap { padding: 10px; border-top: 1px solid var(--border); flex-shrink: 0; }
#search-wrap input {
  width: 100%; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--panel-alt); color: var(--text); font-size: 13px;
}
#search-wrap input:focus { outline: 2px solid var(--accent); }

/* Main pane */
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
#main-header {
  padding: 12px 20px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}
#main-header h2 { margin: 0; font-size: 15px; font-weight: 700; }
#main-header .count-pill {
  background: var(--panel-alt); border: 1px solid var(--border); border-radius: 999px;
  padding: 2px 10px; font-size: 12px; color: var(--text-dim);
}
#messages { flex: 1; overflow-y: auto; padding: 16px 20px; }
.msg {
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px 14px; margin-bottom: 10px;
}
.msg .msg-top { display: flex; justify-content: space-between; color: var(--text-faint); font-size: 11px; margin-bottom: 6px; }
.msg .msg-content { white-space: pre-wrap; word-break: break-word; line-height: 1.45; }
.msg .msg-content.redacted { color: var(--text-faint); font-style: italic; }
.msg .attachments { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
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
</style>
</head>
<body>
<div id="app">
  <div id="header">
    <img class="avatar" src="__AVATAR_URL__" alt="avatar" onerror="this.style.visibility='hidden'">
    <div class="id-block">
      <div class="username">__USERNAME__ <span class="badge __REASON_BADGE_CLASS__">__REASON_LABEL__</span><span id="dryrun-badge"></span></div>
      <div class="userid">ID: __USER_ID__</div>
    </div>
    <div class="stats">
      <div class="stat"><div class="num" id="stat-total">0</div><div class="lbl">Deleted</div></div>
      <div class="stat"><div class="num" id="stat-channels">0</div><div class="lbl">Channels</div></div>
      <div class="stat"><div class="num" id="stat-skipped">0</div><div class="lbl">Skipped</div></div>
    </div>
    <div class="meta-row" id="meta-row"></div>
  </div>
  <div id="body">
    <div id="sidebar">
      <div class="sidebar-title">Channels</div>
      <ul id="channel-list"></ul>
      <div id="search-wrap">
        <input id="search" type="text" placeholder="Search message content…">
      </div>
    </div>
    <div id="main">
      <div id="main-header">
        <h2 id="channel-title">Select a channel</h2>
        <span class="count-pill" id="channel-count-pill"></span>
      </div>
      <div id="messages"></div>
    </div>
  </div>
  <div id="footer">Generated by GhostWipe __GHOSTWIPE_VERSION__ &middot; __GENERATED_AT__</div>
</div>

<script id="report-data" type="application/json">__REPORT_DATA_JSON__</script>
<script>
(function () {
  const data = JSON.parse(document.getElementById('report-data').textContent);
  const channelListEl = document.getElementById('channel-list');
  const messagesEl = document.getElementById('messages');
  const channelTitleEl = document.getElementById('channel-title');
  const channelCountPillEl = document.getElementById('channel-count-pill');
  const searchEl = document.getElementById('search');

  let activeChannelId = null;
  let searchTerm = '';

  document.getElementById('stat-total').textContent = data.totals.messages_deleted;
  document.getElementById('stat-channels').textContent = data.totals.channels_affected;
  document.getElementById('stat-skipped').textContent = data.totals.channels_skipped;
  if (data.dry_run) {
    document.getElementById('dryrun-badge').innerHTML = '<span class="badge badge-dryrun">Dry Run</span>';
  }
  document.getElementById('meta-row').textContent = data.meta_line || '';

  const icons = { text: '#', thread: '🩹', voice: '🔊' };

  function renderSidebar() {
    channelListEl.innerHTML = '';
    const sorted = [...data.channels].sort((a, b) => b.message_count - a.message_count);
    for (const ch of sorted) {
      const li = document.createElement('li');
      li.dataset.id = ch.id;
      if (ch.skipped) li.classList.add('skipped');
      if (ch.id === activeChannelId) li.classList.add('active');
      const nameSpan = document.createElement('span');
      nameSpan.className = 'ch-name';
      nameSpan.innerHTML = '<span class="ch-icon">' + (icons[ch.type] || '#') + '</span>' + escapeHtml(ch.name);
      li.appendChild(nameSpan);
      if (ch.skipped) {
        const tag = document.createElement('span');
        tag.className = 'skip-tag';
        tag.textContent = 'skipped';
        li.appendChild(tag);
      } else {
        const count = document.createElement('span');
        count.className = 'ch-count';
        count.textContent = ch.message_count;
        li.appendChild(count);
      }
      li.addEventListener('click', () => selectChannel(ch.id));
      channelListEl.appendChild(li);
    }
  }

  function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str == null ? '' : String(str);
    return d.innerHTML;
  }

  function selectChannel(id) {
    activeChannelId = id;
    renderSidebar();
    renderMessages();
  }

  function renderMessages() {
    const ch = data.channels.find(c => c.id === activeChannelId);
    messagesEl.innerHTML = '';
    if (!ch) {
      channelTitleEl.textContent = 'Select a channel';
      channelCountPillEl.textContent = '';
      return;
    }
    channelTitleEl.textContent = (ch.type === 'thread' ? '🩹 ' : '# ') + ch.name;
    channelCountPillEl.textContent = ch.message_count + ' message' + (ch.message_count === 1 ? '' : 's');

    if (ch.skipped) {
      const banner = document.createElement('div');
      banner.className = 'skip-banner';
      banner.textContent = 'This channel was skipped: ' + (ch.skip_reason || 'unknown reason');
      messagesEl.appendChild(banner);
      return;
    }

    let msgs = ch.messages || [];
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      msgs = msgs.filter(m => (m.content || '').toLowerCase().includes(term));
    }
    if (!msgs.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = searchTerm ? 'No messages match your search.' : 'No messages recorded for this channel.';
      messagesEl.appendChild(empty);
      return;
    }
    for (const m of msgs) {
      const card = document.createElement('div');
      card.className = 'msg';
      const top = document.createElement('div');
      top.className = 'msg-top';
      top.innerHTML = '<span>' + escapeHtml(m.timestamp) + '</span><span>#' + escapeHtml(m.id) + '</span>';
      card.appendChild(top);

      const content = document.createElement('div');
      if (m.redacted) {
        content.className = 'msg-content redacted';
        content.textContent = '[content redacted by server configuration]';
      } else {
        content.className = 'msg-content';
        content.textContent = m.content || (m.attachments && m.attachments.length ? '' : '[no text content]');
      }
      card.appendChild(content);

      if (!m.redacted && m.attachments && m.attachments.length) {
        const wrap = document.createElement('div');
        wrap.className = 'attachments';
        for (const a of m.attachments) {
          if (a.is_image) {
            const img = document.createElement('img');
            img.className = 'attachment-img';
            img.src = a.url;
            img.alt = a.filename;
            img.loading = 'lazy';
            img.onerror = function () { this.style.display = 'none'; };
            wrap.appendChild(img);
          } else {
            const a_el = document.createElement('a');
            a_el.className = 'attachment-chip';
            a_el.href = a.url;
            a_el.target = '_blank';
            a_el.rel = 'noopener noreferrer';
            a_el.textContent = '📎 ' + a.filename + (a.size ? ' (' + a.size + ')' : '');
            wrap.appendChild(a_el);
          }
        }
        card.appendChild(wrap);
      }

      if (!m.redacted && m.stickers && m.stickers.length) {
        for (const s of m.stickers) {
          const chip = document.createElement('span');
          chip.className = 'sticker-chip';
          chip.textContent = '✨ ' + s;
          card.appendChild(chip);
        }
      }

      messagesEl.appendChild(card);
    }
  }

  searchEl.addEventListener('input', () => {
    searchTerm = searchEl.value;
    renderMessages();
  });

  renderSidebar();
  const first = [...data.channels].sort((a, b) => b.message_count - a.message_count)[0];
  if (first) selectChannel(first.id);
})();
</script>
</body>
</html>
"""


def _badge_class(reason: str) -> str:
    return {
        "left": "badge-left",
        "kicked": "badge-kicked",
        "banned": "badge-banned",
    }.get(reason, "badge-left")


def _badge_label(reason: str) -> str:
    return {
        "left": "Left",
        "kicked": "Kicked",
        "banned": "Banned",
    }.get(reason, reason.title())


def generate_report_html(
    *,
    guild_name: str,
    member_name: str,
    member_id: int,
    avatar_url: str,
    reason: str,
    event_time_str: str,
    moderator: str = None,
    mod_reason: str = None,
    dry_run: bool = False,
    reveal_content: bool = True,
    channels: List[Dict[str, Any]],
    version: str = "1.0.0",
    generated_at: str = "",
) -> str:
    """Build the standalone HTML report string.

    ``channels`` is a list of dicts shaped like:
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

    if not reveal_content:
        for ch in channels:
            for m in ch.get("messages", []):
                m["redacted"] = True

    meta_bits = [f"Server: {guild_name}"]
    if moderator:
        meta_bits.append(f"By: {moderator}")
    if mod_reason:
        meta_bits.append(f"Reason: {mod_reason}")
    meta_line = "  •  ".join(meta_bits)

    payload = {
        "guild_name": guild_name,
        "member_name": member_name,
        "member_id": str(member_id),
        "reason": reason,
        "dry_run": dry_run,
        "meta_line": meta_line,
        "totals": {
            "messages_deleted": total_deleted,
            "channels_affected": channels_affected,
            "channels_skipped": channels_skipped,
        },
        "channels": channels,
    }

    out = TEMPLATE
    out = out.replace("__PAGE_TITLE__", html.escape(f"GhostWipe Report — {member_name}"))
    out = out.replace("__AVATAR_URL__", html.escape(avatar_url or "", quote=True))
    out = out.replace("__USERNAME__", html.escape(member_name))
    out = out.replace("__REASON_BADGE_CLASS__", _badge_class(reason))
    out = out.replace("__REASON_LABEL__", _badge_label(reason))
    out = out.replace("__USER_ID__", str(member_id))
    out = out.replace("__GHOSTWIPE_VERSION__", html.escape(version))
    out = out.replace("__GENERATED_AT__", html.escape(generated_at or event_time_str))
    out = out.replace("__REPORT_DATA_JSON__", json.dumps(payload))
    return out

