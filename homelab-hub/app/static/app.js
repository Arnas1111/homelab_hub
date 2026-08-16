let currentData = null;
let settings = { title: 'Homelab Hub', refresh_seconds: 5, confirm_actions: true };
let refreshTimer = null;
let logRefreshTimer = null;
let activeContainer = null;

const $ = (id) => document.getElementById(id);
const DEFAULT_CONTAINER_ICON = 'docker';
const DASHBOARD_ICONS = [
  'adguard-home','authelia','authentik','bazarr','cloudflare','cloudflare-zero-trust','deluge','docker','duplicati','filebrowser','frigate','grafana','home-assistant','immich','jellyfin','jellyseerr','lidarr','mariadb','mqtt','mysql','netdata','nextcloud','nginx','nginx-proxy-manager','node-red','overseerr','paperless-ngx','photoprism','plex','portainer','postgresql','prowlarr','qbittorrent','radarr','redis','sabnzbd','sonarr','tautulli','traefik','transmission','unifi','unraid','uptime-kuma','vaultwarden','wireguard','wordpress'
];

function bytes(v) {
  if (!v) return '0 B';
  const u = ['B','KB','MB','GB','TB']; let i = 0; let n = Number(v);
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i > 1 ? 1 : 0)} ${u[i]}`;
}

function toast(message) {
  const el = $('toast'); el.textContent = message; el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 2600);
}

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options, headers: { 'Content-Type':'application/json', ...(options.headers || {}) } });
  if (response.status === 401) { location.href = '/login'; throw new Error('Authentication required'); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function statusBadge(c) {
  const health = c.health ? ` · ${c.health}` : '';
  return `<span class="badge ${c.status}">${c.status}${health}</span>`;
}

function portText(ports) {
  if (!ports || !ports.length) return '—';
  return ports.slice(0,3).map(p => `<span class="port">${p.host_port} → ${p.internal}</span>`).join('<br>') + (ports.length > 3 ? `<br><span class="muted">+${ports.length-3} more</span>` : '');
}

function containerIcon(c) {
  return c.icon || DEFAULT_CONTAINER_ICON;
}

function iconPath(icon) {
  return `/static/icons/dashboard/${icon || DEFAULT_CONTAINER_ICON}.svg`;
}

function sanitizeIcon(value) {
  return value.trim().toLowerCase().replace(/[\s_]+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

function renderContainers() {
  if (!currentData) return;
  const q = $('containerSearch').value.trim().toLowerCase();
  const rows = currentData.containers.filter(c => !q || `${c.name} ${c.image} ${c.project || ''} ${c.group_name || ''}`.toLowerCase().includes(q));
  $('containerRows').innerHTML = rows.length ? groupedContainers(rows).map(group => `
    <tr class="group-row"><td colspan="7"><span class="folder-mark"></span>${escapeHtml(group.name)}</td></tr>
    ${group.containers.map(c => `
    <tr class="container-row" onclick="openContainer('${c.id}')">
      <td class="name-cell">
        <div class="container-title">
          <span class="container-icon"><img src="${iconPath(containerIcon(c))}" alt="" loading="lazy" onerror="this.closest('.container-icon').classList.add('missing')"></span>
          <div><strong>${escapeHtml(c.name)}</strong><small>${c.project ? escapeHtml(c.project) : c.short_id}</small></div>
        </div>
      </td>
      <td>${statusBadge(c)}</td>
      <td>${Number(c.cpu_percent || 0).toFixed(1)}%<div class="meter"><i style="width:${Math.min(c.cpu_percent || 0,100)}%"></i></div></td>
      <td>${bytes(c.memory_used)} <span class="muted">/ ${bytes(c.memory_limit)}</span><div class="meter"><i style="width:${Math.min(c.memory_percent || 0,100)}%"></i></div></td>
      <td>${portText(c.ports)}</td>
      <td><div class="image-text" title="${escapeHtml(c.image)}">${escapeHtml(c.image)}</div></td>
      <td><button class="kebab" type="button" title="More options">•••</button></td>
    </tr>`).join('')}
  `).join('') : '<tr><td colspan="7" class="empty">No matching containers.</td></tr>';
}

function groupedContainers(containers) {
  const groups = new Map();
  for (const c of containers) {
    const group = c.group_name || 'Ungrouped';
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(c);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === 'Ungrouped') - (b === 'Ungrouped') || a.localeCompare(b))
    .map(([name, groupContainers]) => ({ name, containers: groupContainers }));
}

function render(data) {
  currentData = data; settings = data.settings || settings;
  const s = data.server;
  $('metricContainers').textContent = s.containers_total;
  $('metricContainerDetail').textContent = `${s.containers_running} running · ${s.containers_stopped} stopped${s.containers_paused ? ` · ${s.containers_paused} paused` : ''}`;
  $('metricMemory').textContent = s.memory_total_human || bytes(s.memory_total);
  $('metricMemoryDetail').textContent = s.os || 'Docker host';
  $('metricCpu').textContent = s.cpus ?? '–';
  $('metricImages').textContent = s.images ?? '–';
  $('dockerVersion').textContent = `Docker ${s.docker_version || 'unknown'}`;
  $('lastUpdated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  $('dockerDetails').innerHTML = [
    ['Server', s.name], ['Operating system', s.os], ['Kernel', s.kernel], ['Docker Engine', s.docker_version], ['Docker API', s.api_version], ['CPU cores', s.cpus], ['Host memory', s.memory_total_human], ['Containers', s.containers_total], ['Images', s.images]
  ].map(([k,v]) => `<div class="detail"><span>${k}</span><strong>${escapeHtml(String(v ?? '—'))}</strong></div>`).join('');
  $('settingTitle').value = settings.title;
  $('settingRefresh').value = settings.refresh_seconds;
  $('settingConfirm').checked = settings.confirm_actions;
  $('brandTitle').textContent = settings.title;
  document.title = settings.title;
  renderOptionLists();
  renderContainers();
  scheduleRefresh();
}

async function refresh() {
  try { render(await api('/api/overview')); }
  catch (e) { $('containerRows').innerHTML = `<tr><td colspan="7" class="empty">${escapeHtml(e.message)}</td></tr>`; toast(e.message); }
}

function scheduleRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, (settings.refresh_seconds || 5) * 1000);
}

function actionsFor(c) {
  if (c.status === 'running') return ['restart','stop','pause'];
  if (c.status === 'paused') return ['unpause','restart','stop'];
  return ['start'];
}

window.openContainer = async function(id) {
  const c = currentData?.containers.find(x => x.id === id); if (!c) return;
  activeContainer = c;
  $('modalTitle').textContent = c.name;
  $('modalMeta').textContent = `${c.image} · ${c.status}`;
  $('modalActions').innerHTML = actionsFor(c).map(a => `<button class="btn ${a === 'stop' ? 'danger' : ''}" onclick="doAction('${a}')">${a[0].toUpperCase()+a.slice(1)}</button>`).join('');
  $('containerIconInput').value = containerIcon(c);
  setIconPreview(containerIcon(c));
  $('containerGroupInput').value = c.group_name || '';
  $('containerPrefsSaved').textContent = '';
  $('modal').classList.remove('hidden');
  await loadLogs({ forceBottom: true });
  scheduleLogRefresh();
}

function renderOptionLists() {
  $('dashboardIconOptions').innerHTML = DASHBOARD_ICONS.map(icon => `<option value="${icon}"></option>`).join('');
  const groups = [...new Set((currentData?.containers || []).map(c => c.group_name).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  $('containerGroupOptions').innerHTML = groups.map(group => `<option value="${escapeHtml(group)}"></option>`).join('');
}

function setIconPreview(icon) {
  const slug = icon || DEFAULT_CONTAINER_ICON;
  const preview = $('containerIconPreview');
  preview.onerror = () => preview.closest('.container-icon').classList.add('missing');
  preview.src = iconPath(slug);
  preview.closest('.container-icon').classList.remove('missing');
}

async function saveContainerPrefs(event) {
  event.preventDefault();
  if (!activeContainer) return;
  const icon = sanitizeIcon($('containerIconInput').value);
  const group_name = $('containerGroupInput').value.trim();
  try {
    const prefs = await api(`/api/containers/${activeContainer.id}/prefs`, {
      method: 'PUT',
      body: JSON.stringify({ icon, group_name }),
    });
    activeContainer.icon = prefs.icon;
    activeContainer.group_name = prefs.group_name;
    const existing = currentData.containers.find(c => c.id === activeContainer.id);
    if (existing) Object.assign(existing, prefs);
    $('containerIconInput').value = prefs.icon || DEFAULT_CONTAINER_ICON;
    setIconPreview(prefs.icon || DEFAULT_CONTAINER_ICON);
    $('containerGroupInput').value = prefs.group_name;
    $('containerPrefsSaved').textContent = 'Saved.';
    renderOptionLists();
    renderContainers();
    setTimeout(() => $('containerPrefsSaved').textContent = '', 1600);
  } catch (e) { toast(e.message); }
}

async function loadLogs({ forceBottom = false } = {}) {
  if (!activeContainer) return;
  const logsEl = $('modalLogs');
  const wasPinned = forceBottom || isLogPinnedToBottom(logsEl);
  setLogStatus('loading', 'Refreshing');
  try {
    const result = await api(`/api/containers/${activeContainer.id}/logs?tail=500`);
    renderLogs(result.logs || '', logsEl);
    if (wasPinned) logsEl.scrollTop = logsEl.scrollHeight;
    setLogStatus('current', `Updated ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    logsEl.innerHTML = `<div class="log-empty error">${escapeHtml(e.message)}</div>`;
    setLogStatus('stale', 'Update failed');
  }
}

function scheduleLogRefresh() {
  if (logRefreshTimer) clearTimeout(logRefreshTimer);
  if (!activeContainer || $('modal').classList.contains('hidden')) return;
  logRefreshTimer = setTimeout(async () => {
    await loadLogs();
    scheduleLogRefresh();
  }, 10000);
}

function setLogStatus(state, text) {
  const el = $('logStatus');
  el.className = `log-status ${state}`;
  el.querySelector('span').textContent = text;
}

function isLogPinnedToBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 36;
}

function renderLogs(raw, target) {
  const lines = raw.split(/\r?\n/).filter(line => line.length);
  if (!lines.length) {
    target.innerHTML = '<div class="log-empty">(No logs)</div>';
    return;
  }
  target.innerHTML = `<div class="log-table">${lines.map(line => {
    const entry = parseLogLine(line);
    return `<div class="log-row ${entry.levelClass}">
      <time>${escapeHtml(entry.timestamp)}</time>
      <span class="log-level">${escapeHtml(entry.level)}</span>
      <code>${escapeHtml(entry.message)}</code>
    </div>`;
  }).join('')}</div>`;
}

function parseLogLine(line) {
  const match = line.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\s*(.*)$/);
  const iso = match?.[1] || '';
  const message = (match?.[2] || line).trim();
  const level = detectLogLevel(message);
  return {
    timestamp: iso ? formatLogTime(iso) : 'No timestamp',
    level,
    levelClass: `level-${level.toLowerCase()}`,
    message: message || '(empty line)',
  };
}

function formatLogTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n, size = 2) => String(n).padStart(size, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

function detectLogLevel(message) {
  const patterns = [
    ['ERROR', /\b(error|fatal|critical|exception|traceback|failed|failure)\b/i],
    ['WARN', /\b(warn|warning|unauthorized|denied|refused)\b/i],
    ['INFO', /\b(info|started|running|listening|request|response|connected|complete)\b/i],
    ['DEBUG', /\b(debug|trace|verbose)\b/i],
  ];
  const explicit = message.match(/^\s*(?:\[[^\]]+\]\s*)?(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL)\b[:\]]?/i);
  if (explicit) return normalizeLogLevel(explicit[1]);
  for (const [level, pattern] of patterns) {
    if (pattern.test(message)) return level;
  }
  return 'LOG';
}

function normalizeLogLevel(level) {
  const value = level.toUpperCase();
  if (value === 'WARNING') return 'WARN';
  if (value === 'ERR' || value === 'FATAL' || value === 'CRITICAL') return 'ERROR';
  if (value === 'TRACE') return 'DEBUG';
  return value;
}

window.doAction = async function(action) {
  if (!activeContainer) return;
  if (settings.confirm_actions && !confirm(`${action.toUpperCase()} container “${activeContainer.name}”?`)) return;
  try {
    await api(`/api/containers/${activeContainer.id}/${action}`, { method:'POST', body:'{}' });
    toast(`${activeContainer.name}: ${action} sent`);
    await refresh();
    const updated = currentData.containers.find(c => c.id === activeContainer.id); if (updated) openContainer(updated.id); else closeModal();
  } catch (e) { toast(e.message); }
}

function closeModal(){
  $('modal').classList.add('hidden');
  activeContainer = null;
  if (logRefreshTimer) clearTimeout(logRefreshTimer);
}
$('modalClose').addEventListener('click', closeModal);
$('modal').addEventListener('click', e => { if (e.target === $('modal')) closeModal(); });
$('logRefreshBtn').addEventListener('click', () => loadLogs({ forceBottom: true }));
$('containerPrefsForm').addEventListener('submit', saveContainerPrefs);
$('containerIconInput').addEventListener('input', () => {
  setIconPreview(sanitizeIcon($('containerIconInput').value) || DEFAULT_CONTAINER_ICON);
});
$('refreshBtn').addEventListener('click', refresh);
$('containerSearch').addEventListener('input', renderContainers);

for (const btn of document.querySelectorAll('.nav-item[data-view]')) {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item[data-view]').forEach(x => x.classList.remove('active')); btn.classList.add('active');
    document.querySelectorAll('.view').forEach(x => x.classList.remove('active')); $(`${btn.dataset.view}View`).classList.add('active');
    const names = {dashboard:['Overview','Live Docker status'],docker:['Docker','Docker Engine information'],settings:['Settings','Configure this hub']};
    $('pageTitle').textContent = names[btn.dataset.view][0]; $('pageSubtitle').textContent = names[btn.dataset.view][1];
  });
}

$('settingsForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    settings = await api('/api/settings', { method:'PUT', body: JSON.stringify({ title:$('settingTitle').value, refresh_seconds:Number($('settingRefresh').value), confirm_actions:$('settingConfirm').checked }) });
    $('brandTitle').textContent = settings.title; document.title = settings.title; $('settingsSaved').textContent = 'Saved.'; scheduleRefresh();
    setTimeout(() => $('settingsSaved').textContent = '', 1800);
  } catch (err) { toast(err.message); }
});

function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }

refresh();
