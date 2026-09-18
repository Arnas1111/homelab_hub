/* The workspace overview is a service directory, not a second administration table. */
let boardSaving = false;
let unraidLoading = false;

function boardLink(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
  catch (_) { return ''; }
}

function boardServices() {
  const links = mergedWebLinks();
  const containers = currentData?.containers || [];
  const result = containers.map(c => {
    const link = links.find(l => l.container_name === c.name || l.label === c.name);
    return { key: `container:${c.name}`, id: c.id, name: c.display_name || c.name, rawName: c.name,
      group: c.group_name || 'Other services', icon: containerIcon(c), url: boardLink(link?.url || ''),
      description: c.description || c.project || c.image, status: c.status, health: c.health, integration: c.integration };
  });
  for (const link of links.filter(l => l.source === 'manual' && !containers.some(c => c.name === l.container_name || c.name === l.label))) {
    result.push({ key: `link:${link.link_key}`, name: link.label, group: 'External services', icon: link.icon || 'docker',
      url: boardLink(link.url), status: 'external', description: 'Saved link · availability not monitored' });
  }
  return result;
}

function needsAttention(service) {
  return service.health === 'unhealthy' || ['restarting','dead','error'].includes(service.status);
}

function serviceCard(service) {
  const favorite = (currentData?.board?.favorites || []).includes(service.key);
  const state = needsAttention(service) ? 'attention' : service.status === 'running' ? 'running' : 'idle';
  const label = needsAttention(service) ? (service.health === 'unhealthy' ? 'Unhealthy' : service.status) : service.status === 'external' ? 'External link' : service.status || 'Unknown';
  const icon = `<span class="service-icon"><img src="${iconPath(service.icon)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"></span>`;
  const title = `${icon}<span class="service-name"><strong>${escapeHtml(service.name)}</strong><small>${escapeHtml(service.description || service.group)}</small></span>`;
  return `<article class="service-card" data-service-key="${escapeHtml(service.key)}"><div class="service-main">${service.url ? `<a href="${escapeHtml(service.url)}" target="_blank" rel="noreferrer" title="Open ${escapeHtml(service.name)}">${title}</a>` : `<div class="service-title">${title}</div>`}<button class="pin-service ${favorite ? 'pinned' : ''}" data-pin="${escapeHtml(service.key)}" aria-label="${favorite ? 'Unpin' : 'Pin'} ${escapeHtml(service.name)}" aria-pressed="${favorite}">${favorite ? '★' : '☆'}</button></div><div class="service-footer"><span class="service-state ${state}"><i></i>${escapeHtml(label)}</span>${service.id ? `<button class="text-btn" data-service-details="${escapeHtml(service.id)}">Details ↗</button>` : '<span class="muted tiny">Link</span>'}</div></article>`;
}

function boardGroups(services) {
  if (!services.length) return '<div class="board-empty">No matching services. Try another search or add a link below.</div>';
  const groups = new Map();
  for (const service of services) {
    if (!groups.has(service.group)) groups.set(service.group, []);
    groups.get(service.group).push(service);
  }
  return [...groups].sort(([a], [b]) => a.localeCompare(b)).map(([name, items]) => `<section class="service-group"><div class="group-heading"><h3>${escapeHtml(name)}</h3><span>${items.length}</span></div><div class="service-grid">${items.map(serviceCard).join('')}</div></section>`).join('');
}

function renderBoard() {
  if (!currentData) return;
  const services = boardServices();
  const s = currentData.server || {};
  const metrics = s.metrics || {};
  const discovery = currentData.discovery || {};
  const host = currentData.host_collection || {};
  const resource = currentData.resource_collection || {};
  $('metricsCollectionStatus').textContent = host.error || (host.updated_at ? `Host sampled ${new Date(host.updated_at).toLocaleTimeString()}` : 'Waiting for host readings.');
  $('resourceCollectionStatus').textContent = resource.error || (resource.updated_at ? `Resources sampled ${new Date(resource.updated_at).toLocaleTimeString()}${resource.loading ? ' · updating' : ''}` : 'Resource samples load independently. Missing readings are shown as —.');
  const dot = document.querySelector('.server-pill .dot');
  if (dot) dot.dataset.state = discovery.error ? 'error' : discovery.updated_at ? 'ready' : 'unknown';
  const favorites = currentData.board?.favorites || [];
  const attention = services.filter(needsAttention);
  const homeQuery = $('homeSearch').value.trim().toLowerCase();
  const match = (service, query) => `${service.name} ${service.rawName || ''} ${service.group} ${service.description}`.toLowerCase().includes(query);
  const pinned = services.filter(service => favorites.includes(service.key));
  const visibleHome = (homeQuery ? services.filter(service => match(service, homeQuery)) : pinned.length ? pinned : services).slice(0, 8);
  $('homeServerTitle').textContent = s.name || 'Your homelab';
  $('favoriteTitle').textContent = homeQuery ? 'Search results' : pinned.length ? 'Favorites' : 'Your services';
  $('boardStatus').textContent = discovery.error || (!discovery.updated_at && discovery.loading ? 'Discovering Docker services… Host readings load independently.' : `${services.length} services · ${s.cpus || metrics.cpu?.cores?.length || '—'} logical cores · ${bytes(s.memory_total || metrics.memory?.total)} memory${discovery.updated_at ? ` · discovered ${new Date(discovery.updated_at).toLocaleTimeString()}` : ''}`);
  $('boardStatus').classList.toggle('attention', Boolean(discovery.error));
  if (host.error) $('boardStatus').textContent += ` · ${host.error}; host readings may be stale`;
  const pulse = (title, value, note, action, level = 'normal') => `<button class="pulse-card ${level}" ${action}><span>${title}<b>↗</b></span><strong>${value}</strong><small>${escapeHtml(note)}</small></button>`;
  patchContent($('homePulse'),
    pulse('Running containers', discovery.updated_at || services.length ? `${s.containers_running ?? services.filter(c => c.status === 'running').length}<em> / ${s.containers_total ?? services.length}</em>` : '—', 'Docker state, not service availability', 'data-open-view="containers"') +
    pulse('CPU utilization', metrics.cpu?.cores?.length ? percent(metrics.cpu.total_percent) : '—', 'Host capacity', 'data-metric-page="cpu"', metricLevel(metrics.cpu?.total_percent).kind) +
    pulse('Memory utilization', metrics.memory?.total ? percent(metrics.memory.percent) : '—', `${metrics.memory?.available_human || '—'} available`, 'data-metric-page="memory"', metricLevel(metrics.memory?.percent).kind) +
    pulse('Storage capacity', metrics.data_mount?.total ? percent(metrics.data_mount.percent) : '—', `${metrics.data_mount?.free_human || '—'} free on /data mount`, 'data-metric-page="storage"', metricLevel(metrics.data_mount?.percent).kind));
  patchContent($('homeServices'), visibleHome.length ? `<div class="service-grid home-service-grid">${visibleHome.map(serviceCard).join('')}</div><p class="board-help">${homeQuery ? 'Open Services to see all search results.' : pinned.length ? 'Your favorites are saved in the Hub.' : 'Pin a service with ☆ to make this space your own.'}</p>` : `<div class="board-empty">${discovery.loading ? 'Discovering services…' : 'No services yet. Connect the Docker socket or add an external link in Services.'}<button class="btn" data-open-view="services">Open services</button></div>`);
  $('attentionCount').textContent = attention.length;
  patchContent($('homeAttention'), discovery.error ? `<p class="attention">Docker discovery is unavailable. These readings may be stale.</p>` : !discovery.updated_at && !services.length ? '<p class="muted tiny">Waiting for Docker discovery.</p>' : attention.length ? attention.slice(0, 5).map(c => `<button class="attention-row" data-service-details="${escapeHtml(c.id)}"><span>${escapeHtml(c.name)}</span><small>${escapeHtml(c.health === 'unhealthy' ? 'Unhealthy' : c.status)}</small></button>`).join('') : '<div class="quiet-state"><span>✓</span><strong>No container alerts</strong><p>No unhealthy or restarting containers were reported. Stopped containers are not treated as incidents.</p></div>');
  const configured = currentData.connections || {};
  patchContent($('homeConnections'), [['unraid','Unraid','Array & disks'],['jellyfin','Jellyfin','Media activity'],['home_assistant','Home Assistant','Home controls']].map(([key,label,description]) => `<button class="connection-row" data-open-view="${configured[key] ? 'integrations' : 'connectors'}"><span><strong>${label}</strong><small>${description}</small></span><span class="connection-state">${configured[key] ? 'Configured' : services.some(c => c.integration === key) ? 'Detected · set up' : 'Connect'} ↗</span></button>`).join(''));
  const query = $('serviceSearch').value.trim().toLowerCase();
  const filter = $('serviceFilter').value;
  const filtered = services.filter(c => match(c, query) && (filter === 'all' || filter === 'favorites' && favorites.includes(c.key) || filter === 'attention' && needsAttention(c) || filter === 'running' && c.status === 'running'));
  $('serviceCount').textContent = `${filtered.length} of ${services.length} services`;
  if ($('servicesView').classList.contains('active')) patchContent($('allServices'), boardGroups(filtered));
}

async function loadUnraid() {
  if (unraidLoading) return;
  unraidLoading = true;
  try {
    const snapshot = await api('/api/unraid');
    const data = snapshot.data || {};
    const array = data.array || {};
    const info = data.info || {};
    patchContent($('unraidPanel'), `<article class="unraid-summary"><div class="board-section-heading"><div><span class="eyebrow">HOST CONNECTION</span><h2>Unraid</h2></div><span class="connection-state">${data.array ? escapeHtml(array.state || 'Connected') : data.configured ? 'Check connection' : 'Not connected'}</span></div>${snapshot.error || data.error ? `<p class="attention">${escapeHtml(snapshot.error || data.error)}</p>` : !snapshot.data ? '<p class="muted">Connecting to Unraid…</p>' : !data.configured ? `<p class="muted">${escapeHtml(data.message || 'Configure Unraid to see array and disk readings.')}</p><button class="btn" data-open-view="connectors">Connect Unraid</button>` : `<div class="unraid-facts"><span>Processor<strong>${escapeHtml(info.cpu?.brand || '—')}</strong></span><span>System<strong>${escapeHtml([info.os?.distro, info.os?.release].filter(Boolean).join(' ') || '—')}</strong></span><span>Array free<strong>${array.capacity_bytes?.free == null ? '&mdash;' : bytes(array.capacity_bytes.free)}</strong></span></div><div class="table-wrap"><table><thead><tr><th>Disk</th><th>State</th><th>Temperature</th></tr></thead><tbody>${(array.disks || []).map(disk => `<tr><td>${escapeHtml(disk.name)}</td><td>${escapeHtml(disk.status || '—')}</td><td>${disk.temp === null || disk.temp === undefined ? '—' : `${escapeHtml(disk.temp)} °C`}</td></tr>`).join('')}</tbody></table></div>`}</article>`);
  } catch (error) { $('unraidPanel').textContent = error.message; }
  finally { unraidLoading = false; }
}

document.addEventListener('click', async event => {
  const navigation = event.target.closest('[data-open-view]');
  if (navigation) document.querySelector(`.nav-item[data-view="${navigation.dataset.openView}"]`)?.click();
  const details = event.target.closest('[data-service-details]');
  if (details) openContainer(details.dataset.serviceDetails);
  const pin = event.target.closest('[data-pin]');
  if (pin && !boardSaving) {
    boardSaving = true;
    const favorites = new Set(currentData?.board?.favorites || []);
    if (favorites.has(pin.dataset.pin)) favorites.delete(pin.dataset.pin); else favorites.add(pin.dataset.pin);
    try { currentData.board = await api('/api/board', { method:'PUT', body:JSON.stringify({favorites:[...favorites]}) }); renderBoard(); }
    catch (error) { toast(error.message); }
    finally { boardSaving = false; }
  }
});
$('homeSearch').addEventListener('input', renderBoard);
$('serviceSearch').addEventListener('input', renderBoard);
$('serviceFilter').addEventListener('change', renderBoard);
$('manageServices').addEventListener('click', () => { const editor = document.querySelector('.webui-editor'); if (editor) { editor.open = true; editor.scrollIntoView({behavior:'smooth',block:'start'}); } });
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    document.querySelector('[data-view="services"]').click();
    $('serviceSearch').focus();
  }
});
if (currentData) renderBoard();
