let currentData = null;
let settings = { title: 'Homelab Hub', refresh_seconds: 5, confirm_actions: true };
let refreshTimer = null;
let activeContainer = null;

const $ = (id) => document.getElementById(id);

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

function renderContainers() {
  if (!currentData) return;
  const q = $('containerSearch').value.trim().toLowerCase();
  const rows = currentData.containers.filter(c => !q || `${c.name} ${c.image} ${c.project || ''}`.toLowerCase().includes(q));
  $('containerRows').innerHTML = rows.length ? rows.map(c => `
    <tr>
      <td class="name-cell"><strong>${escapeHtml(c.name)}</strong><small>${c.project ? escapeHtml(c.project) : c.short_id}</small></td>
      <td>${statusBadge(c)}</td>
      <td>${Number(c.cpu_percent || 0).toFixed(1)}%<div class="meter"><i style="width:${Math.min(c.cpu_percent || 0,100)}%"></i></div></td>
      <td>${bytes(c.memory_used)} <span class="muted">/ ${bytes(c.memory_limit)}</span><div class="meter"><i style="width:${Math.min(c.memory_percent || 0,100)}%"></i></div></td>
      <td>${portText(c.ports)}</td>
      <td><div class="image-text" title="${escapeHtml(c.image)}">${escapeHtml(c.image)}</div></td>
      <td><button class="kebab" onclick="openContainer('${c.id}')">•••</button></td>
    </tr>`).join('') : '<tr><td colspan="7" class="empty">No matching containers.</td></tr>';
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
  $('modal').classList.remove('hidden'); $('modalLogs').textContent = 'Loading logs…';
  try { const result = await api(`/api/containers/${id}/logs?tail=300`); $('modalLogs').textContent = result.logs || '(No logs)'; }
  catch (e) { $('modalLogs').textContent = e.message; }
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

function closeModal(){ $('modal').classList.add('hidden'); activeContainer = null; }
$('modalClose').addEventListener('click', closeModal);
$('modal').addEventListener('click', e => { if (e.target === $('modal')) closeModal(); });
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
