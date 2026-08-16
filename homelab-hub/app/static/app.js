let currentData = null;
let settings = { title: 'Homelab Hub', refresh_seconds: 5, confirm_actions: true };
let refreshTimer = null;
let logRefreshTimer = null;
let activeContainer = null;
let dashboardIcons = [];
let collapsedGroups = new Set(JSON.parse(localStorage.getItem('collapsedGroups') || '[]'));
const DEFAULT_SECTION_ORDER = ['summary', 'server', 'webui', 'ports', 'containers'];
let collapsedSections = new Set(JSON.parse(localStorage.getItem('collapsedSections') || '[]'));
if (localStorage.getItem('containersSectionCollapsed') === 'true') collapsedSections.add('containers');
let sectionOrder = JSON.parse(localStorage.getItem('overviewSectionOrder') || '[]').filter(id => DEFAULT_SECTION_ORDER.includes(id));
sectionOrder = [...sectionOrder, ...DEFAULT_SECTION_ORDER.filter(id => !sectionOrder.includes(id))];

const $ = (id) => document.getElementById(id);
const DEFAULT_CONTAINER_ICON = 'docker';

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

function monitorStatus(c) {
  if (c.status === 'running' && c.health === 'healthy') return { label: 'Healthy', kind: 'ok', info: 'Running and Docker health check is passing.' };
  if (c.status === 'running' && c.health === 'unhealthy') return { label: 'Attention', kind: 'attention', info: 'Running, but Docker reports an unhealthy health check.' };
  if (c.status === 'running' && c.health === 'starting') return { label: 'Starting', kind: 'pending', info: 'Running, but the health check is still warming up.' };
  if (c.status === 'running') return { label: 'Online', kind: 'ok', info: 'Running. No Docker health check is configured for this container.' };
  if (c.status === 'paused') return { label: 'Paused', kind: 'paused', info: 'Container is paused and processes are suspended.' };
  if (c.status === 'restarting' || c.status === 'created') return { label: 'Starting', kind: 'pending', info: 'Container exists but is not fully online yet.' };
  if (c.status === 'exited' || c.status === 'dead') return { label: 'Offline', kind: 'offline', info: 'Container is stopped or dead.' };
  if (c.status === 'error') return { label: 'Problem', kind: 'attention', info: c.error || 'Docker returned an error while reading this container.' };
  return { label: 'Unknown', kind: 'unknown', info: `Docker state: ${c.status || 'unknown'}.` };
}

function statusBadge(c) {
  const status = monitorStatus(c);
  const raw = [c.status, c.health].filter(Boolean).join(' / ');
  return `<span class="badge ${status.kind}">${status.label}<span class="info-dot" title="${escapeHtml(`${status.info}${raw ? ` Raw Docker state: ${raw}.` : ''}`)}">i</span></span>`;
}

function portText(ports) {
  if (!ports || !ports.length) return '—';
  return ports.slice(0,3).map(p => `<span class="port">${p.host_port} → ${p.internal}</span>`).join('<br>') + (ports.length > 3 ? `<br><span class="muted">+${ports.length-3} more</span>` : '');
}

function containerIcon(c) {
  return c.icon || DEFAULT_CONTAINER_ICON;
}

function iconPath(icon) {
  return `/icons/dashboard/${icon || DEFAULT_CONTAINER_ICON}.svg`;
}

function sanitizeIcon(value) {
  return value.trim().toLowerCase().replace(/[\s_]+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

function containerSearchText(c) {
  const portParts = (c.ports || []).flatMap(p => [p.host_ip, p.host_port, p.internal, `${p.host_port}:${p.internal}`]);
  return [
    c.id,
    c.short_id,
    c.name,
    c.image,
    c.status,
    c.health,
    c.project,
    c.service,
    c.group_name,
    c.restart_policy,
    ...portParts,
  ].filter(Boolean).join(' ').toLowerCase();
}

function percent(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function metricBar(label, value, detail = '') {
  const width = Math.min(Number(value || 0), 100);
  return `<div class="server-bar">
    <div><span>${escapeHtml(label)}</span><strong>${percent(value)}</strong></div>
    <div class="meter wide"><i style="width:${width}%"></i></div>
    ${detail ? `<small>${escapeHtml(detail)}</small>` : ''}
  </div>`;
}

function renderServerMetrics(s) {
  const metrics = s.metrics || {};
  const load = metrics.load || {};
  const cpu = metrics.cpu || {};
  const memory = metrics.memory || {};
  const disk = metrics.data_mount || metrics.appdata_disk || {};
  const cores = (cpu.cores || []).slice(0, 16);
  $('serverMetrics').innerHTML = `
    <article class="server-card">
      <span class="server-card-label">Load average</span>
      <strong>${escapeHtml(String(load.one ?? '–'))}</strong>
      ${metricBar('1 min', load.one_percent, `${load.one ?? '–'} load`)}
      ${metricBar('5 min', load.five_percent, `${load.five ?? '–'} load`)}
      ${metricBar('15 min', load.fifteen_percent, `${load.fifteen ?? '–'} load`)}
    </article>
    <article class="server-card cpu-card">
      <span class="server-card-label">Processor</span>
      <strong>${percent(cpu.total_percent)}</strong>
      ${metricBar('Overall', cpu.total_percent, `${s.cpus ?? cores.length} cores`)}
      <div class="core-grid">${cores.map(core => metricBar(core.name, core.percent)).join('') || '<small class="muted">CPU sample pending</small>'}</div>
    </article>
    <article class="server-card">
      <span class="server-card-label">Memory</span>
      <strong>${percent(memory.percent)}</strong>
      ${metricBar('RAM usage', memory.percent, `${memory.used_human || '–'} / ${memory.total_human || s.memory_total_human || '–'}`)}
      <small class="metric-note">${escapeHtml(memory.available_human || '–')} available</small>
    </article>
    <article class="server-card">
      <span class="server-card-label">Data mount</span>
      <strong>${percent(disk.percent)}</strong>
      ${metricBar('Used capacity', disk.percent, `${disk.free_human || '–'} free / ${disk.total_human || '–'} total`)}
      <small class="metric-note">Shared Unraid mount capacity, not appdata folder size</small>
    </article>
  `;
}

function sectionSearchActive(section) {
  if (section === 'containers') return Boolean($('containerSearch')?.value.trim());
  if (section === 'ports') return Boolean($('portSearch')?.value.trim());
  return false;
}

function isSectionOpen(section) {
  return !collapsedSections.has(section) || sectionSearchActive(section);
}

function applySectionState() {
  for (const section of DEFAULT_SECTION_ORDER) {
    const body = $(`${section}PanelBody`);
    const button = document.querySelector(`[data-action="toggle-section"][data-section="${section}"]`);
    const icon = $(`${section}FoldIcon`);
    if (!body || !button || !icon) continue;
    const open = isSectionOpen(section);
    body.classList.toggle('hidden', !open);
    button.setAttribute('aria-expanded', String(open));
    icon.textContent = open ? '▾' : '▸';
  }
}

function toggleSection(section) {
  if (collapsedSections.has(section)) collapsedSections.delete(section);
  else collapsedSections.add(section);
  localStorage.setItem('collapsedSections', JSON.stringify([...collapsedSections]));
  applySectionState();
  refresh();
}

function applySectionOrder() {
  const parent = $('overviewSections');
  if (!parent) return;
  for (const section of sectionOrder) {
    const el = document.querySelector(`[data-section="${section}"].dashboard-section`);
    if (el) parent.appendChild(el);
  }
}

function moveSection(section, direction) {
  const index = sectionOrder.indexOf(section);
  if (!moveItem(sectionOrder, index, direction)) return;
  localStorage.setItem('overviewSectionOrder', JSON.stringify(sectionOrder));
  applySectionOrder();
}

function renderContainers() {
  if (!currentData) return;
  const q = $('containerSearch').value.trim().toLowerCase();
  const isSearching = Boolean(q);
  const terms = q.split(/\s+/).filter(Boolean);
  const containers = currentData.containers || [];
  const rows = containers.filter(c => !terms.length || terms.every(term => containerSearchText(c).includes(term)));
  $('containerRows').innerHTML = rows.length ? groupedContainers(rows).map(group => `
    <tr class="group-row ${collapsedGroups.has(group.name) && !isSearching ? 'collapsed' : ''}" data-group="${escapeHtml(group.name)}">
      <td colspan="7">
        <button class="group-toggle" type="button" data-action="toggle-group" data-group="${escapeHtml(group.name)}">
          <span class="folder-caret">${collapsedGroups.has(group.name) && !isSearching ? '▸' : '▾'}</span>
          <span class="folder-mark"></span>
          <span>${escapeHtml(group.name)}</span>
          <small>${group.containers.length}</small>
        </button>
        ${!isSearching ? `<span class="order-controls"><button class="order-btn" type="button" data-action="group-up" data-group="${escapeHtml(group.name)}" aria-label="Move group up">▵</button><button class="order-btn" type="button" data-action="group-down" data-group="${escapeHtml(group.name)}" aria-label="Move group down">▿</button></span>` : ''}
      </td>
    </tr>
    ${collapsedGroups.has(group.name) && !isSearching ? '' : group.containers.map(c => `
    <tr class="container-row" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}">
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
      <td>${!isSearching ? `<span class="order-controls"><button class="order-btn" type="button" data-action="container-up" data-name="${escapeHtml(c.name)}" aria-label="Move container up">▵</button><button class="order-btn" type="button" data-action="container-down" data-name="${escapeHtml(c.name)}" aria-label="Move container down">▿</button></span>` : ''}<button class="kebab" type="button" title="More options">•••</button></td>
    </tr>`).join('')}
  `).join('') : '<tr><td colspan="7" class="empty">No matching containers.</td></tr>';
  applySectionState();
}

function groupedContainers(containers) {
  const groups = new Map();
  for (const c of containers) {
    const group = c.group_name || 'Ungrouped';
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(c);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => sortValue(currentData?.group_order?.[a], a).localeCompare(sortValue(currentData?.group_order?.[b], b)))
    .map(([name, groupContainers]) => ({
      name,
      containers: groupContainers.sort((a, b) => sortValue(a.sort_order, a.name).localeCompare(sortValue(b.sort_order, b.name))),
    }));
}

function sortValue(order, fallback) {
  return `${String(Number.isInteger(order) && order >= 0 ? order : 999999).padStart(6, '0')}|${String(fallback).toLowerCase()}`;
}

function toggleGroup(groupName) {
  if (collapsedGroups.has(groupName)) collapsedGroups.delete(groupName);
  else collapsedGroups.add(groupName);
  localStorage.setItem('collapsedGroups', JSON.stringify([...collapsedGroups]));
  renderContainers();
}

function moveItem(items, index, direction) {
  const target = index + direction;
  if (index < 0 || target < 0 || target >= items.length) return false;
  [items[index], items[target]] = [items[target], items[index]];
  return true;
}

async function moveGroup(groupName, direction) {
  const groups = groupedContainers(currentData.containers || []);
  const names = groups.map(g => g.name);
  if (!moveItem(names, names.indexOf(groupName), direction)) return;
  currentData.group_order = currentData.group_order || {};
  names.forEach((name, index) => currentData.group_order[name] = index);
  renderContainers();
  await persistOrder();
}

async function moveContainer(containerName, direction) {
  const groups = groupedContainers(currentData.containers || []);
  const group = groups.find(g => g.containers.some(c => c.name === containerName));
  if (!group) return;
  const names = group.containers.map(c => c.name);
  if (!moveItem(names, names.indexOf(containerName), direction)) return;
  names.forEach((name, index) => {
    const container = (currentData.containers || []).find(c => c.name === name);
    if (container) container.sort_order = index;
  });
  renderContainers();
  await persistOrder();
}

async function persistOrder() {
  const groups = groupedContainers(currentData.containers || []);
  try {
    await api('/api/order', {
      method: 'PUT',
      body: JSON.stringify({
        groups: groups.map(g => g.name),
        containers: Object.fromEntries(groups.map(g => [g.name, g.containers.map(c => c.name)])),
      }),
    });
  } catch (e) { toast(e.message); }
}

function webLinks(containers) {
  const links = [];
  for (const c of containers || []) {
    for (const p of c.ports || []) {
      const [internalPort, protocol = 'tcp'] = String(p.internal || '').split('/');
      if (protocol !== 'tcp' || !p.host_port) continue;
      const port = Number(p.host_port);
      const scheme = port === 443 || port === 8443 || Number(internalPort) === 443 ? 'https' : 'http';
      links.push({ container: c, port, url: `${scheme}://${location.hostname}:${p.host_port}` });
    }
  }
  return links.sort((a, b) => a.container.name.localeCompare(b.container.name) || a.port - b.port);
}

function renderWebLinks() {
  const links = webLinks(currentData?.containers || []);
  $('webuiPanelBody').innerHTML = links.length ? links.map(link => `
    <a class="webui-pill" href="${escapeHtml(link.url)}" target="_blank" rel="noreferrer" title="${escapeHtml(link.url)}">
      <span class="container-icon mini"><img src="${iconPath(containerIcon(link.container))}" alt="" loading="lazy" onerror="this.closest('.container-icon').classList.add('missing')"></span>
      <span>${escapeHtml(link.container.name)}</span>
      <small>${escapeHtml(String(link.port))}</small>
    </a>
  `).join('') : '<div class="empty">No published TCP ports found.</div>';
}

function portProtocol(port) {
  return String(port.internal || '').split('/')[1] || 'tcp';
}

function usedPorts(containers) {
  const rows = [];
  for (const c of containers || []) {
    for (const p of c.ports || []) {
      const port = Number(p.host_port);
      if (!Number.isInteger(port) || port < 1 || port > 65535) continue;
      rows.push({ port, protocol: portProtocol(p), container: c.name, target: p.internal, host_ip: p.host_ip || '0.0.0.0' });
    }
  }
  return rows.sort((a, b) => a.protocol.localeCompare(b.protocol) || a.port - b.port || a.container.localeCompare(b.container));
}

function freeRanges(protocol, used) {
  if (protocol === 'all') return [...freeRanges('tcp', used), ...freeRanges('udp', used)];
  const taken = new Set(used.filter(row => row.protocol === protocol).map(row => row.port));
  const ranges = [];
  let start = null;
  for (let port = 1; port <= 65535; port++) {
    if (!taken.has(port) && start === null) start = port;
    if ((taken.has(port) || port === 65535) && start !== null) {
      const end = taken.has(port) ? port - 1 : port;
      if (end >= start) ranges.push({ start, end, protocol });
      start = null;
    }
  }
  return ranges;
}

function rangeLabel(range) {
  return range.start === range.end ? String(range.start) : `${range.start}-${range.end}`;
}

function renderPorts() {
  const used = usedPorts(currentData?.containers || []);
  const protocol = $('portProtocol').value;
  const mode = $('portMode').value;
  const q = $('portSearch').value.trim().toLowerCase();
  const usedFiltered = used.filter(row => {
    const protocolMatch = protocol === 'all' || row.protocol === protocol;
    const text = `${row.port} ${row.protocol} ${row.container} ${row.target} ${row.host_ip}`.toLowerCase();
    return protocolMatch && (!q || text.includes(q));
  });
  const freeFiltered = freeRanges(protocol, used).filter(range => {
    if (!q) return true;
    const text = `${rangeLabel(range)} ${range.protocol}`.toLowerCase();
    const searchedPort = Number(q);
    return text.includes(q) || (Number.isInteger(searchedPort) && searchedPort >= range.start && searchedPort <= range.end);
  }).slice(0, 120);
  const rows = [];
  if (mode !== 'free') {
    rows.push(...usedFiltered.map(row => `<tr><td><strong>${row.port}</strong></td><td>${row.protocol.toUpperCase()}</td><td><span class="port-state used">Used</span></td><td>${escapeHtml(row.container)}</td><td>${escapeHtml(row.target)}</td></tr>`));
  }
  if (mode !== 'used') {
    rows.push(...freeFiltered.map(range => `<tr><td><strong>${rangeLabel(range)}</strong></td><td>${range.protocol === 'all' ? 'TCP/UDP' : range.protocol.toUpperCase()}</td><td><span class="port-state free">Free</span></td><td class="muted">Available</td><td class="muted">Host range</td></tr>`));
  }
  $('portSummary').innerHTML = `<span>${usedFiltered.length} used</span><span>${freeFiltered.length} free ranges shown</span>`;
  $('portRows').innerHTML = rows.length ? rows.join('') : '<tr><td colspan="5" class="empty">No matching ports.</td></tr>';
  applySectionState();
}

function containerStatusSummary(containers, server) {
  if (!containers?.length) {
    return `${server.containers_running} online · ${server.containers_stopped} offline${server.containers_paused ? ` · ${server.containers_paused} paused` : ''}`;
  }
  const counts = containers.reduce((acc, c) => {
    const status = monitorStatus(c).label.toLowerCase();
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
  return [
    counts.healthy ? `${counts.healthy} healthy` : '',
    counts.online ? `${counts.online} online` : '',
    counts.attention ? `${counts.attention} attention` : '',
    counts.offline ? `${counts.offline} offline` : '',
    counts.paused ? `${counts.paused} paused` : '',
    counts.starting ? `${counts.starting} starting` : '',
  ].filter(Boolean).join(' · ') || `${server.containers_total} tracked`;
}

function overviewQuery() {
  const containerSearchActive = Boolean($('containerSearch')?.value.trim());
  const portSearchActive = Boolean($('portSearch')?.value.trim());
  const includeMetrics = isSectionOpen('server');
  const includeContainers = isSectionOpen('containers') || isSectionOpen('webui') || isSectionOpen('ports') || containerSearchActive || portSearchActive;
  const includeStats = isSectionOpen('containers') || containerSearchActive;
  return new URLSearchParams({
    include_metrics: String(includeMetrics),
    include_containers: String(includeContainers),
    include_stats: String(includeStats),
  }).toString();
}

function render(data) {
  currentData = {
    ...(currentData || {}),
    ...data,
    server: { ...((currentData || {}).server || {}), ...(data.server || {}) },
    containers: data.containers || (currentData?.containers || []),
  };
  settings = data.settings || settings;
  const s = currentData.server;
  $('metricContainers').textContent = s.containers_total;
  $('metricContainerDetail').textContent = containerStatusSummary(currentData.containers, s);
  $('metricMemory').textContent = s.metrics?.memory?.total_human || s.memory_total_human || bytes(s.memory_total);
  $('metricMemoryDetail').textContent = s.os || 'Docker host';
  $('metricCpu').textContent = s.cpus ?? '–';
  $('metricImages').textContent = s.images ?? '–';
  $('dockerVersion').textContent = `Docker ${s.docker_version || 'unknown'}`;
  $('lastUpdated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  $('dockerDetails').innerHTML = [
    ['Server', s.name], ['Operating system', s.os], ['Kernel', s.kernel], ['Docker Engine', s.docker_version], ['Docker API', s.api_version], ['CPU cores', s.cpus], ['CPU usage', percent(s.metrics?.cpu?.total_percent)], ['Load average', s.metrics?.load ? `${s.metrics.load.one} / ${s.metrics.load.five} / ${s.metrics.load.fifteen}` : '—'], ['Host memory', s.metrics?.memory?.total_human || s.memory_total_human], ['Containers', s.containers_total], ['Images', s.images]
  ].map(([k,v]) => `<div class="detail"><span>${k}</span><strong>${escapeHtml(String(v ?? '—'))}</strong></div>`).join('');
  $('settingTitle').value = settings.title;
  $('settingRefresh').value = settings.refresh_seconds;
  $('settingConfirm').checked = settings.confirm_actions;
  $('brandTitle').textContent = settings.title;
  document.title = settings.title;
  renderOptionLists();
  if (s.metrics) renderServerMetrics(s);
  renderContainers();
  renderWebLinks();
  renderPorts();
  applySectionOrder();
  applySectionState();
  scheduleRefresh();
}

async function refresh() {
  try { render(await api(`/api/overview?${overviewQuery()}`)); }
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
  const c = (currentData?.containers || []).find(x => x.id === id); if (!c) return;
  activeContainer = c;
  $('modalTitle').textContent = c.name;
  $('modalMeta').textContent = `${c.image} · ${c.status}`;
  $('modalActions').innerHTML = actionsFor(c).map(a => `<button class="btn ${a === 'stop' ? 'danger' : ''}" onclick="doAction('${a}')">${a[0].toUpperCase()+a.slice(1)}</button>`).join('');
  $('containerIconInput').value = containerIcon(c);
  setIconPreview(containerIcon(c));
  $('containerGroupInput').value = c.group_name || '';
  $('containerPrefsSaved').textContent = '';
  renderIconPicker(containerIcon(c));
  document.body.classList.add('modal-open');
  $('modal').classList.remove('hidden');
  await loadLogs({ forceBottom: true });
  scheduleLogRefresh();
}

function renderOptionLists() {
  $('dashboardIconOptions').innerHTML = dashboardIcons.map(icon => `<option value="${icon}"></option>`).join('');
  const groups = [...new Set((currentData?.containers || []).map(c => c.group_name).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  $('containerGroupOptions').innerHTML = groups.map(group => `<option value="${escapeHtml(group)}"></option>`).join('');
  renderIconPicker($('containerIconInput')?.value || '');
}

function setIconPreview(icon) {
  const slug = icon || DEFAULT_CONTAINER_ICON;
  const preview = $('containerIconPreview');
  preview.onerror = () => preview.closest('.container-icon').classList.add('missing');
  preview.src = iconPath(slug);
  preview.closest('.container-icon').classList.remove('missing');
}

async function loadIconLibrary() {
  try {
    const result = await api('/api/icons');
    dashboardIcons = result.icons || [];
    renderOptionLists();
  } catch (e) { toast(e.message); }
}

function renderIconPicker(query = '') {
  const target = $('dashboardIconGrid');
  if (!target) return;
  const selected = sanitizeIcon($('containerIconInput')?.value || '') || DEFAULT_CONTAINER_ICON;
  const q = sanitizeIcon(query);
  const icons = dashboardIcons.filter(icon => !q || icon.includes(q)).slice(0, 80);
  target.innerHTML = icons.length ? icons.map(icon => `
    <button class="icon-choice ${icon === selected ? 'selected' : ''}" type="button" data-icon="${icon}" title="${escapeHtml(icon)}">
      <img src="${iconPath(icon)}" alt="">
      <span>${escapeHtml(icon)}</span>
    </button>
  `).join('') : '<div class="icon-picker-empty">No local icon found.</div>';
}

function chooseIcon(icon) {
  $('containerIconInput').value = icon;
  setIconPreview(icon);
  renderIconPicker(icon);
}

async function downloadIcon() {
  const icon = sanitizeIcon($('containerIconInput').value);
  if (!icon) return;
  $('iconLibraryStatus').textContent = 'Checking...';
  try {
    const result = await api('/api/icons/download', { method:'POST', body: JSON.stringify({ icon }) });
    dashboardIcons = result.icons || dashboardIcons;
    chooseIcon(result.icon);
    $('iconLibraryStatus').textContent = 'Downloaded.';
    setTimeout(() => $('iconLibraryStatus').textContent = '', 1800);
  } catch (e) {
    $('iconLibraryStatus').textContent = e.message;
  }
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
    const existing = (currentData.containers || []).find(c => c.id === activeContainer.id);
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
    const updated = (currentData.containers || []).find(c => c.id === activeContainer.id); if (updated) openContainer(updated.id); else closeModal();
  } catch (e) { toast(e.message); }
}

function closeModal(){
  $('modal').classList.add('hidden');
  document.body.classList.remove('modal-open');
  activeContainer = null;
  if (logRefreshTimer) clearTimeout(logRefreshTimer);
}
$('modalClose').addEventListener('click', closeModal);
$('modal').addEventListener('click', e => { if (e.target === $('modal')) closeModal(); });
$('logRefreshBtn').addEventListener('click', () => loadLogs({ forceBottom: true }));
$('containerPrefsForm').addEventListener('submit', saveContainerPrefs);
$('containerIconInput').addEventListener('input', () => {
  const icon = sanitizeIcon($('containerIconInput').value) || DEFAULT_CONTAINER_ICON;
  setIconPreview(icon);
  renderIconPicker(icon);
});
$('dashboardIconGrid').addEventListener('click', event => {
  const button = event.target.closest('.icon-choice');
  if (button) chooseIcon(button.dataset.icon);
});
$('iconDownloadBtn').addEventListener('click', downloadIcon);
$('refreshBtn').addEventListener('click', refresh);
$('overviewSections').addEventListener('click', event => {
  const sectionButton = event.target.closest('[data-action^="section-"], [data-action="toggle-section"]');
  if (!sectionButton) return;
  event.stopPropagation();
  const section = sectionButton.dataset.section;
  if (sectionButton.dataset.action === 'toggle-section') toggleSection(section);
  if (sectionButton.dataset.action === 'section-up') moveSection(section, -1);
  if (sectionButton.dataset.action === 'section-down') moveSection(section, 1);
});
$('containerSearch').addEventListener('input', () => { renderContainers(); refresh(); });
$('portSearch').addEventListener('input', () => { renderPorts(); refresh(); });
$('portProtocol').addEventListener('change', renderPorts);
$('portMode').addEventListener('change', renderPorts);
$('containerRows').addEventListener('click', event => {
  const orderButton = event.target.closest('.order-btn');
  if (orderButton) {
    event.stopPropagation();
    const action = orderButton.dataset.action;
    if (action === 'group-up') moveGroup(orderButton.dataset.group, -1);
    if (action === 'group-down') moveGroup(orderButton.dataset.group, 1);
    if (action === 'container-up') moveContainer(orderButton.dataset.name, -1);
    if (action === 'container-down') moveContainer(orderButton.dataset.name, 1);
    return;
  }
  const groupToggle = event.target.closest('[data-action="toggle-group"]');
  if (groupToggle) {
    toggleGroup(groupToggle.dataset.group);
    return;
  }
  const row = event.target.closest('.container-row');
  if (row) openContainer(row.dataset.id);
});

for (const btn of document.querySelectorAll('.nav-item[data-view]')) {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item[data-view]').forEach(x => x.classList.remove('active')); btn.classList.add('active');
    document.querySelectorAll('.view').forEach(x => x.classList.remove('active')); $(`${btn.dataset.view}View`).classList.add('active');
    const names = {dashboard:['Overview','Homelab data, shortcuts, ports, and monitoring'],docker:['Docker','Docker Engine information'],settings:['Settings','Configure this hub']};
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

loadIconLibrary().finally(refresh);
