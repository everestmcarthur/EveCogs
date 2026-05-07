/* ═══════════════════════════════════════════════════════════════════════
   EveDash — Single-Page Application
   ═══════════════════════════════════════════════════════════════════════ */

(() => {
"use strict";

// ── State ──────────────────────────────────────────────────────────────

const state = {
    user: null,
    token: null,
    botInfo: null,
    guilds: [],
    selectedGuild: null,
    sidebarCollapsed: false,
    ws: null,
    wsRetries: 0,
};

// ── API Client ─────────────────────────────────────────────────────────

const api = {
    async fetch(path, opts = {}) {
        const headers = { "Content-Type": "application/json", ...opts.headers };
        if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
        const res = await fetch(`/api${path}`, { ...opts, headers });
        if (res.status === 401) { logout(); return null; }
        const data = await res.json();
        if (data.error && res.status >= 400) { toast(data.error, "error"); return null; }
        return data;
    },
    get:  (p) => api.fetch(p),
    post: (p, body) => api.fetch(p, { method: "POST", body: JSON.stringify(body || {}) }),
    put:  (p, body) => api.fetch(p, { method: "PUT",  body: JSON.stringify(body || {}) }),
    del:  (p) => api.fetch(p, { method: "DELETE" }),
};

// ── Toast system ───────────────────────────────────────────────────────

function toast(msg, type = "info") {
    let container = document.querySelector(".toast-container");
    if (!container) { container = document.createElement("div"); container.className = "toast-container"; document.body.appendChild(container); }
    const icons = { success: "fa-check-circle", error: "fa-exclamation-circle", warning: "fa-exclamation-triangle", info: "fa-info-circle" };
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i><span>${msg}</span><button class="toast-close" onclick="this.parentElement.classList.add('removing');setTimeout(()=>this.parentElement.remove(),300)"><i class="fas fa-times"></i></button>`;
    container.appendChild(el);
    setTimeout(() => { el.classList.add("removing"); setTimeout(() => el.remove(), 300); }, 4000);
}

// ── WebSocket ──────────────────────────────────────────────────────────

function connectWS() {
    if (state.ws && state.ws.readyState <= 1) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onopen = () => {
        ws.send(JSON.stringify({ token: state.token }));
        state.wsRetries = 0;
    };
    ws.onmessage = (e) => {
        try {
            const { event, data } = JSON.parse(e.data);
            if (event === "connected") return;
            if (event === "pong") return;
            if (["member_join", "member_remove"].includes(event) && state.selectedGuild) {
                // Could refresh guild data here
            }
        } catch {}
    };
    ws.onclose = () => {
        state.ws = null;
        if (state.user && state.wsRetries < 5) {
            state.wsRetries++;
            setTimeout(connectWS, 2000 * state.wsRetries);
        }
    };
    state.ws = ws;
    // Keepalive ping
    setInterval(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ type: "ping" })); }, 30000);
}

// ── Router ─────────────────────────────────────────────────────────────

function navigate(path) {
    location.hash = path;
}

function getRoute() {
    return location.hash.slice(1) || "/";
}

function parseQuery(hash) {
    const [, qs] = hash.split("?");
    if (!qs) return {};
    return Object.fromEntries(new URLSearchParams(qs));
}

// ── Auth ───────────────────────────────────────────────────────────────

async function login() {
    const data = await api.get("/auth/login");
    if (data && data.url) window.location.href = data.url;
}

function logout() {
    state.user = null;
    state.token = null;
    localStorage.removeItem("eve_token");
    navigate("/login");
}

async function checkAuth() {
    state.token = localStorage.getItem("eve_token");
    if (!state.token) return false;
    const data = await api.get("/auth/me");
    if (!data) { state.token = null; localStorage.removeItem("eve_token"); return false; }
    state.user = data;
    return true;
}

// ── Rendering helpers ──────────────────────────────────────────────────

function $(sel, el = document) { return el.querySelector(sel); }
function $$(sel, el = document) { return el.querySelectorAll(sel); }

function html(strings, ...vals) {
    return strings.reduce((acc, str, i) => acc + str + (vals[i] ?? ""), "");
}

function formatUptime(seconds) {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return String(n);
}

function guildIcon(guild, size = 32) {
    if (guild.icon) return `<img class="guild-icon" src="${guild.icon}" width="${size}" height="${size}" style="border-radius:var(--radius-sm);object-fit:cover;">`;
    return `<div class="guild-icon-placeholder" style="width:${size}px;height:${size}px;font-size:${size * 0.4}px">${guild.name.charAt(0).toUpperCase()}</div>`;
}

// ── Page: Login ────────────────────────────────────────────────────────

function renderLogin() {
    return html`
    <div class="login-page">
        <div class="login-bg"></div>
        <div class="login-card">
            <div class="logo"><i class="fas fa-robot"></i></div>
            <h1>Eve<span>Dash</span></h1>
            <p>Manage your Red-DiscordBot from a sleek web interface</p>
            <button class="login-btn" onclick="window.__login()">
                <i class="fab fa-discord"></i> Login with Discord
            </button>
            <div class="login-features">
                <div class="login-feature"><i class="fas fa-check"></i> Guild Management</div>
                <div class="login-feature"><i class="fas fa-check"></i> Cog Control</div>
                <div class="login-feature"><i class="fas fa-check"></i> Command Toggles</div>
                <div class="login-feature"><i class="fas fa-check"></i> Real-time Updates</div>
                <div class="login-feature"><i class="fas fa-check"></i> Third-party Settings</div>
                <div class="login-feature"><i class="fas fa-check"></i> Bot Owner Admin</div>
            </div>
        </div>
    </div>`;
}

// ── Sidebar ────────────────────────────────────────────────────────────

function renderSidebar() {
    const u = state.user;
    const g = state.selectedGuild;
    const isOwner = u && u.is_owner;
    const route = getRoute();

    const guildNav = g ? html`
        <div class="nav-section-title">Server</div>
        <div class="nav-item ${route.includes('/guild/') && route.includes('/overview') ? 'active' : ''}" data-nav="/guild/${g.id}/overview">
            <i class="fas fa-chart-bar"></i><span class="nav-text">Overview</span>
        </div>
        <div class="nav-item ${route.includes('/settings') ? 'active' : ''}" data-nav="/guild/${g.id}/settings">
            <i class="fas fa-cog"></i><span class="nav-text">Settings</span>
        </div>
        <div class="nav-item ${route.includes('/commands') ? 'active' : ''}" data-nav="/guild/${g.id}/commands">
            <i class="fas fa-terminal"></i><span class="nav-text">Commands</span>
        </div>
        <div class="nav-item ${route.includes('/third-parties') ? 'active' : ''}" data-nav="/guild/${g.id}/third-parties">
            <i class="fas fa-puzzle-piece"></i><span class="nav-text">Third Parties</span>
        </div>
    ` : "";

    const adminNav = isOwner ? html`
        <div class="nav-section-title">Admin</div>
        <div class="nav-item ${route === '/cogs' ? 'active' : ''}" data-nav="/cogs">
            <i class="fas fa-cubes"></i><span class="nav-text">Cog Management</span>
        </div>
        <div class="nav-item ${route === '/admin' ? 'active' : ''}" data-nav="/admin">
            <i class="fas fa-shield-alt"></i><span class="nav-text">Admin Panel</span>
        </div>
    ` : "";

    return html`
    <aside class="sidebar ${state.sidebarCollapsed ? 'collapsed' : ''}" id="sidebar">
        <button class="sidebar-toggle" id="sidebar-toggle">
            <i class="fas ${state.sidebarCollapsed ? 'fa-chevron-right' : 'fa-chevron-left'}"></i>
        </button>
        <div class="sidebar-brand">
            <div class="brand-icon"><i class="fas fa-robot"></i></div>
            <div class="brand-text">Eve<span>Dash</span></div>
        </div>

        <div class="guild-selector" id="guild-selector">
            ${g
                ? html`${guildIcon(g)}
                    <div class="guild-selector-text">
                        <div class="guild-name">${g.name}</div>
                        <div class="guild-members">${formatNumber(g.member_count)} members</div>
                    </div>
                    <i class="fas fa-chevron-down chevron"></i>`
                : html`<div class="guild-icon-placeholder" style="width:32px;height:32px;font-size:0.85rem"><i class="fas fa-plus"></i></div>
                    <div class="guild-selector-text">
                        <div class="guild-name">Select a Server</div>
                        <div class="guild-members">Choose a server to manage</div>
                    </div>
                    <i class="fas fa-chevron-down chevron"></i>`
            }
            <div class="guild-dropdown" id="guild-dropdown"></div>
        </div>

        <nav class="sidebar-nav">
            <div class="nav-section-title">General</div>
            <div class="nav-item ${route === '/' || route === '/home' ? 'active' : ''}" data-nav="/home">
                <i class="fas fa-home"></i><span class="nav-text">Home</span>
            </div>
            <div class="nav-item ${route === '/guilds' ? 'active' : ''}" data-nav="/guilds">
                <i class="fas fa-server"></i><span class="nav-text">Servers</span>
                <span class="nav-badge">${state.guilds.length}</span>
            </div>
            ${guildNav}
            ${adminNav}
        </nav>

        <div class="sidebar-footer">
            ${u ? html`
                <img class="user-avatar" src="${u.avatar || ''}" alt="">
                <div class="sidebar-footer-info">
                    <div class="user-name">${u.display_name || u.username}</div>
                    <div class="user-role">${u.is_owner ? '👑 Bot Owner' : 'Admin'}</div>
                </div>
                <button class="logout-btn" title="Logout" onclick="window.__logout()">
                    <i class="fas fa-sign-out-alt"></i>
                </button>
            ` : ""}
        </div>
    </aside>`;
}

// ── Page: Home ─────────────────────────────────────────────────────────

async function renderHome() {
    const info = state.botInfo || await api.get("/bot/info");
    if (info) state.botInfo = info;
    const stats = await api.get("/bot/stats");

    if (!info) return `<div class="page-body"><div class="empty-state"><i class="fas fa-exclamation-triangle"></i><h3>Error</h3><p>Could not load bot info.</p></div></div>`;

    const topGuilds = (stats?.top_guilds || []).map(g => html`
        <tr>
            <td><div class="flex items-center gap-1">${g.icon ? `<img src="${g.icon}" style="width:24px;height:24px;border-radius:var(--radius-sm);object-fit:cover">` : `<div style="width:24px;height:24px;border-radius:var(--radius-sm);background:var(--accent-soft);display:flex;align-items:center;justify-content:center;color:var(--accent);font-size:0.7rem;font-weight:600">${g.name.charAt(0)}</div>`}<span>${g.name}</span></div></td>
            <td>${formatNumber(g.members)}</td>
        </tr>
    `).join("");

    return html`
    <div class="page-header">
        <div class="flex items-center gap-1">
            <img src="${info.avatar}" style="width:36px;height:36px;border-radius:50%;margin-right:0.5rem">
            <div>
                <h1>${info.name}</h1>
                <p><span class="status-dot online"></span> Online · ${formatUptime(info.uptime_seconds)} uptime · ${info.latency_ms}ms latency</p>
            </div>
        </div>
    </div>
    <div class="page-body">
        <div class="stats-grid mb-2">
            <div class="stat-card">
                <div class="stat-icon blue"><i class="fas fa-server"></i></div>
                <div class="stat-value">${formatNumber(info.guild_count)}</div>
                <div class="stat-label">Servers</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon green"><i class="fas fa-users"></i></div>
                <div class="stat-value">${formatNumber(info.user_count)}</div>
                <div class="stat-label">Users</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon cyan"><i class="fas fa-hashtag"></i></div>
                <div class="stat-value">${formatNumber(info.channel_count)}</div>
                <div class="stat-label">Channels</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon yellow"><i class="fas fa-puzzle-piece"></i></div>
                <div class="stat-value">${info.cog_count}</div>
                <div class="stat-label">Cogs Loaded</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon red"><i class="fas fa-terminal"></i></div>
                <div class="stat-value">${formatNumber(info.command_count)}</div>
                <div class="stat-label">Commands</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon blue"><i class="fas fa-envelope"></i></div>
                <div class="stat-value">${formatNumber(stats?.message_count || 0)}</div>
                <div class="stat-label">Messages Tracked</div>
            </div>
        </div>

        <div class="grid-2">
            <div class="card">
                <div class="card-header">
                    <h3><i class="fas fa-crown"></i> Top Servers</h3>
                </div>
                <div class="card-body">
                    <div class="table-container">
                        <table>
                            <thead><tr><th>Server</th><th>Members</th></tr></thead>
                            <tbody>${topGuilds || '<tr><td colspan="2" class="text-muted text-sm">No data</td></tr>'}</tbody>
                        </table>
                    </div>
                </div>
            </div>
            <div class="card">
                <div class="card-header">
                    <h3><i class="fas fa-info-circle"></i> Bot Details</h3>
                </div>
                <div class="card-body">
                    <table>
                        <tr><td class="text-muted">Bot ID</td><td class="font-mono text-sm">${info.id}</td></tr>
                        <tr><td class="text-muted">Prefixes</td><td class="font-mono text-sm">${(info.prefixes || []).map(p => `<span class="badge badge-primary">${p}</span>`).join(" ")}</td></tr>
                        <tr><td class="text-muted">Red Version</td><td>${info.red_version}</td></tr>
                        <tr><td class="text-muted">Owner</td><td>${info.owner?.name || "Unknown"}</td></tr>
                        <tr><td class="text-muted">Latency</td><td><span class="badge ${info.latency_ms < 100 ? 'badge-success' : info.latency_ms < 300 ? 'badge-warning' : 'badge-danger'}">${info.latency_ms}ms</span></td></tr>
                    </table>
                </div>
            </div>
        </div>
    </div>`;
}

// ── Page: Guilds ───────────────────────────────────────────────────────

async function renderGuilds() {
    const data = await api.get("/guilds");
    if (data) state.guilds = data.guilds;
    const guilds = state.guilds;

    const list = guilds.map(g => html`
        <div class="cog-card" style="cursor:pointer" data-guild="${g.id}">
            <div class="cog-card-header">
                <h4>${guildIcon(g, 28)} ${g.name}</h4>
            </div>
            <p>${formatNumber(g.member_count)} members · ${g.channel_count} channels · ${g.role_count} roles</p>
            <button class="btn btn-primary btn-sm" data-guild="${g.id}"><i class="fas fa-cog"></i> Manage</button>
        </div>
    `).join("");

    return html`
    <div class="page-header">
        <h1>Servers</h1>
        <p>Select a server to manage</p>
    </div>
    <div class="page-body">
        <div class="cog-grid">
            ${list || '<div class="empty-state"><i class="fas fa-server"></i><h3>No servers</h3><p>You don\'t have manage permissions on any servers this bot is in.</p></div>'}
        </div>
    </div>`;
}

// ── Page: Guild Overview ───────────────────────────────────────────────

async function renderGuildOverview(guildId) {
    const guild = await api.get(`/guilds/${guildId}`);
    if (!guild) return `<div class="page-body"><div class="empty-state"><i class="fas fa-exclamation-triangle"></i><h3>Guild not found</h3></div></div>`;

    const features = (guild.features || []).map(f => `<span class="badge badge-muted">${f.replace(/_/g, " ")}</span>`).join(" ");

    return html`
    <div class="page-header">
        <div class="guild-hero">
            ${guild.icon ? `<img class="guild-hero-icon" src="${guild.icon}">` : `<div class="guild-hero-icon-placeholder">${guild.name.charAt(0)}</div>`}
            <div class="guild-hero-info">
                <h2>${guild.name}</h2>
                <div class="guild-meta">
                    <span><i class="fas fa-users"></i> ${formatNumber(guild.member_count)} members</span>
                    <span><i class="fas fa-hashtag"></i> ${guild.text_channels} text · ${guild.voice_channels} voice</span>
                    <span><i class="fas fa-at"></i> ${guild.role_count} roles</span>
                    <span><i class="fas fa-smile"></i> ${guild.emoji_count} emojis</span>
                </div>
            </div>
        </div>
    </div>
    <div class="page-body">
        <div class="stats-grid mb-2">
            <div class="stat-card">
                <div class="stat-icon green"><i class="fas fa-users"></i></div>
                <div class="stat-value">${formatNumber(guild.member_count)}</div>
                <div class="stat-label">Members</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon blue"><i class="fas fa-hashtag"></i></div>
                <div class="stat-value">${guild.text_channels + guild.voice_channels}</div>
                <div class="stat-label">Channels</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon yellow"><i class="fas fa-gem"></i></div>
                <div class="stat-value">${guild.boost_count}</div>
                <div class="stat-label">Boosts (Level ${guild.boost_level})</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon cyan"><i class="fas fa-at"></i></div>
                <div class="stat-value">${guild.role_count}</div>
                <div class="stat-label">Roles</div>
            </div>
        </div>

        <div class="card">
            <div class="card-header"><h3><i class="fas fa-info-circle"></i> Server Details</h3></div>
            <div class="card-body">
                <table>
                    <tr><td class="text-muted" style="width:180px">Server ID</td><td class="font-mono text-sm">${guild.id}</td></tr>
                    <tr><td class="text-muted">Owner</td><td>${guild.owner?.name || "Unknown"}</td></tr>
                    <tr><td class="text-muted">Created</td><td>${new Date(guild.created_at).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })}</td></tr>
                    <tr><td class="text-muted">Boost Level</td><td><span class="badge badge-info">Level ${guild.boost_level}</span> (${guild.boost_count} boosts)</td></tr>
                    ${features ? `<tr><td class="text-muted">Features</td><td>${features}</td></tr>` : ""}
                </table>
            </div>
        </div>
    </div>`;
}

// ── Page: Guild Settings ───────────────────────────────────────────────

async function renderGuildSettings(guildId) {
    const [settings, roles, channels] = await Promise.all([
        api.get(`/guilds/${guildId}/settings`),
        api.get(`/guilds/${guildId}/roles`),
        api.get(`/guilds/${guildId}/channels`),
    ]);
    if (!settings) return "";

    const roleOptions = (roles?.roles || [])
        .filter(r => r.name !== "@everyone" && !r.managed)
        .map(r => `<option value="${r.id}" ${(settings.admin_roles || []).includes(r.id) ? "selected" : ""}>${r.name}</option>`)
        .join("");

    const modRoleOptions = (roles?.roles || [])
        .filter(r => r.name !== "@everyone" && !r.managed)
        .map(r => `<option value="${r.id}" ${(settings.mod_roles || []).includes(r.id) ? "selected" : ""}>${r.name}</option>`)
        .join("");

    return html`
    <div class="page-header">
        <h1>Bot Settings</h1>
        <p>Configure bot behavior for this server</p>
    </div>
    <div class="page-body">
        <div class="card">
            <div class="card-header"><h3><i class="fas fa-cog"></i> General Settings</h3></div>
            <div class="card-body">
                <form id="guild-settings-form" class="settings-form">
                    <div class="form-group">
                        <label class="form-label">Bot Nickname</label>
                        <input class="form-input" name="bot_nickname" value="${settings.bot_nickname || ""}" placeholder="Leave empty for default">
                        <div class="form-hint">The bot's nickname in this server</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Prefixes</label>
                        <input class="form-input" name="prefixes" value="${(settings.prefixes || []).join(", ")}" placeholder="!, ?, .">
                        <div class="form-hint">Comma-separated list of command prefixes</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Admin Roles</label>
                        <select class="form-select" name="admin_roles" multiple style="min-height:80px">
                            ${roleOptions}
                        </select>
                        <div class="form-hint">Roles that can use admin commands (Ctrl+Click to multi-select)</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Mod Roles</label>
                        <select class="form-select" name="mod_roles" multiple style="min-height:80px">
                            ${modRoleOptions}
                        </select>
                        <div class="form-hint">Roles that can use mod commands</div>
                    </div>
                    <button type="submit" class="btn btn-primary mt-2"><i class="fas fa-save"></i> Save Settings</button>
                </form>
            </div>
        </div>
    </div>`;
}

// ── Page: Guild Commands ───────────────────────────────────────────────

async function renderGuildCommands(guildId) {
    const data = await api.get(`/guilds/${guildId}/commands`);
    if (!data) return "";

    const cogs = Object.values(data.cogs || {});
    const accordions = cogs.map(cog => {
        const cmds = (cog.commands || []).filter(c => !c.parent);
        return html`
        <div class="accordion-item">
            <div class="accordion-header">
                <h4><i class="fas fa-puzzle-piece"></i> ${cog.name} <span class="badge badge-muted" style="margin-left:0.5rem">${cmds.length}</span></h4>
                <span class="text-xs text-muted" style="margin-right:1rem">${cog.description}</span>
                <i class="fas fa-chevron-down arrow"></i>
            </div>
            <div class="accordion-body">
                <div class="accordion-body-inner">
                    ${cmds.map(cmd => html`
                        <div class="command-row">
                            <div class="command-info">
                                <div class="command-name">${cmd.name}${cmd.signature ? ` <span class="text-muted text-xs">${cmd.signature}</span>` : ""}</div>
                                <div class="command-desc">${cmd.description || "No description"}</div>
                                ${cmd.aliases.length ? `<div class="command-aliases">${cmd.aliases.map(a => `<span>${a}</span>`).join("")}</div>` : ""}
                            </div>
                            <label class="toggle">
                                <input type="checkbox" ${cmd.enabled ? "checked" : ""} data-cmd="${cmd.name}" data-guild="${guildId}">
                                <span class="slider"></span>
                            </label>
                        </div>
                    `).join("")}
                </div>
            </div>
        </div>`;
    }).join("");

    return html`
    <div class="page-header">
        <div class="flex items-center justify-between">
            <div>
                <h1>Commands</h1>
                <p>Enable or disable commands for this server</p>
            </div>
            <div class="search-box">
                <i class="fas fa-search"></i>
                <input type="text" placeholder="Search commands..." id="cmd-search">
            </div>
        </div>
    </div>
    <div class="page-body">
        <div id="cmd-accordion">${accordions}</div>
    </div>`;
}

// ── Page: Third Parties ────────────────────────────────────────────────

async function renderThirdParties(guildId) {
    const data = await api.get(`/guilds/${guildId}/third-parties`);
    if (!data) return "";

    const tps = Object.values(data.third_parties || {});

    if (!tps.length) {
        return html`
        <div class="page-header"><h1>Third-Party Cog Settings</h1><p>Cogs with dashboard integration</p></div>
        <div class="page-body">
            <div class="empty-state">
                <i class="fas fa-puzzle-piece"></i>
                <h3>No Third Parties</h3>
                <p>No cogs have registered dashboard pages yet. Cog developers can add dashboard support using the EveDash SDK.</p>
            </div>
        </div>`;
    }

    const cards = tps.map(tp => {
        const pages = Object.values(tp.pages || {});
        return html`
        <div class="cog-card">
            <div class="cog-card-header">
                <h4><i class="fas fa-puzzle-piece"></i> ${tp.name}</h4>
                <span class="badge badge-primary">${pages.length} page${pages.length !== 1 ? "s" : ""}</span>
            </div>
            <p>${tp.description}</p>
            <div class="cog-card-actions">
                ${pages.map(p => html`
                    <button class="btn btn-ghost btn-sm" data-tp="${tp.name}" data-tp-page="${p.name}" data-guild="${guildId}">
                        <i class="${p.icon || 'fas fa-cog'}"></i> ${p.description || p.name}
                    </button>
                `).join("")}
            </div>
        </div>`;
    }).join("");

    return html`
    <div class="page-header"><h1>Third-Party Cog Settings</h1><p>Cogs with dashboard integration</p></div>
    <div class="page-body">
        <div class="cog-grid">${cards}</div>
        <div id="tp-content" class="mt-3"></div>
    </div>`;
}

async function loadThirdPartyPage(guildId, cogName, pageName) {
    const data = await api.get(`/guilds/${guildId}/third-parties/${cogName}/${pageName}`);
    if (!data || data.status === 1) {
        toast(data?.error || "Failed to load page", "error");
        return;
    }

    const wc = data.web_content;
    if (!wc || !wc.settings) return;

    const formFields = wc.settings.map(s => renderSettingField(s)).join("");

    const container = document.getElementById("tp-content");
    if (container) {
        container.innerHTML = html`
        <div class="card">
            <div class="card-header"><h3><i class="fas fa-cog"></i> ${cogName} — ${pageName}</h3></div>
            <div class="card-body">
                <form class="settings-form" id="tp-form" data-cog="${cogName}" data-page="${pageName}" data-guild="${guildId}">
                    ${formFields}
                    <button type="submit" class="btn btn-primary mt-2"><i class="fas fa-save"></i> Save</button>
                </form>
            </div>
        </div>`;
    }
}

function renderSettingField(s) {
    switch (s.type) {
        case "toggle":
            return html`<div class="form-group"><div class="toggle-wrapper"><label class="toggle"><input type="checkbox" name="${s.id}" ${s.value ? "checked" : ""}><span class="slider"></span></label><div><div class="form-label" style="margin-bottom:0">${s.label}</div>${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div></div></div>`;
        case "textarea":
            return html`<div class="form-group"><label class="form-label">${s.label}</label><textarea class="form-textarea" name="${s.id}" placeholder="${s.placeholder || ""}">${s.value || ""}</textarea>${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div>`;
        case "number":
            return html`<div class="form-group"><label class="form-label">${s.label}</label><input class="form-input" type="number" name="${s.id}" value="${s.value || ""}" min="${s.min || ""}" max="${s.max || ""}" step="${s.step || 1}">${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div>`;
        case "select":
            return html`<div class="form-group"><label class="form-label">${s.label}</label><select class="form-select" name="${s.id}">${(s.options || []).map(o => `<option value="${o.value}" ${o.value == s.value ? "selected" : ""}>${o.label}</option>`).join("")}</select>${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div>`;
        case "channel_select":
            return html`<div class="form-group"><label class="form-label">${s.label}</label><input class="form-input" name="${s.id}" value="${s.value || ""}" placeholder="Channel ID">${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div>`;
        case "role_select":
            return html`<div class="form-group"><label class="form-label">${s.label}</label><input class="form-input" name="${s.id}" value="${s.value || ""}" placeholder="Role ID">${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div>`;
        case "color":
            return html`<div class="form-group"><label class="form-label">${s.label}</label><input class="form-input" type="color" name="${s.id}" value="${s.value || "#5865F2"}">${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div>`;
        default: // text
            return html`<div class="form-group"><label class="form-label">${s.label}</label><input class="form-input" name="${s.id}" value="${s.value || ""}" placeholder="${s.placeholder || ""}">${s.description ? `<div class="form-hint">${s.description}</div>` : ""}</div>`;
    }
}

// ── Page: Cog Management ───────────────────────────────────────────────

async function renderCogs() {
    const data = await api.get("/cogs");
    if (!data) return "";

    const loaded = Object.values(data.loaded || {}).sort((a, b) => a.name.localeCompare(b.name));
    const available = (data.available || []).sort((a, b) => a.name.localeCompare(b.name));

    const loadedCards = loaded.map(c => html`
        <div class="cog-card">
            <div class="cog-card-header">
                <h4><i class="fas fa-cube" style="color:var(--success)"></i> ${c.name}</h4>
                <span class="badge badge-success">Loaded</span>
            </div>
            <p>${c.description || "No description"}</p>
            <p class="text-xs text-muted">${(c.commands || []).length} commands</p>
            <div class="cog-card-actions mt-1">
                <button class="btn btn-ghost btn-sm" data-cog-action="reload" data-cog="${c.name}"><i class="fas fa-sync-alt"></i> Reload</button>
                ${c.name !== "EveDash" ? `<button class="btn btn-danger btn-sm" data-cog-action="unload" data-cog="${c.name}"><i class="fas fa-stop"></i> Unload</button>` : ""}
            </div>
        </div>
    `).join("");

    const availableCards = available.map(c => html`
        <div class="cog-card">
            <div class="cog-card-header">
                <h4><i class="fas fa-cube" style="color:var(--text-muted)"></i> ${c.name}</h4>
                <span class="badge badge-muted">Unloaded</span>
            </div>
            <p class="text-xs text-muted">Repo: ${c.repo || "unknown"}</p>
            <div class="cog-card-actions mt-1">
                <button class="btn btn-primary btn-sm" data-cog-action="load" data-cog="${c.name}"><i class="fas fa-play"></i> Load</button>
            </div>
        </div>
    `).join("");

    return html`
    <div class="page-header">
        <h1>Cog Management</h1>
        <p>Load, unload, and reload cogs</p>
    </div>
    <div class="page-body">
        <h3 class="mb-1" style="font-size:1rem"><i class="fas fa-check-circle" style="color:var(--success)"></i> Loaded (${loaded.length})</h3>
        <div class="cog-grid mb-2">${loadedCards}</div>
        ${available.length ? html`<h3 class="mb-1" style="font-size:1rem"><i class="fas fa-circle" style="color:var(--text-muted)"></i> Available (${available.length})</h3><div class="cog-grid">${availableCards}</div>` : ""}
    </div>`;
}

// ── Page: Admin Panel ──────────────────────────────────────────────────

async function renderAdmin() {
    const [config, blacklist] = await Promise.all([
        api.get("/admin/config"),
        api.get("/admin/blacklist"),
    ]);
    if (!config) return "";

    const blRows = (blacklist?.blacklist || []).map(u => html`
        <tr>
            <td><div class="flex items-center gap-1">${u.avatar ? `<img src="${u.avatar}" style="width:24px;height:24px;border-radius:50%">` : ""}<span>${u.name}</span></div></td>
            <td class="font-mono text-sm">${u.id}</td>
            <td><button class="btn btn-danger btn-sm" data-bl-remove="${u.id}"><i class="fas fa-times"></i></button></td>
        </tr>
    `).join("");

    return html`
    <div class="page-header"><h1>Admin Panel</h1><p>Bot-wide configuration (owner only)</p></div>
    <div class="page-body">
        <div class="grid-2">
            <div class="card">
                <div class="card-header"><h3><i class="fas fa-sliders-h"></i> Global Config</h3></div>
                <div class="card-body">
                    <form id="admin-config-form" class="settings-form">
                        <div class="form-group">
                            <label class="form-label">Global Prefixes</label>
                            <input class="form-input" name="global_prefixes" value="${(config.global_prefixes || []).join(", ")}">
                            <div class="form-hint">Comma-separated</div>
                        </div>
                        <div class="form-group">
                            <div class="toggle-wrapper">
                                <label class="toggle"><input type="checkbox" name="embeds" ${config.embeds ? "checked" : ""}><span class="slider"></span></label>
                                <div><div class="form-label" style="margin-bottom:0">Embeds</div><div class="form-hint">Use embeds for responses</div></div>
                            </div>
                        </div>
                        <div class="form-group">
                            <div class="toggle-wrapper">
                                <label class="toggle"><input type="checkbox" name="fuzzy" ${config.fuzzy ? "checked" : ""}><span class="slider"></span></label>
                                <div><div class="form-label" style="margin-bottom:0">Fuzzy Command Search</div><div class="form-hint">Suggest similar commands on typo</div></div>
                            </div>
                        </div>
                        <div class="form-group">
                            <div class="toggle-wrapper">
                                <label class="toggle"><input type="checkbox" name="invite_public" ${config.invite_public ? "checked" : ""}><span class="slider"></span></label>
                                <div><div class="form-label" style="margin-bottom:0">Public Invite</div><div class="form-hint">Allow anyone to get the invite link</div></div>
                            </div>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Locale</label>
                            <input class="form-input" name="locale" value="${config.locale || "en-US"}">
                        </div>
                        <button type="submit" class="btn btn-primary mt-1"><i class="fas fa-save"></i> Save</button>
                    </form>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h3><i class="fas fa-ban"></i> Dashboard Blacklist</h3>
                    <button class="btn btn-ghost btn-sm" id="bl-add-btn"><i class="fas fa-plus"></i> Add</button>
                </div>
                <div class="card-body">
                    ${blRows ? html`<div class="table-container"><table><thead><tr><th>User</th><th>ID</th><th></th></tr></thead><tbody>${blRows}</tbody></table></div>` : '<div class="empty-state" style="padding:1.5rem"><i class="fas fa-check-circle" style="font-size:1.5rem;color:var(--success)"></i><p class="text-sm text-muted mt-1">No blacklisted users</p></div>'}
                </div>
            </div>
        </div>
    </div>`;
}

// ── Main Render ────────────────────────────────────────────────────────

async function render() {
    const route = getRoute();
    const app = document.getElementById("app");

    // Handle OAuth callback
    if (route.startsWith("/callback")) {
        const params = parseQuery(location.hash);
        if (params.token) {
            localStorage.setItem("eve_token", params.token);
            state.token = params.token;
        }
        navigate("/home");
        return;
    }

    // Check auth
    if (route !== "/login") {
        const authed = await checkAuth();
        if (!authed) {
            navigate("/login");
            return;
        }
    }

    if (route === "/login") {
        app.innerHTML = renderLogin();
        hideLoading();
        return;
    }

    // Load guilds if not loaded
    if (!state.guilds.length) {
        const data = await api.get("/guilds");
        if (data) state.guilds = data.guilds;
    }

    // Determine page content
    let content = "";
    const guildMatch = route.match(/^\/guild\/(\d+)\/(.*)/);

    if (guildMatch) {
        const guildId = guildMatch[1];
        const subPage = guildMatch[2];
        state.selectedGuild = state.guilds.find(g => g.id === guildId) || { id: guildId, name: "Unknown", member_count: 0 };

        switch (subPage) {
            case "overview": content = await renderGuildOverview(guildId); break;
            case "settings": content = await renderGuildSettings(guildId); break;
            case "commands": content = await renderGuildCommands(guildId); break;
            case "third-parties": content = await renderThirdParties(guildId); break;
            default: content = await renderGuildOverview(guildId);
        }
    } else {
        switch (route) {
            case "/": case "/home": content = await renderHome(); break;
            case "/guilds": content = await renderGuilds(); break;
            case "/cogs": content = await renderCogs(); break;
            case "/admin": content = await renderAdmin(); break;
            default: content = await renderHome();
        }
    }

    app.innerHTML = `
        ${renderSidebar()}
        <button class="mobile-menu-btn" id="mobile-menu"><i class="fas fa-bars"></i></button>
        <main class="main-content ${state.sidebarCollapsed ? 'sidebar-collapsed' : ''}">
            ${content}
        </main>
    `;

    hideLoading();
    bindEvents();
    connectWS();
}

// ── Event Bindings ─────────────────────────────────────────────────────

function bindEvents() {
    // Sidebar nav
    document.querySelectorAll("[data-nav]").forEach(el => {
        el.addEventListener("click", () => navigate(el.dataset.nav));
    });

    // Sidebar toggle
    const toggleBtn = document.getElementById("sidebar-toggle");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            state.sidebarCollapsed = !state.sidebarCollapsed;
            localStorage.setItem("sidebar_collapsed", state.sidebarCollapsed);
            render();
        });
    }

    // Mobile menu
    const mobileBtn = document.getElementById("mobile-menu");
    if (mobileBtn) {
        mobileBtn.addEventListener("click", () => {
            const sidebar = document.getElementById("sidebar");
            if (sidebar) sidebar.classList.toggle("mobile-open");
        });
    }

    // Guild selector dropdown
    const guildSel = document.getElementById("guild-selector");
    const guildDd = document.getElementById("guild-dropdown");
    if (guildSel && guildDd) {
        guildSel.addEventListener("click", (e) => {
            e.stopPropagation();
            const isOpen = guildDd.classList.contains("open");
            if (isOpen) {
                guildDd.classList.remove("open");
            } else {
                // Populate dropdown
                guildDd.innerHTML = `
                    <input class="guild-dropdown-search" placeholder="Search servers..." id="guild-search-input">
                    ${state.guilds.map(g => `
                        <div class="guild-dropdown-item ${state.selectedGuild?.id === g.id ? 'active' : ''}" data-guild="${g.id}">
                            ${g.icon ? `<img src="${g.icon}">` : `<div class="placeholder-icon">${g.name.charAt(0)}</div>`}
                            <span>${g.name}</span>
                        </div>
                    `).join("")}
                `;
                guildDd.classList.add("open");

                // Search filter
                const searchInput = document.getElementById("guild-search-input");
                if (searchInput) {
                    searchInput.focus();
                    searchInput.addEventListener("input", (e) => {
                        const q = e.target.value.toLowerCase();
                        guildDd.querySelectorAll(".guild-dropdown-item").forEach(item => {
                            const name = item.querySelector("span").textContent.toLowerCase();
                            item.style.display = name.includes(q) ? "" : "none";
                        });
                    });
                    searchInput.addEventListener("click", (e) => e.stopPropagation());
                }

                // Guild selection
                guildDd.querySelectorAll(".guild-dropdown-item").forEach(item => {
                    item.addEventListener("click", (e) => {
                        e.stopPropagation();
                        const gid = item.dataset.guild;
                        state.selectedGuild = state.guilds.find(g => g.id === gid);
                        guildDd.classList.remove("open");
                        navigate(`/guild/${gid}/overview`);
                    });
                });
            }
        });

        // Close dropdown on outside click
        document.addEventListener("click", () => guildDd.classList.remove("open"));
    }

    // Guild cards on guilds page
    document.querySelectorAll("[data-guild]").forEach(el => {
        if (el.classList.contains("guild-dropdown-item") || el.classList.contains("guild-selector")) return;
        el.addEventListener("click", (e) => {
            const gid = el.dataset.guild || e.target.closest("[data-guild]")?.dataset.guild;
            if (gid) {
                state.selectedGuild = state.guilds.find(g => g.id === gid);
                navigate(`/guild/${gid}/overview`);
            }
        });
    });

    // Command toggles
    document.querySelectorAll("[data-cmd]").forEach(el => {
        el.addEventListener("change", async () => {
            const cmd = el.dataset.cmd;
            const gid = el.dataset.guild;
            const result = await api.put(`/guilds/${gid}/commands/${cmd}`, { enabled: el.checked });
            if (result) toast(`${cmd} ${el.checked ? "enabled" : "disabled"}`, "success");
        });
    });

    // Accordion
    document.querySelectorAll(".accordion-header").forEach(el => {
        el.addEventListener("click", () => {
            el.parentElement.classList.toggle("open");
        });
    });

    // Command search
    const cmdSearch = document.getElementById("cmd-search");
    if (cmdSearch) {
        cmdSearch.addEventListener("input", (e) => {
            const q = e.target.value.toLowerCase();
            document.querySelectorAll(".accordion-item").forEach(item => {
                const cmds = item.querySelectorAll(".command-row");
                let visible = 0;
                cmds.forEach(row => {
                    const name = row.querySelector(".command-name")?.textContent.toLowerCase() || "";
                    const show = !q || name.includes(q);
                    row.style.display = show ? "" : "none";
                    if (show) visible++;
                });
                item.style.display = visible || !q ? "" : "none";
                if (q && visible) item.classList.add("open");
            });
        });
    }

    // Guild settings form
    const guildForm = document.getElementById("guild-settings-form");
    if (guildForm) {
        guildForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fd = new FormData(guildForm);
            const gid = getRoute().match(/\/guild\/(\d+)/)?.[1];
            if (!gid) return;

            const prefixes = fd.get("prefixes").split(",").map(s => s.trim()).filter(Boolean);
            const adminRoles = Array.from(guildForm.querySelector('[name="admin_roles"]')?.selectedOptions || []).map(o => o.value);
            const modRoles = Array.from(guildForm.querySelector('[name="mod_roles"]')?.selectedOptions || []).map(o => o.value);

            const result = await api.put(`/guilds/${gid}/settings`, {
                bot_nickname: fd.get("bot_nickname"),
                prefixes,
                admin_roles: adminRoles,
                mod_roles: modRoles,
            });
            if (result) toast("Settings saved!", "success");
        });
    }

    // Cog actions
    document.querySelectorAll("[data-cog-action]").forEach(el => {
        el.addEventListener("click", async () => {
            const action = el.dataset.cogAction;
            const cog = el.dataset.cog;
            if (action === "unload" && !confirm(`Unload ${cog}?`)) return;
            const result = await api.post(`/cogs/${cog}/${action}`);
            if (result) { toast(result.message || `${cog} ${action}ed`, "success"); render(); }
        });
    });

    // Third-party page buttons
    document.querySelectorAll("[data-tp]").forEach(el => {
        if (!el.dataset.tpPage) return;
        el.addEventListener("click", () => {
            loadThirdPartyPage(el.dataset.guild, el.dataset.tp, el.dataset.tpPage);
        });
    });

    // Third-party form
    document.addEventListener("submit", async (e) => {
        if (e.target.id !== "tp-form") return;
        e.preventDefault();
        const form = e.target;
        const cogName = form.dataset.cog;
        const page = form.dataset.page;
        const gid = form.dataset.guild;

        const data = {};
        new FormData(form).forEach((v, k) => {
            const input = form.querySelector(`[name="${k}"]`);
            if (input && input.type === "checkbox") {
                data[k] = input.checked;
            } else {
                data[k] = v;
            }
        });
        // Include unchecked checkboxes
        form.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            if (!data.hasOwnProperty(cb.name)) data[cb.name] = false;
        });

        const result = await api.post(`/guilds/${gid}/third-parties/${cogName}/${page}`, data);
        if (result && result.status === 0) {
            toast("Settings saved!", "success");
            if (result.notifications) {
                result.notifications.forEach(n => toast(n.message, n.type || "info"));
            }
        }
    });

    // Admin config form
    const adminForm = document.getElementById("admin-config-form");
    if (adminForm) {
        adminForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fd = new FormData(adminForm);
            const result = await api.put("/admin/config", {
                global_prefixes: fd.get("global_prefixes").split(",").map(s => s.trim()).filter(Boolean),
                embeds: adminForm.querySelector('[name="embeds"]').checked,
                fuzzy: adminForm.querySelector('[name="fuzzy"]').checked,
                invite_public: adminForm.querySelector('[name="invite_public"]').checked,
                locale: fd.get("locale"),
            });
            if (result) toast("Config saved!", "success");
        });
    }

    // Blacklist remove
    document.querySelectorAll("[data-bl-remove]").forEach(el => {
        el.addEventListener("click", async () => {
            const uid = el.dataset.blRemove;
            await api.del(`/admin/blacklist/${uid}`);
            toast("User removed from blacklist", "success");
            render();
        });
    });

    // Blacklist add
    const blAddBtn = document.getElementById("bl-add-btn");
    if (blAddBtn) {
        blAddBtn.addEventListener("click", async () => {
            const uid = prompt("Enter user ID to blacklist:");
            if (!uid) return;
            await api.post("/admin/blacklist", { user_id: uid });
            toast("User added to blacklist", "success");
            render();
        });
    }
}

function hideLoading() {
    const ls = document.getElementById("loading-screen");
    if (ls) ls.classList.add("hidden");
}

// ── Global exports ─────────────────────────────────────────────────────

window.__login = login;
window.__logout = logout;

// ── Init ───────────────────────────────────────────────────────────────

state.sidebarCollapsed = localStorage.getItem("sidebar_collapsed") === "true";

window.addEventListener("hashchange", render);
render();

})();
