'use strict';
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const paths = {
  overview:['Overview','Storage, workloads, and the things that need your attention.','chart'],
  storage:['Storage','Array disks, cache devices, parity, and capacity.','server'],
  shares:['Shares','Your shared data, space usage, and storage placement.','files'],
  docker:['Docker','Container state, application links, and workload controls.','box'],
  vms:['Virtual machines','Virtual machine state and lifecycle controls.','monitor'],
  services:['Services','All your apps and automation tools, in one place.','automation'],
  network:['Network','Interfaces, addressing, and link state.','network'],
  notifications:['Notifications','Server alerts and warnings that need attention.','bell'],
  plugins:['Plugins','Installed API modules and extension coverage.','puzzle'],
  tools:['Tools & coverage','Server tools and the feature parity checklist.','tool'],
  activity:['Activity','Confirmed server commands and their reported outcomes.','history'],
  settings:['Settings','Connection, access, and workspace preferences.','settings'],
};
const drawings = {
  chart:'M4 18V6M4 18h16M7 14l4-5 4 3 5-7', server:'M4 3h16v7H4zM4 14h16v7H4zM7 6h1M7 17h1',
  files:'M3 7h7l2 2h9v11H3zM3 7V4h7l2 3', box:'M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10',
  monitor:'M3 3h18v13H3zM12 16v5M8 21h8', automation:'M13 2L4 14h7l-1 8 10-12h-7z',
  network:'M9 3h6v6H9zM2 16h6v6H2zM16 16h6v6h-6zM12 9v4M5 16v-3h14v3',
  bell:'M5 16h14l-2-3V8a5 5 0 0 0-10 0v5zM10 20h4', puzzle:'M4 4h5a3 3 0 1 1 6 0h5v5a3 3 0 1 0 0 6v5H4z',
  tool:'M14 3a6 6 0 0 0-7 7l-5 8 4 4 8-8a6 6 0 0 0 7-7l-4 3-3-3z', history:'M3 8a9 9 0 1 1 0 8M3 3v5h5M12 7v5l3 2',
  settings:'M4 5h16M4 12h16M4 19h16M8 3v4M16 10v4M10 17v4',
  media:'M4 3h16v18H4zM9 8l7 4-7 4z', shield:'M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6zM8 11l3 3 5-6',
  backup:'M4 8a8 8 0 1 1-1 7M3 3v5h5M12 7v5l4 2',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${drawings[name] || drawings.server}"/></svg>`;
let page = location.pathname.slice(1) || 'overview';
if (!paths[page]) page = 'overview';
let settings = {}, samples = {}, tiles = [], capabilities = {actions:[], controls_enabled:false};
let accessSetup = false, busy = false, pendingConfirmation = null, editingTile = null;
let readings = [], search = '';
function applyTheme(theme) { document.body.dataset.theme = theme === 'dark' ? 'dark' : 'paper'; }
const needed = {
  overview:['system','metrics','storage','docker','notifications'], storage:['storage'], docker:['docker'],
  vms:['vms'], shares:['shares'], network:['network'], notifications:['notifications'], plugins:['plugins'], services:['docker'],
};
function safeLink(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
  catch (_) { return ''; }
}
function nativeUrl(path = '') {
  const url = safeLink(settings.url);
  return url ? new URL('/' + path, url).href : '';
}
async function api(path, options = {}) {
  const response = await fetch('/api/' + path, {...options, headers:{'Content-Type':'application/json', ...options.headers}});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && !$('accessDialog').open) await checkAccess();
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the submitted values.');
  }
  return data;
}
const send = (path, method, body) => api(path, {method, body:JSON.stringify(body)});
function patch(node, html) { if (node.innerHTML !== html) node.innerHTML = html; }
function bytes(value, multiplier = 1) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  let number = Number(value) * multiplier, unit = 0;
  while (number >= 1024 && unit < 5) { number /= 1024; unit++; }
  return `${number.toFixed(unit ? 1 : 0)} ${['B','KiB','MiB','GiB','TiB','PiB'][unit]}`;
}
const percent = value => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(1);
function badge(value) {
  const status = String(value ?? 'Unknown');
  const good = /^(running|started|disk_ok|up|online|active)$/i.test(status);
  const bad = /error|unhealthy|disabled|missing|alert/i.test(status);
  return `<span class="badge ${good ? 'good' : bad ? 'bad' : ''}">${escape(status.replaceAll('_',' ').toLowerCase())}</span>`;
}
function stamp(section) {
  const sample = samples[section];
  if (!sample) return 'Loading readings…';
  return sample.error ? `${sample.stale ? 'Stale data · ' : ''}${sample.error}` : `Sampled ${new Date(sample.sampled_at * 1000).toLocaleTimeString()} · refresh every 10 s`;
}
function panel(title, body, section, extra = '') {
  return `<article class="panel"><div class="panel-head"><h2>${escape(title)}</h2>${extra}</div>${body}<div class="status-line ${samples[section]?.stale ? 'stale' : ''}">${escape(stamp(section))}</div></article>`;
}
const empty = message => `<div class="empty">${escape(message)}</div>`;
function commands(prefix, target, actions) {
  return actions.map(action => {
    const operation = prefix + '.' + action;
    return `<button class="button" data-operation="${escape(operation)}" data-target="${escape(target || '')}" ${capabilities.controls_enabled && capabilities.actions.includes(operation) ? '' : 'disabled'} title="${capabilities.controls_enabled ? 'Available when supported by your API and key permissions' : 'Enable server controls in Settings'}">${escape(action[0].toUpperCase() + action.slice(1))}</button>`;
  }).join('');
}
function workloadRows(limit) {
  const containers = samples.docker?.data?.containers || [];
  return containers.slice(0, limit).map(c => `<div class="row"><div class="row-start"><span class="row-icon">${icon('box')}</span><div class="row-title">${escape((c.names || []).join(', ').replace(/^\//,''))}<small>${escape(c.image)}</small></div></div>${badge(c.state)}</div>`).join('') || empty('No containers reported.');
}
function alerts(limit = 100) {
  return (samples.notifications?.data?.list || []).slice(0, limit).map(n => `<div class="row"><div><span class="row-title ${n.importance === 'ALERT' ? 'alert-title' : ''}">${escape(n.title)}</span><small>${escape(n.subject)}</small><p class="section-description">${escape(n.description)}</p></div><div>${badge(n.importance)}${page === 'notifications' ? commands('notification', n.id, ['archive']) : ''}</div></div>`).join('') || empty('No unread notifications reported.');
}
function cpuChart(metrics) {
  const series = ControlMetrics.cpuSeries(readings, Date.now()/1000);
  const width = window.innerWidth <= 760 ? 340 : 760;
  const x = point => 40+(point.x-40)/700*(width-60);
  const ticks = [0,25,50,75,100].map(value => {
    const y = 12+(100-value)/100*126;
    return `<line class="chart-grid" x1="40" y1="${y}" x2="${width-20}" y2="${y}"/><text class="chart-axis" x="2" y="${y+4}">${value}%</text>`;
  }).join('');
  const plotted = series.segments.map(segment => {
    const points = segment.map(point => `${x(point)},${point.y}`).join(' ');
    const first = segment[0], last = segment.at(-1);
    return `${segment.length > 1 ? `<polygon class="chart-area" points="${x(first)},138 ${points} ${x(last)},138"/><polyline class="chart-line" points="${points}"/>` : ''}<circle class="chart-point" cx="${x(last)}" cy="${last.y}" r="3"/>`;
  }).join('');
  const chart = `<svg class="cpu-chart" viewBox="0 0 ${width} 164" role="img" aria-label="CPU utilization over the last five minutes, fixed zero to one hundred percent scale; ${series.count} samples">${ticks}${plotted}<text class="chart-axis" x="40" y="160">5 min ago</text><text class="chart-axis" x="${width/2-10}" y="160">2.5 min ago</text><text class="chart-axis" x="${width-54}" y="160">Now</text></svg>`;
  const cores = (metrics.cpu?.cpus || []).map((core,index) => `<div class="cpu-core"><span>Thread ${index+1}</span><strong>${percent(core.percentTotal)}%</strong><div class="meter"><div class="meter-fill" data-width="${ControlMetrics.number(core.percentTotal) || 0}"></div></div></div>`).join('');
  return panel('CPU activity', `<div class="panel-body">${chart}<div class="chart-caption"><span>${series.count < 2 ? 'Collecting samples — the chart grows every 10 seconds.' : `${series.count} readings · gaps indicate unavailable samples`}</span><span>Last 5 minutes · browser session</span></div>${cores ? `<div class="cpu-cores">${cores}</div>` : ''}</div>`, 'metrics', '<span class="metric-tag">LIVE / 10 SEC</span>');
}
function rememberCpuReadings() {
  try { sessionStorage.setItem('control-cpu:' + settings.url, JSON.stringify(readings)); } catch (_) {}
}
function loadCpuReadings() {
  try {
    const saved = JSON.parse(sessionStorage.getItem('control-cpu:' + settings.url) || '[]');
    readings = Array.isArray(saved) ? saved.filter(point => point && Number.isFinite(point.stamp) && Number.isFinite(point.value) && point.stamp >= Date.now()/1000-300).slice(-120) : [];
  } catch (_) { readings = []; }
}
function overview() {
  const system = samples.system?.data || {}, metrics = samples.metrics?.data || {}, storage = samples.storage?.data || {};
  const capacity = storage.capacity?.kilobytes || {};
  const total = Number(capacity.total), used = Number(capacity.used);
  const ratio = capacity.total != null && capacity.used != null && total > 0 ? used / total * 100 : null;
  const containers = samples.docker?.data?.containers || [];
  const memory = ControlMetrics.memorySummary(metrics.memory, system.memory?.layout);
  return `<div class="stats"><article class="stat stat-cpu"><div class="stat-label">CPU utilization</div><div class="stat-value">${percent(metrics.cpu?.percentTotal)}<small>%</small></div><div class="stat-caption">${escape(system.cpu?.brand || 'Hardware details unavailable')}</div></article><article class="stat stat-memory"><div class="stat-label">Memory in use</div><div class="stat-value">${bytes(memory.used)}</div><div class="stat-caption">${percent(memory.percentage)}% of ${bytes(memory.total)} usable</div><div class="meter" role="progressbar" aria-label="Memory in use" aria-valuemin="0" aria-valuemax="100" ${memory.percentage === null ? 'aria-valuetext="Unavailable"' : `aria-valuenow="${memory.percentage.toFixed(1)}"`}><div class="meter-fill" data-width="${memory.percentage || 0}"></div></div><div class="stat-detail">${memory.installed ? `${bytes(memory.installed)} installed &middot; ` : ''}${bytes(memory.available)} available</div>${memory.cache === null ? '' : `<div class="stat-detail">${bytes(memory.cache)} buffer/cache &middot; reclaimable memory included in available</div>`}</article><article class="stat stat-storage"><div class="stat-label">Array capacity</div><div class="stat-value">${bytes(capacity.free,1024)}</div><div class="stat-caption">Free of ${bytes(capacity.total,1024)}</div><div class="meter"><div class="meter-fill" data-width="${ratio || 0}"></div></div></article><article class="stat stat-docker"><div class="stat-label">Docker workloads</div><div class="stat-value">${samples.docker?.data ? containers.filter(c => String(c.state).toLowerCase() === 'running').length : '—'}<small>/ ${containers.length}</small></div><div class="stat-caption">Running containers · API state</div></article></div>
  ${cpuChart(metrics)}<div class="columns"><div>${panel('Storage at a glance', `<div class="panel-body">${badge(storage.state)}<div class="storage-track"><div class="storage-fill" data-width="${ratio || 0}"></div></div><div class="row"><div class="row-title">${bytes(capacity.used,1024)} used<small>${bytes(capacity.free,1024)} available</small></div><a class="button" href="/storage" data-page="storage">Inspect storage →</a></div><div class="row"><span class="muted">Parity verification</span>${badge(storage.parityCheckStatus?.status)}</div></div>`, 'storage')}${panel('Workloads', `<div class="panel-body">${workloadRows(5)}</div>`, 'docker', '<a class="link-button" href="/docker" data-page="docker">View all →</a>')}</div><div>${panel('Needs attention', `<div class="panel-body">${alerts(4)}</div>`, 'notifications', '<a class="link-button" href="/notifications" data-page="notifications">All notifications →</a>')}${panel('Server details', `<div class="panel-body"><div class="row"><span class="muted">Hostname</span>${escape(system.os?.hostname || '—')}</div><div class="row"><span class="muted">Unraid version</span>${escape(system.versions?.unraid || system.os?.release || '—')}</div><div class="row"><span class="muted">Processor</span>${escape(system.cpu?.cores ?? '—')} cores / ${escape(system.cpu?.threads ?? '—')} threads</div><div class="row"><span class="muted">Uptime</span>${escape(system.os?.uptime || '—')}</div></div>`, 'system')}</div></div>`;
}
function storagePage() {
  const array = samples.storage?.data;
  if (!array) return panel('Storage', empty('Waiting for an array reading. Connect your server in Settings.'), 'storage');
  const table = disks => `<div class="table-wrap"><table><thead><tr><th>Device</th><th>State</th><th>Capacity</th><th>Used / Free</th><th>Temperature</th><th>Errors</th></tr></thead><tbody>${disks.map(d => `<tr><td>${escape(d.name || d.id)}<small>${escape(d.device || '—')} · ${escape(d.fsType || '—')}</small></td><td>${badge(d.status)}</td><td>${bytes(d.size,1024)}</td><td>${bytes(d.fsUsed,1024)} / ${bytes(d.fsFree,1024)}</td><td>${d.temp == null ? '—' : escape(d.temp) + ' °C'}</td><td>${escape(d.numErrors ?? '—')}</td></tr>`).join('')}</tbody></table></div>`;
  const parity = array.parityCheckStatus || {};
  return panel('Array operations', `<div class="panel-body"><div class="row">${badge(array.state)}<div class="row-actions">${commands('array', '', array.state === 'STARTED' ? ['stop'] : array.state === 'STOPPED' ? ['start'] : [])}</div></div><p class="section-description">Array stops interrupt dependent workloads. Disk assignment, formatting, and filesystem repair remain in the native WebUI.</p><div class="row"><div class="row-title">Parity verification<small>${escape(parity.progress ?? '—')}% · ${escape(parity.errors ?? '—')} errors · ${escape(parity.speed ?? '—')} MB/s</small></div>${badge(parity.status)}</div><div class="row-actions">${commands('parity', '', parity.running ? parity.paused ? ['resume','cancel'] : ['pause','cancel'] : ['start'])}</div></div>`, 'storage') +
    [['Array disks',array.disks],['Parity devices',array.parities],['Cache / pools',array.caches],['Boot device',array.boot ? [array.boot] : []]].map(([title,disks]) => panel(title, disks?.length ? table(disks) : empty('No devices reported.'), 'storage')).join('');
}
function dockerPage() {
  const containers = (samples.docker?.data?.containers || []).filter(c => `${c.names} ${c.image}`.toLowerCase().includes(search));
  return panel('Container workloads', containers.length ? `<div class="panel-body">${containers.map(c => {
    const state = String(c.state).toLowerCase(), url = safeLink(c.webUiUrl);
    return `<div class="row"><div class="row-start"><span class="row-icon">${icon('box')}</span><div class="row-title">${escape((c.names || []).join(', ').replace(/^\//,''))}<small>${escape(c.image)}</small><small>Autostart: ${c.autoStart ? 'on' : 'off'}${c.isUpdateAvailable ? ' · Update available' : ''}</small></div></div><div class="row-actions">${badge(c.state)}${url ? `<a class="button" href="${escape(url)}" target="_blank" rel="noreferrer">Web UI ↗</a>` : ''}${commands('docker', c.id, state === 'running' ? ['stop','restart','pause'] : state === 'paused' ? ['unpause','stop'] : ['start'])}</div></div>`;
  }).join('')}</div>` : empty('No matching containers. API access or Docker may be unavailable.'), 'docker');
}
function vmsPage() {
  const domains = (samples.vms?.data?.domains || []).filter(d => `${d.name} ${d.state}`.toLowerCase().includes(search));
  return panel('Virtual machines', domains.length ? `<div class="panel-body">${domains.map(d => `<div class="row"><div class="row-start"><span class="row-icon">${icon('monitor')}</span><div class="row-title">${escape(d.name)}<small>${escape(d.id)}</small></div></div><div class="row-actions">${badge(d.state)}${commands('vm', d.id, String(d.state).toLowerCase() === 'running' ? ['stop','reboot','pause'] : String(d.state).toLowerCase() === 'paused' ? ['resume','stop'] : ['start'])}</div></div>`).join('')}</div>` : empty('No virtual machines reported.'), 'vms') + nativeNote('VM editing, passthrough, console access, and snapshots', 'VMs');
}
function sharesPage() {
  const shares = (samples.shares?.data || []).filter(s => `${s.name} ${s.comment}`.toLowerCase().includes(search));
  return panel('User shares', shares.length ? `<div class="table-wrap"><table><thead><tr><th>Share</th><th>Used</th><th>Free</th><th>Cached</th><th>Placement</th></tr></thead><tbody>${shares.map(s => `<tr><td>${escape(s.name)}<small>${escape(s.comment || '')}</small></td><td>${bytes(s.used,1024)}</td><td>${bytes(s.free,1024)}</td><td>${s.cache == null ? '—' : s.cache ? 'Yes' : 'No'}</td><td>${escape(s.allocator || '—')}<small>Include: ${escape((s.include || []).join(', ') || 'default')} · Exclude: ${escape((s.exclude || []).join(', ') || 'none')}</small></td></tr>`).join('')}</tbody></table></div>` : empty('No shares reported.'), 'shares') + nativeNote('Share creation, permissions, SMB/NFS, primary/secondary storage, and Mover policy', 'Shares');
}
function networkPage() {
  return panel('Network interfaces', `<div class="table-wrap"><table><thead><tr><th>Interface</th><th>Link</th><th>Address</th><th>Speed</th><th>MTU</th></tr></thead><tbody>${(samples.network?.data || []).map(n => `<tr><td>${escape(n.name)}<small>${escape(n.macAddress || '')}${n.virtual ? ' · virtual' : ''}</small></td><td>${badge(n.operstate)}</td><td>${escape(n.ipAddress || '—')}<small>Gateway: ${escape(n.gateway || '—')}</small></td><td>${n.speed == null ? '—' : escape(n.speed) + ' Mbps'}</td><td>${escape(n.mtu ?? '—')}</td></tr>`).join('')}</tbody></table></div>`, 'network') + nativeNote('Network configuration, bonding, VLANs, DNS, and WireGuard', 'Settings');
}
function nativeNote(feature, route) {
  return `<article class="panel"><div class="panel-body"><h3>${escape(feature)}</h3><p class="section-description">Native implementation is still planned. Use Unraid's own interface for these operations in this preview.</p>${nativeUrl(route) ? `<a class="button" href="${escape(nativeUrl(route))}" target="_blank" rel="noreferrer">Open Unraid ${escape(route)} ↗</a>` : '<a class="button" href="/settings" data-page="settings">Connect your server</a>'}</div></article>`;
}
function servicesPage() {
  const containers = samples.docker?.data?.containers || [];
  const cards = [...containers.filter(c => safeLink(c.webUiUrl)).map(c => ({name:(c.names || []).join(', ').replace(/^\//,''), url:c.webUiUrl, icon:'box', group:'Docker apps', status:c.state})), ...tiles.filter(t => t.enabled).map(t => ({...t,status:'Saved link'}))].filter(t => `${t.name} ${t.group}`.toLowerCase().includes(search));
  return `<div class="page-actions"><button class="button primary" id="addTile">+ Add tile</button><span class="muted">Custom tiles are links; availability is not monitored.</span></div><br><div class="service-grid">${cards.map(t => `<article class="service-tile"><a class="tile-main" href="${escape(safeLink(t.url))}" target="_blank" rel="noreferrer"><span class="row-icon">${icon(t.icon)}</span><div><h3>${escape(t.name)}</h3><p class="muted">${escape(t.group)}</p></div></a><div class="tile-footer">${badge(t.status)}${t.id ? `<button class="link-button" data-tile="${escape(t.id)}">Edit tile</button>` : '<span class="muted">Discovered from Unraid</span>'}</div></article>`).join('') || empty('No service links yet. Add your first tile.')}</div>`;
}
function settingsPage() {
  return `<article class="panel"><div class="panel-head"><h2>Server connection & workspace</h2><span class="badge">Settings persist under /data</span></div><div class="panel-body"><form id="settingsForm" class="settings-form"><h3 id="appearanceSettings">Appearance</h3><label>Theme<select name="theme" id="appearanceTheme"><option value="paper" ${settings.theme !== 'dark' ? 'selected' : ''}>Artcraft-inspired light</option><option value="dark" ${settings.theme === 'dark' ? 'selected' : ''}>Dark</option></select></label><p class="section-description">Preview changes immediately. Save settings to keep your theme after reload and container restart.</p><h3>Server connection</h3><div class="settings-grid"><label>Workspace title<input name="title" value="${escape(settings.title || 'Unraid Control')}" maxlength="80" required></label><label>Unraid server URL<input name="url" type="url" value="${escape(settings.url || '')}" placeholder="http://tower.local" maxlength="500"></label></div><label>Unraid API key<input name="api_key" type="password" autocomplete="new-password" maxlength="2000" placeholder="${settings.api_key_configured ? 'Saved key · leave blank to keep' : 'Paste an API key'}"></label><label class="checkbox"><input name="clear_api_key" type="checkbox"> Clear saved API key</label><label class="checkbox"><input name="enabled" type="checkbox" ${settings.enabled ? 'checked' : ''}> Enable Unraid connection</label><label class="checkbox"><input name="controls_enabled" type="checkbox" ${settings.controls_enabled ? 'checked' : ''}> Enable confirmed server controls</label><label class="checkbox"><input name="login_required" type="checkbox" ${settings.login_required !== false ? 'checked' : ''}> Require local password login</label><label>Homelab Hub URL (optional)<input name="homelab_url" type="url" value="${escape(settings.homelab_url || '')}" placeholder="http://server:3333"></label><p class="section-description">Unraid 7.2.3 target. The API key stays on the backend. Blank key fields preserve it; clear explicitly to remove it. Schema discovery detects installed API fields. Homelab is a separate integration target in this preview.</p><div class="page-actions"><button class="button primary" type="submit">Save settings</button><button class="button" id="reconnect" type="button">Test & reconnect</button></div><p id="settingsMessage" class="settings-message" role="status"></p></form></div></article>`;
}
function toolsPage() {
  return `<article class="panel"><div class="panel-head"><h2>Feature coverage</h2><span class="badge warn">Preview · parity incomplete</span></div><div class="panel-body"><p class="section-description">This is an original interface backed by supported API contracts. Features are marked by actual implementation coverage, not by the presence of a navigation tab.</p><div class="row"><span class="row-title">Native readings & confirmed controls<small>Storage, parity verification, Docker lifecycle, VM lifecycle, share inventory, network interfaces, notifications.</small></span>${badge('Implemented')}</div><div class="row"><span class="row-title">Homelab enhancements<small>Custom service tiles and icons, optional local login, command navigation, independent polling, stale-data status, audit activity.</small></span>${badge('Implemented')}</div><div class="row"><span class="row-title">Full Unraid configuration<small>Disk assignment and formatting, pools/ZFS, SMART tests, share editing, users, Docker templates, VM hardware, plugin management, OS updates, terminal and file manager.</small></span>${badge('Planned')}</div><div class="row"><span class="row-title">Homelab feature migration<small>Zigbee/MQTT, occupancy and solar automations, persistent metrics history, branding and connector cards.</small></span>${badge('Planned')}</div></div></article><article class="panel"><div class="panel-head"><h2>Native tools during migration</h2></div><div class="panel-body native-tools">${[['Main','Storage & disk operations'],['Users','Users & permissions'],['Settings','System configuration'],['Plugins','Plugin management'],['Apps','Community applications'],['Tools','Diagnostics, updates & maintenance']].map(([route,label]) => nativeUrl(route) ? `<a href="${escape(nativeUrl(route))}" target="_blank" rel="noreferrer">${label} ↗<small>Opens the native Unraid WebUI</small></a>` : '').join('') || empty('Connect a server to open its native tools.')}</div></article>`;
}
function render() {
  if (page === 'settings' && $('settingsForm')) return;
  const views = {overview, storage:storagePage, docker:dockerPage, vms:vmsPage, shares:sharesPage,
    network:networkPage, services:servicesPage, settings:settingsPage, tools:toolsPage,
    notifications:() => panel('Unread notifications', `<div class="panel-body">${alerts()}</div>`, 'notifications'),
    plugins:() => panel('API plugins', `<div class="panel-body">${(samples.plugins?.data || []).map(p => `<div class="row"><span class="row-title">${escape(p.name)}<small>${escape(p.version)}</small></span>${badge(p.hasApiModule ? 'API module' : 'Plugin')}</div>`).join('') || empty('No API plugins reported. This list is not the complete .plg inventory.')}</div>`, 'plugins') + nativeNote('Installing, updating, and removing Unraid plugins', 'Plugins'),
    activity:() => '<div class="empty">Loading activity…</div>'};
  patch($('results') || $('content'), views[page]());
  document.querySelectorAll('[data-width]').forEach(node => { node.style.width = Math.max(0,Math.min(100,Number(node.dataset.width))) + '%'; });
  const errors = (needed[page] || []).filter(k => samples[k]?.error).map(k => `${k}: ${samples[k].error}`);
  $('notice').hidden = !errors.length;
  $('notice').textContent = errors.join(' · ');
  const successful = Object.values(samples).filter(s => s.data != null && !s.error);
  document.body.classList.toggle('connected', successful.length > 0 && settings.enabled);
  $('connectionLabel').textContent = successful.length && settings.enabled ? 'Server readings available' : 'Not connected';
  $('footerStatus').textContent = successful.length ? `${successful.length} sections sampled · API connection` : 'No server data loaded';
}
function navigate(target, historyMode = true) {
  if (!paths[target]) return;
  page = target; search = ''; applyTheme(settings.theme);
  if (historyMode) history.pushState({}, '', '/' + (page === 'overview' ? '' : page));
  document.querySelectorAll('.nav-link').forEach(node => node.classList.toggle('active', node.dataset.page === page));
  $('breadcrumb').textContent = 'Server / ' + paths[page][0];
  $('pageTitle').textContent = paths[page][0]; $('pageDescription').textContent = paths[page][1];
  document.title = paths[page][0] + ' · ' + (settings.title || 'Unraid Control');
  $('sidebar').classList.remove('open');
  $('content').innerHTML = ['docker','vms','shares','services'].includes(page) ? '<label class="sr-only" for="sectionSearch">Search this section</label><input id="sectionSearch" class="filter" placeholder="Search this section…"><div id="results"></div>' : '';
  render(); refresh();
}
async function refresh(fresh = false) {
  if (busy || $('accessDialog').open) return;
  busy = true; const target = page;
  try {
    if (target === 'activity') {
      const data = await api('audit');
      if (page === target) patch($('content'), `<article class="panel"><div class="panel-head"><h2>Server command activity</h2></div><div class="panel-body">${data.events.map(e => `<div class="row"><div class="row-title">${escape(e.operation)}<small>${escape(e.target)} · ${new Date(e.time*1000).toLocaleString()}</small></div><span class="muted">${escape(e.outcome)}</span></div>`).join('') || empty('No server commands have been sent.')}</div></article>`);
      return;
    }
    await Promise.all((needed[target] || []).map(async section => {
      samples[section] = await api('sections/' + section + (fresh ? '?fresh=true' : ''));
      if (section === 'metrics' && samples[section].data?.cpu?.percentTotal != null && !samples[section].error) {
        const last = readings.at(-1);
        if (last?.stamp !== samples[section].sampled_at) readings.push({stamp:samples[section].sampled_at, value:samples[section].data.cpu.percentTotal});
        readings = readings.filter(point => point.stamp >= Date.now()/1000-300).slice(-120);
        rememberCpuReadings();
      }
    }));
    capabilities = await api('capabilities');
    if (page === target) render();
    $('refreshLabel').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (error) { $('notice').hidden = false; $('notice').textContent = error.message; }
  finally { busy = false; if (page !== target) refresh(); }
}
async function checkAccess() {
  const access = await api('access');
  if (access.theme) applyTheme(access.theme);
  accessSetup = access.setup;
  if (!access.authenticated) {
    $('accessTitle').textContent = accessSetup ? 'Welcome to Control' : 'Sign in';
    $('accessHelp').textContent = accessSetup ? 'Create the local administrator password for this independent workspace.' : 'Enter your Control administrator password.';
    $('accessPassword').autocomplete = accessSetup ? 'new-password' : 'current-password';
    $('accessDialog').showModal();
  }
  return access.authenticated;
}
async function start() {
  if (!await checkAccess()) return;
  [settings, {tiles}] = await Promise.all([api('settings'), api('tiles')]);
  applyTheme(settings.theme);
  loadCpuReadings();
  const native = nativeUrl(); $('nativeLink').hidden = !native; if (native) $('nativeLink').href = native;
  navigate(page, false);
}
function openTile(id = null) {
  editingTile = tiles.find(t => t.id === id) || null;
  $('tileForm').reset(); $('tileError').textContent = '';
  $('tileTitle').textContent = editingTile ? 'Edit service tile' : 'Add service tile';
  $('tileName').value = editingTile?.name || ''; $('tileUrl').value = editingTile?.url || '';
  $('tileGroup').value = editingTile?.group || 'Services'; $('tileIcon').value = editingTile?.icon || 'server';
  $('tileEnabled').checked = editingTile?.enabled ?? true; $('tileDelete').hidden = !editingTile;
  $('tileDialog').showModal();
}
document.addEventListener('click', async event => {
  const nav = event.target.closest('[data-page]');
  if (nav && !event.ctrlKey && !event.metaKey && !event.shiftKey) { event.preventDefault(); navigate(nav.dataset.page); }
  const closer = event.target.closest('[data-close]'); if (closer) $(closer.dataset.close).close();
  if (event.target.closest('#addTile')) openTile();
  const tile = event.target.closest('[data-tile]'); if (tile) openTile(tile.dataset.tile);
  const command = event.target.closest('[data-operation]');
  if (command) {
    command.disabled = true;
    try {
      pendingConfirmation = await send('actions/prepare', 'POST', {operation:command.dataset.operation, target:command.dataset.target});
      $('confirmationName').textContent = command.dataset.operation + (command.dataset.target ? ' · ' + command.dataset.target : '');
      $('confirmationImpact').textContent = pendingConfirmation.impact;
      $('confirmationText').placeholder = pendingConfirmation.confirmation;
      $('confirmationText').value = ''; $('confirmationError').textContent = '';
      $('confirmationDialog').showModal();
    } catch (error) { $('notice').hidden = false; $('notice').textContent = error.message; }
    finally { command.disabled = false; }
  }
  if (event.target.closest('#reconnect')) {
    try { capabilities = await send('reconnect','POST',{}); $('settingsMessage').textContent = 'Connected. ' + capabilities.actions.length + ' API operations detected.'; }
    catch (error) { $('settingsMessage').textContent = error.message; }
  }
});
document.addEventListener('input', event => {
  if (event.target.id === 'sectionSearch') { search = event.target.value.toLowerCase(); render(); }
});
document.addEventListener('change', event => { if (event.target.name === 'theme') applyTheme(event.target.value); });
document.addEventListener('submit', async event => {
  if (event.target.id !== 'settingsForm') return;
  event.preventDefault(); const form = event.target, button = form.querySelector('[type=submit]'); button.disabled = true;
  const data = new FormData(form), body = Object.fromEntries(data);
  for (const key of ['clear_api_key','enabled','controls_enabled','login_required']) body[key] = data.has(key);
  try { const previousUrl = settings.url; settings = await send('settings','PUT',body); applyTheme(settings.theme); if (settings.url !== previousUrl) loadCpuReadings(); samples = {}; capabilities = {actions:[],controls_enabled:false};
    const native = nativeUrl(); $('nativeLink').hidden = !native; if (native) $('nativeLink').href = native;
    form.querySelector('[name=api_key]').value = ''; form.querySelector('[name=clear_api_key]').checked = false;
    $('settingsMessage').textContent = 'Settings saved. Test & reconnect to verify the server.'; await checkAccess();
  } catch (error) { $('settingsMessage').textContent = error.message; }
  finally { button.disabled = false; }
});
$('accessForm').onsubmit = async event => {
  event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
  try { await send(accessSetup ? 'setup' : 'login', 'POST', {password:$('accessPassword').value}); $('accessPassword').value = ''; $('accessError').textContent = ''; $('accessDialog').close(); await start(); }
  catch (error) { $('accessError').textContent = error.message; }
  finally { button.disabled = false; }
};
$('accessDialog').addEventListener('cancel', event => event.preventDefault());
$('confirmationForm').onsubmit = async event => {
  event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
  try { await send('actions/execute','POST',{token:pendingConfirmation.token, confirmation:$('confirmationText').value}); $('confirmationDialog').close(); $('refreshLabel').textContent = 'Command accepted · checking state…'; await refresh(true); }
  catch (error) { $('confirmationError').textContent = error.message + ' Check server state before retrying.'; }
  finally { button.disabled = false; }
};
$('tileForm').onsubmit = async event => {
  event.preventDefault(); const button = event.target.querySelector('[type=submit]'); button.disabled = true;
  const tile = {id:editingTile?.id || Date.now().toString(36) + Math.random().toString(36).slice(2), name:$('tileName').value.trim(),
    url:$('tileUrl').value.trim(), group:$('tileGroup').value.trim(), icon:$('tileIcon').value, enabled:$('tileEnabled').checked};
  if (!safeLink(tile.url)) { $('tileError').textContent = 'Use an http(s) URL without embedded credentials.'; button.disabled = false; return; }
  try { ({tiles} = await send('tiles','PUT',{tiles:[...tiles.filter(t => t.id !== tile.id),tile]})); $('tileDialog').close(); render(); }
  catch (error) { $('tileError').textContent = error.message; }
  finally { button.disabled = false; }
};
$('tileDelete').onclick = async () => {
  if (!editingTile || !confirm('Delete this saved tile?')) return;
  try { ({tiles} = await send('tiles','PUT',{tiles:tiles.filter(t => t.id !== editingTile.id)})); $('tileDialog').close(); render(); }
  catch (error) { $('tileError').textContent = error.message; }
};
$('tilePreset').onchange = () => {
  const name = $('tilePreset').value; if (!name) return;
  $('tileName').value = name;
  const lookup = {'Unraid':['server',nativeUrl()], 'Homelab Hub':['server',settings.homelab_url],
    'Automations':['automation',settings.homelab_url ? new URL('/automations',settings.homelab_url).href : ''],
    'Home Assistant':['automation',''], 'Node-RED':['automation',''], 'Uptime Kuma':['chart',''],
    'Grafana':['chart',''], 'Backups':['backup',''], 'Files':['files',''], 'Network controller':['network','']};
  const [symbol,url] = lookup[name] || ['server','']; $('tileIcon').value = symbol; $('tileUrl').value = url || '';
};
$('navigation').innerHTML = Object.entries(paths).map(([key,[title,,symbol]]) => `<a class="nav-link" data-page="${key}" href="/${key === 'overview' ? '' : key}">${icon(symbol)}${title}</a>`).join('');
$('menuToggle').onclick = () => $('sidebar').classList.toggle('open');
$('logout').onclick = async () => { await send('logout','POST',{}); await checkAccess(); };
$('refresh').onclick = () => refresh(true);
function commandResults() {
  const value = $('commandSearch').value.toLowerCase();
  $('commandResults').innerHTML = Object.entries(paths).filter(([key,[title]]) => `${key} ${title}`.toLowerCase().includes(value)).map(([key,[title,,symbol]]) => `<a class="command-result" data-page="${key}" href="/${key}">${icon(symbol)}${title}</a>`).join('');
}
function openCommands() { $('commandSearch').value = ''; commandResults(); $('commandDialog').showModal(); $('commandSearch').focus(); }
$('commandOpen').onclick = openCommands; $('commandSearch').oninput = commandResults;
$('commandResults').onclick = event => { if (event.target.closest('[data-page]')) $('commandDialog').close(); };
document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openCommands(); } });
window.addEventListener('popstate', () => navigate(location.pathname.slice(1) || 'overview',false));
window.addEventListener('resize', () => { if (page === 'overview') render(); });
setInterval(() => { if (!document.hidden) refresh(); }, 10000);
start().catch(error => { $('notice').hidden = false; $('notice').textContent = error.message; });
