/* Dedicated history pages; the live overview remains independent of PostgreSQL. */
const METRIC_PAGES = {
  cpu: ['CPU history', 'Total host utilization · 100% means all logical cores'],
  memory: ['Memory history', 'Host RAM usage and available memory'],
  storage: ['Storage history', 'Capacity of the filesystem backing /data · not array health'],
  network: ['Network history', 'Hub network namespace · bridge mode excludes other host traffic'],
  containers: ['Container history', 'Docker CPU uses 100% per core · memory is measured in bytes'],
};
let historyMetric = 'cpu';
let historyRequest = 0;
let historySettingsLoaded = false;
let lastHistoryData = null;

function historyFormat(value, unit) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  if (unit === 'B' || unit === 'B/s') return `${bytes(Number(value))}${unit === 'B/s' ? '/s' : ''}`;
  return `${Number(value).toFixed(1)}%`;
}

function historyChart(points, series, start, end, bucketSeconds) {
  const valid = points.filter(p => p[series.key] !== null && Number.isFinite(Number(p[series.key])));
  if (!valid.length) return '<div class="history-empty">No samples for this statistic in the selected range.</div>';
  const max = series.unit === '%' ? 100 : Math.max(1, ...valid.map(p => Number(p[series.key + '_max'] ?? p[series.key]))) * 1.1;
  const first = new Date(start).getTime();
  const span = Math.max(1, new Date(end).getTime() - first);
  const chartWidth = typeof window !== 'undefined' && window.matchMedia('(max-width:720px)').matches ? 360 : 900;
  const plotEnd = chartWidth - 30;
  const x = p => 70 + Math.max(0, Math.min(1, (new Date(p.time).getTime() - first) / span)) * (plotEnd - 70);
  const y = v => 190 - Math.max(0, Math.min(1, Number(v) / max)) * 160;
  function path(key) {
    let previous = null;
    return points.map(p => {
      if (p[key] === null || !Number.isFinite(Number(p[key]))) { previous = null; return ''; }
      const disconnected = !previous || new Date(p.time) - new Date(previous.time) > bucketSeconds * 1500;
      previous = p;
      return `${disconnected ? 'M' : 'L'}${x(p).toFixed(1)} ${y(p[key]).toFixed(1)}`;
    }).join(' ');
  }
  const grid = [0, .5, 1].map(f => `<path d="M70 ${y(f * max)}H${plotEnd}"/><text x="62" y="${y(f * max) + 4}" text-anchor="end">${escapeHtml(historyFormat(f * max, series.unit))}</text>`).join('');
  return `<svg class="history-chart" viewBox="0 0 ${chartWidth} 220" role="img" aria-label="${escapeHtml(series.label)}: average and peak per ${bucketSeconds}-second interval"><g class="history-grid">${grid}</g><path class="history-peak" d="${path(series.key + '_max')}"/><path class="history-average" d="${path(series.key)}"/>${valid.map(p => `<circle class="history-point" cx="${x(p)}" cy="${y(p[series.key])}" r="2.5"><title>${escapeHtml(new Date(p.time).toLocaleString())}: average ${escapeHtml(historyFormat(p[series.key], series.unit))}, peak ${escapeHtml(historyFormat(p[series.key + '_max'], series.unit))}</title></circle>`).join('')}</svg><div class="history-axis"><span>${escapeHtml(new Date(start).toLocaleString())}</span><span>${escapeHtml(new Date(end).toLocaleString())}</span></div>`;
}

function renderHistory(data) {
  lastHistoryData = data;
  const latest = data.latest?.payload || {};
  const chosen = $('historyContainer').value;
  const selected = chosen ? (latest.containers || []).find(c => c.id === chosen) : null;
  const series = data.series.map(s => {
    const values = data.points.filter(p => p[s.key] !== null && Number.isFinite(Number(p[s.key])));
    const count = values.reduce((n, p) => n + Number(p[s.key + '_count'] || 0), 0);
    const average = count ? values.reduce((n, p) => n + Number(p[s.key]) * Number(p[s.key + '_count'] || 0), 0) / count : null;
    const peak = values.length ? Math.max(...values.map(p => Number(p[s.key + '_max']))) : null;
    let lastValue = latest[s.key];
    if (data.metric === 'containers' && chosen) lastValue = selected?.[s.key === 'container_cpu' ? 'cpu_percent' : 'memory_used'];
    return `<article class="history-series"><h2>${escapeHtml(s.label)}</h2><div class="history-summary"><div><span>Latest stored</span><strong>${escapeHtml(historyFormat(lastValue, s.unit))}</strong></div><div><span>Range average</span><strong>${escapeHtml(historyFormat(average, s.unit))}</strong></div><div><span>Range peak</span><strong>${escapeHtml(historyFormat(peak, s.unit))}</strong></div></div><div class="history-chart-key"><span>━ Average</span><span>┄ Peak</span><small>${data.bucket_seconds}s buckets · hover points for values</small></div>${historyChart(data.points, s, data.start, data.end, data.bucket_seconds)}<details class="history-table"><summary>View sampled values</summary><div class="table-wrap"><table><thead><tr><th>Time</th><th>Average</th><th>Peak</th><th>Samples</th></tr></thead><tbody>${values.map(p => `<tr><td>${escapeHtml(new Date(p.time).toLocaleString())}</td><td>${escapeHtml(historyFormat(p[s.key], s.unit))}</td><td>${escapeHtml(historyFormat(p[s.key + '_max'], s.unit))}</td><td>${p[s.key + '_count']}</td></tr>`).join('')}</tbody></table></div></details></article>`;
  }).join('');
  let details = '';
  if (data.metric === 'cpu') details = `<h3>Latest per-core sample</h3><div class="history-core-list">${Object.entries(latest.cores || {}).map(([name, value]) => `<span>${escapeHtml(name)} <strong>${historyFormat(value, '%')}</strong></span>`).join('') || 'No per-core sample yet.'}</div>`;
  if (data.metric === 'storage') details = `<p class="muted">Latest total capacity: ${historyFormat(latest.storage_total, 'B')}. Changes can reflect mount capacity changes as well as file growth.</p>`;
  if (data.metric === 'containers') details = `<h3>Containers in latest stored snapshot</h3><div class="table-wrap"><table><thead><tr><th>Name</th><th>State</th><th>CPU</th><th>Memory</th></tr></thead><tbody>${(latest.containers || []).filter(c => !chosen || c.id === chosen).map(c => `<tr><td>${escapeHtml(c.name || c.id)}</td><td>${escapeHtml(c.status || 'unknown')}</td><td>${historyFormat(c.cpu_percent, '%')}</td><td>${historyFormat(c.memory_used, 'B')}</td></tr>`).join('')}</tbody></table></div>`;
  patchContent($('historyContent'), series + `<div class="history-extra">${details}</div>`);
  const saved = data.latest ? new Date(data.latest.sampled_at) : null;
  const stale = saved && Date.now() - saved.getTime() > Math.max(120, data.sample_seconds * 3) * 1000;
  $('historyNotice').textContent = `${data.enabled ? 'Collection enabled.' : 'Collection disabled; stored history remains available.'} ${saved ? `Last stored sample: ${saved.toLocaleString()}.${stale ? ' Samples are stale; check History storage for errors.' : ''}` : 'No stored samples yet. Enable collection in History storage.'} Retention: ${data.retention_days} days. Empty intervals are gaps, not zero usage.`;
}

async function loadHistory(clear = false) {
  if (!$('metricDetailView').classList.contains('active')) return;
  const request = ++historyRequest;
  if (clear) $('historyContent').innerHTML = '<div class="empty">Loading history…</div>';
  if (clear) lastHistoryData = null;
  const range = $('historyRange').value;
  const container = historyMetric === 'containers' ? $('historyContainer').value : '';
  const query = new URLSearchParams({ metric: historyMetric, range });
  if (container) query.set('container_id', container);
  try {
    const data = await api(`/api/metrics/history?${query}`);
    if (request !== historyRequest || !$('metricDetailView').classList.contains('active')) return;
    if (historyMetric === 'containers') {
      const choices = new Map(data.containers.map(c => [c.id, c.name || c.id]));
      if (container && !choices.has(container)) choices.set(container, 'Selected container (no samples in range)');
      $('historyContainer').innerHTML = '<option value="">All containers</option>' + [...choices].map(([id, name]) => `<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`).join('');
      $('historyContainer').value = container;
    }
    renderHistory(data);
  } catch (error) {
    if (request !== historyRequest) return;
    $('historyNotice').textContent = error.message;
    if (clear) $('historyContent').innerHTML = '<div class="history-empty">History is unavailable. Open <button class="btn" data-history-settings>History storage</button> to configure or test PostgreSQL. Live metrics remain available in Overview.</div>';
  }
}

function openMetricPage(metric) {
  if (!METRIC_PAGES[metric]) return;
  if (location.hash !== `#metrics/${metric}`) { location.hash = `metrics/${metric}`; return; }
  historyMetric = metric;
  document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
  $('metricDetailView').classList.add('active');
  document.querySelectorAll('.nav-item').forEach(btn => btn.classList.toggle('active', btn.classList.contains('history-nav')));
  document.querySelectorAll('.metric-tabs button').forEach(btn => {
    btn.classList.toggle('primary', btn.dataset.metricPage === metric);
    btn.setAttribute('aria-pressed', String(btn.dataset.metricPage === metric));
  });
  $('pageTitle').textContent = METRIC_PAGES[metric][0];
  $('pageSubtitle').textContent = METRIC_PAGES[metric][1];
  $('historyContainerLabel').hidden = metric !== 'containers';
  loadHistory(true);
}

function pgPayload() {
  return { enabled: $('pgEnabled').checked, host: $('pgHost').value.trim(), port: Number($('pgPort').value),
    database: $('pgDatabase').value.trim(), username: $('pgUsername').value.trim(), password: $('pgPassword').value,
    clear_password: $('pgClearPassword').checked, sslmode: $('pgSslmode').value,
    sample_seconds: Number($('pgSampleSeconds').value), retention_days: Number($('pgRetentionDays').value), include_containers: $('pgIncludeContainers').checked };
}

function pgStatus(data) {
  $('pgStatus').textContent = `${data.enabled ? 'Collection enabled' : 'Collection disabled'} · ${data.status.last_saved ? `Last saved ${new Date(data.status.last_saved).toLocaleString()}` : 'No sample saved in this process yet'}.${data.status.error ? ` ${data.status.error}` : ''}`;
}

async function loadHistorySettings() {
  try {
    const data = await api('/api/metrics/settings');
    for (const [id, key] of Object.entries({ pgHost:'host', pgPort:'port', pgDatabase:'database', pgUsername:'username', pgSslmode:'sslmode', pgSampleSeconds:'sample_seconds', pgRetentionDays:'retention_days' })) $(id).value = data[key];
    $('pgEnabled').checked = data.enabled;
    $('pgIncludeContainers').checked = data.include_containers;
    $('pgPassword').value = '';
    $('pgClearPassword').checked = false;
    $('pgPasswordHint').textContent = data.password_set ? 'Password saved. Leave blank to keep it.' : 'No password saved.';
    historySettingsLoaded = true;
    pgStatus(data);
  } catch (error) { $('pgFeedback').textContent = error.message; }
}

document.addEventListener('click', event => {
  const metric = event.target.closest('[data-metric-page]');
  if (metric) openMetricPage(metric.dataset.metricPage);
  if (event.target.closest('[data-history-settings]')) document.querySelector('[data-view="database"]').click();
});
document.querySelectorAll('.nav-item[data-view]').forEach(btn => btn.addEventListener('click', () => {
  historyRequest++;
  document.querySelector('.history-nav').classList.remove('active');
  if (btn.dataset.view === 'database' && !historySettingsLoaded) loadHistorySettings();
}));
$('historyRange').addEventListener('change', () => loadHistory(true));
$('historyContainer').addEventListener('change', () => loadHistory(true));
$('historyRefresh').addEventListener('click', () => loadHistory());
$('historySettingsForm').addEventListener('submit', async event => {
  event.preventDefault();
  $('pgSave').disabled = true;
  try {
    const data = await api('/api/metrics/settings', { method: 'PUT', body: JSON.stringify(pgPayload()) });
    $('pgPassword').value = '';
    $('pgClearPassword').checked = false;
    $('pgPasswordHint').textContent = data.password_set ? 'Password saved. Leave blank to keep it.' : 'No password saved.';
    $('pgFeedback').textContent = 'Settings saved. Collection status updates below; a successful save does not imply a successful database connection.';
    pgStatus(data);
  } catch (error) { $('pgFeedback').textContent = error.message; }
  finally { $('pgSave').disabled = false; }
});
$('pgTest').addEventListener('click', async () => {
  if (!$('historySettingsForm').reportValidity()) return;
  $('pgTest').disabled = true;
  $('pgFeedback').textContent = 'Testing connection…';
  try {
    const data = await api('/api/metrics/test', { method: 'POST', body: JSON.stringify(pgPayload()) });
    $('pgFeedback').textContent = `PostgreSQL ${Math.floor(data.server_version / 10000)}: ${data.message}${!data.can_create_schema && !data.schema_exists ? ' This role cannot create the required schema.' : ''}`;
  } catch (error) { $('pgFeedback').textContent = error.message; }
  finally { $('pgTest').disabled = false; }
});
window.addEventListener('hashchange', () => {
  const metric = location.hash.split('/')[1];
  if (location.hash.startsWith('#metrics/') && METRIC_PAGES[metric]) openMetricPage(metric);
  else if ($('metricDetailView').classList.contains('active')) document.querySelector('[data-view="home"]').click();
});
if (location.hash.startsWith('#metrics/')) openMetricPage(location.hash.split('/')[1]);
window.addEventListener('resize', () => {
  if (lastHistoryData && $('metricDetailView').classList.contains('active')) renderHistory(lastHistoryData);
});
setInterval(async () => {
  if (document.hidden) return;
  if ($('metricDetailView').classList.contains('active')) loadHistory();
  if ($('databaseView').classList.contains('active')) {
    try { pgStatus(await api('/api/metrics/settings')); } catch (_) { /* Keep editable settings available. */ }
  }
}, 30000);
