/* The workspace overview is a service directory, not a second administration table. */
let boardSaving = false;
let unraidLoading = false;
let favoriteDragKey = null;
let favoritePointer = null;

function boardLink(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
  catch (_) { return ''; }
}

function boardServices() {
  const links = mergedWebLinks();
  const containers = currentData?.containers || [];
  const result = containers.map(c => {
    const link = webuiLinkForContainer(c);
    return { key: `container:${c.name}`, id: c.id, name: c.display_name || c.name, rawName: c.name,
      group: c.group_name || 'Other services', icon: link?.icon || containerIcon(c), url: boardLink(link?.url || ''),
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

function serviceCard(service, onHome = false) {
  const favorite = (currentData?.board?.favorites || []).includes(service.key);
  const state = needsAttention(service) ? 'attention' : service.status === 'running' ? 'running' : 'idle';
  const label = needsAttention(service) ? (service.health === 'unhealthy' ? 'Unhealthy' : service.status) : service.status === 'external' ? 'External link' : service.status || 'Unknown';
  const icon = `<span class="service-icon"><img src="${iconPath(service.icon)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'"></span>`;
  const title = `${icon}<span class="service-name"><strong>${escapeHtml(service.name)}</strong><small>${escapeHtml(service.description || service.group)}</small></span>`;
  return `<article class="service-card" data-service-key="${escapeHtml(service.key)}" ${onHome && favorite ? `data-favorite-key="${escapeHtml(service.key)}"` : ''}>${onHome && favorite ? `<button class="favorite-drag-handle" draggable="true" data-favorite-drag="${escapeHtml(service.key)}" aria-label="Move ${escapeHtml(service.name)} favorite" title="Drag to reorder favorites">⠿</button>` : ''}<div class="service-main">${service.url ? `<a href="${escapeHtml(service.url)}" target="_blank" rel="noreferrer" title="Open ${escapeHtml(service.name)}">${title}</a>` : `<div class="service-title">${title}</div>`}<button class="pin-service ${favorite ? 'pinned' : ''}" data-pin="${escapeHtml(service.key)}" aria-label="${favorite ? 'Unpin' : 'Pin'} ${escapeHtml(service.name)}" aria-pressed="${favorite}">${favorite ? '★' : '☆'}</button></div><div class="service-footer"><span class="service-state ${state}"><i></i>${escapeHtml(label)}</span><button class="text-btn" data-service-edit="${escapeHtml(service.key)}">${service.id ? service.url ? 'Edit Web UI' : 'Add Web UI' : 'Edit tile'}</button>${service.id ? `<button class="text-btn" data-service-details="${escapeHtml(service.id)}">Details ↗</button>` : '<span class="muted tiny">Link</span>'}</div></article>`;
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
  const homeQuery = $('homeSearch').value.trim().toLowerCase();
  const match = (service, query) => `${service.name} ${service.rawName || ''} ${service.group} ${service.description}`.toLowerCase().includes(query);
  const pinned = favorites.map(key => services.find(service => service.key === key)).filter(Boolean);
  $('allContainerCount').textContent = services.filter(service => service.id).length;
  const selectedContainers = pinned.filter(service => service.id);
  if (!favoriteDragKey && !favoritePointer) patchContent($('featuredContainers'), selectedContainers.length ? selectedContainers.map(service => serviceCard(service, true)).join('') : '<div class="board-empty">Pin containers in the list below to show them here.</div>');
  const visibleHome = (homeQuery ? services.filter(service => match(service, homeQuery)) : pinned).slice(0, 8);
  $('homeServerTitle').textContent = s.name || 'Your homelab';
  const serverUrl = boardLink(s.webui_url || '');
  const serverLink = $('homeServerLink');
  if (serverUrl) { serverLink.href = serverUrl; serverLink.title = 'Open Unraid WebUI'; }
  else { serverLink.removeAttribute('href'); serverLink.removeAttribute('title'); }
  $('favoriteTitle').textContent = homeQuery ? 'Search results' : 'Favorites';
  const pulse = (title, value, note, action, level = 'normal') => `<button class="pulse-card ${level}" ${action}><span>${title}<b>↗</b></span><strong>${value}</strong><small>${escapeHtml(note)}</small></button>`;
  patchContent($('homePulse'),
    pulse('Running containers', discovery.updated_at || services.length ? `${s.containers_running ?? services.filter(c => c.status === 'running').length}<em> / ${s.containers_total ?? services.length}</em>` : '—', 'Docker state, not service availability', 'data-open-view="services"') +
    pulse('CPU utilization', metrics.cpu?.cores?.length ? percent(metrics.cpu.total_percent) : '—', 'Host capacity', 'data-metric-page="cpu"', metricLevel(metrics.cpu?.total_percent).kind) +
    pulse('Memory utilization', metrics.memory?.total ? percent(metrics.memory.percent) : '—', `${metrics.memory?.available_human || '—'} available`, 'data-metric-page="memory"', metricLevel(metrics.memory?.percent).kind) +
    pulse('Storage capacity', metrics.data_mount?.total ? percent(metrics.data_mount.percent) : '—', `${metrics.data_mount?.free_human || '—'} free on /data mount`, 'data-metric-page="storage"', metricLevel(metrics.data_mount?.percent).kind));
  if (!favoriteDragKey && !favoritePointer) {
    patchContent($('homeServices'), visibleHome.length ? `<div class="service-grid home-service-grid">${visibleHome.map(service => serviceCard(service, true)).join('')}</div>` : `<div class="board-empty">${homeQuery ? 'No matching services.' : 'Pin containers to add them here.'}<button class="btn" data-open-view="services">Open containers</button></div>`);
    if ($('homeFavoritePreview')) patchContent($('homeFavoritePreview'), pinned.length ? pinned.map(service => `<button type="button" class="home-favorite-chip" draggable="true" data-favorite-drag="${escapeHtml(service.key)}" data-favorite-key="${escapeHtml(service.key)}" aria-label="Move ${escapeHtml(service.name)} favorite">${escapeHtml(service.name)}</button>`).join('') : '<span class="muted tiny">No pinned services</span>');
  }
  const query = $('serviceSearch').value.trim().toLowerCase();
  const filter = $('serviceFilter').value;
  const filtered = services.filter(c => match(c, query) && (filter === 'all' || filter === 'favorites' && favorites.includes(c.key) || filter === 'attention' && needsAttention(c) || filter === 'running' && c.status === 'running'));
  $('serviceCount').textContent = `${filtered.length} of ${services.length} services`;
  if ($('servicesView').classList.contains('active')) patchContent($('allServices'), boardGroups(filtered));
}

async function loadUnraid() {
  if (!(integrationSettings?.connectors || []).includes('unraid') || integrationSettings.unraid_enabled === false) return;
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
  if (navigation) document.querySelector(`.nav-item[data-view="${navigation.dataset.openView === 'connectors' ? 'integrations' : navigation.dataset.openView}"]`)?.click();
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
async function reorderFavorite(source, destination) {
  if (source === destination || boardSaving) return;
  const current = currentData?.board?.favorites || [];
  const sourceIndex = current.indexOf(source), destinationIndex = current.indexOf(destination);
  if (sourceIndex < 0 || destinationIndex < 0) return;
  const favorites = current.filter(key => key !== source);
  const index = favorites.indexOf(destination);
  favorites.splice(index + (sourceIndex < destinationIndex ? 1 : 0), 0, source);
  boardSaving = true;
  try { currentData.board = await api('/api/board', {method:'PUT', body:JSON.stringify({favorites})}); renderBoard(); }
  catch (error) { toast(error.message); }
  finally { boardSaving = false; }
}
document.addEventListener('dragstart', event => {
  const handle = event.target.closest('[data-favorite-drag]');
  if (!handle || boardSaving) return;
  favoriteDragKey = handle.dataset.favoriteDrag;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', favoriteDragKey);
});
document.addEventListener('dragover', event => {
  const target = event.target.closest('[data-favorite-key]');
  if (!favoriteDragKey || !target || target.dataset.favoriteKey === favoriteDragKey) return;
  event.preventDefault(); target.classList.add('home-drop-target');
});
document.addEventListener('dragleave', event => {
  event.target.closest('[data-favorite-key]')?.classList.remove('home-drop-target');
});
document.addEventListener('drop', async event => {
  const target = event.target.closest('[data-favorite-key]');
  if (!favoriteDragKey || !target) return;
  event.preventDefault(); event.stopPropagation();
  const source = favoriteDragKey, destination = target.dataset.favoriteKey;
  favoriteDragKey = null; target.classList.remove('home-drop-target');
  await reorderFavorite(source, destination);
});
document.addEventListener('dragend', () => {
  favoriteDragKey = null;
  for (const card of document.querySelectorAll('[data-favorite-key].home-drop-target')) card.classList.remove('home-drop-target');
});
document.addEventListener('pointerdown', event => {
  const handle = event.target.closest('[data-favorite-drag]');
  if (!handle || event.pointerType === 'mouse') return;
  favoritePointer = {id:event.pointerId, key:handle.dataset.favoriteDrag};
  handle.setPointerCapture(event.pointerId);
  event.preventDefault();
});
document.addEventListener('pointermove', event => {
  if (!favoritePointer || event.pointerId !== favoritePointer.id) return;
  for (const card of document.querySelectorAll('[data-favorite-key].home-drop-target')) card.classList.remove('home-drop-target');
  document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-favorite-key]')?.classList.add('home-drop-target');
});
document.addEventListener('pointerup', event => {
  if (!favoritePointer || event.pointerId !== favoritePointer.id) return;
  const source = favoritePointer.key;
  const destination = document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-favorite-key]')?.dataset.favoriteKey;
  favoritePointer = null;
  for (const card of document.querySelectorAll('[data-favorite-key].home-drop-target')) card.classList.remove('home-drop-target');
  if (destination) reorderFavorite(source,destination);
});
document.addEventListener('pointercancel', () => { favoritePointer = null; });
document.addEventListener('keydown', event => {
  const handle = event.target.closest('[data-favorite-drag]');
  if (!handle || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
  const favorites = currentData?.board?.favorites || [];
  const index = favorites.indexOf(handle.dataset.favoriteDrag);
  const destination = favorites[index + (event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1)];
  if (index < 0 || !destination) return;
  event.preventDefault(); reorderFavorite(handle.dataset.favoriteDrag,destination);
});
$('serviceSearch').addEventListener('input', renderBoard);
$('serviceFilter').addEventListener('change', renderBoard);
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    document.querySelector('[data-view="services"]').click();
    $('allContainersDisclosure').open = true;
    $('serviceSearch').focus();
  }
});
if (currentData) renderBoard();
