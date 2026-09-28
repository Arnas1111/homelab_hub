/* Recent log investigation is independent of overview and metric polling. */
let aggregateLogRequest = 0;
let aggregateLogTimer = null;
let aggregateLogSearchTimer = null;

function aggregateLogsActive() { return $('logsView').classList.contains('active'); }

async function loadAggregateLogs() {
  clearTimeout(aggregateLogTimer);
  const request = ++aggregateLogRequest;
  const params = new URLSearchParams({level:$('aggregateLogLevel').value,
    service:$('aggregateLogService').value, minutes:$('aggregateLogRange').value,
    q:$('aggregateLogSearch').value.trim()});
  let delay = 15000;
  try {
    const data = await api(`/api/logs?${params}`);
    if (request !== aggregateLogRequest || !aggregateLogsActive()) return;
    const selected = $('aggregateLogService').value;
    const options = '<option value="">All containers</option>' + data.services.map(s => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`).join('');
    if (document.activeElement !== $('aggregateLogService')) {
      patchContent($('aggregateLogService'), options);
      $('aggregateLogService').value = data.services.some(s => s.id === selected) ? selected : '';
    }
    const errors = data.services.filter(s => s.error);
    const limited = data.services.filter(s => s.limited);
    const collecting = data.loading && !data.updated_at;
    delay = collecting ? 1000 : 15000;
    $('aggregateLogStatus').textContent = data.error || (collecting ? 'Collecting recent logs in the background...' : `${data.entries.length} of ${data.matched} matching captured lines${data.updated_at ? ` · collected ${new Date(data.updated_at).toLocaleTimeString()}` : ''}${data.loading ? ' · updating' : ''}${errors.length ? ` · ${errors.length} unreadable sources` : ''}${data.limited ? ' · result limit reached; narrow your filters' : ''}`);
    $('aggregateLogStatus').classList.toggle('attention', Boolean(data.error || errors.length));
    patchContent($('aggregateLogCounts'), ['critical','error','warning','info','debug','unknown'].map(level => `<button class="log-count log-level-${level} ${data.counts[level] > 0 ? 'has-events' : ''}" data-log-level="${level}"><strong>${data.counts[level] || 0}</strong><span>${level}</span></button>`).join(''));
    patchContent($('aggregateLogCoverageBody'), `<p>${escapeHtml(data.scope)}</p><p>Counts describe captured lines matching the service, time and text filters, before the severity filter. Logs without timestamps cannot be time-filtered. Collection runs while this page is viewed; rotated or deleted Docker logs cannot be recovered.</p><p>Common credential fields are masked, but applications can log sensitive content in arbitrary formats. This view uses the Hub's administrator session.</p>${data.container_limit_reached ? '<p class="attention">Only the first 200 containers were collected.</p>' : ''}${limited.length ? `<p class="attention">Capture limit reached: ${limited.map(s => escapeHtml(s.name)).join(', ')}. Some lines may be missing.</p>` : ''}${errors.length ? `<ul>${errors.map(s => `<li><strong>${escapeHtml(s.name)}</strong>: ${escapeHtml(s.error)}</li>`).join('')}</ul>` : ''}`);
    patchContent($('aggregateLogRows'), data.entries.length ? data.entries.map(entry => `<article class="aggregate-log-entry log-level-${escapeHtml(entry.level)}"><div class="aggregate-log-meta"><time>${entry.time ? escapeHtml(new Date(entry.time).toLocaleString()) : 'No timestamp'}</time><strong>${escapeHtml(entry.service)}</strong><span class="log-severity">${escapeHtml(entry.level)}</span><span class="log-detection">${escapeHtml(entry.detection)}</span><button class="text-btn" data-log-context="${escapeHtml(entry.container_id)}">Service context</button></div><pre>${escapeHtml(entry.message)}</pre></article>`).join('') : `<div class="board-empty">${collecting ? 'Waiting for the first snapshot...' : data.error ? 'No collected logs are available.' : errors.length ? 'No matching lines in the readable sources. Check collection coverage.' : 'No matching lines in the captured logs. This does not establish that every service is healthy.'}</div>`);
  } catch (error) {
    if (request === aggregateLogRequest) $('aggregateLogStatus').textContent = `Refresh failed; previous results retained. ${error.message}`;
  } finally {
    if (request === aggregateLogRequest && aggregateLogsActive() && $('aggregateLogLive').checked) {
      aggregateLogTimer = setTimeout(() => { if (!document.hidden && aggregateLogsActive()) loadAggregateLogs(); }, delay);
    }
  }
}

for (const id of ['aggregateLogService','aggregateLogLevel','aggregateLogRange']) $(id).addEventListener('change', loadAggregateLogs);
$('aggregateLogsRefresh').addEventListener('click', loadAggregateLogs);
$('aggregateLogLive').addEventListener('change', () => { if ($('aggregateLogLive').checked) loadAggregateLogs(); else clearTimeout(aggregateLogTimer); });
$('aggregateLogSearch').addEventListener('input', () => { clearTimeout(aggregateLogSearchTimer); aggregateLogSearchTimer = setTimeout(loadAggregateLogs, 250); });
$('logsView').addEventListener('click', event => {
  const level = event.target.closest('[data-log-level]');
  const context = event.target.closest('[data-log-context]');
  if (level) { $('aggregateLogLevel').value = level.dataset.logLevel; loadAggregateLogs(); }
  if (context) {
    $('aggregateLogService').value = context.dataset.logContext;
    $('aggregateLogLevel').value = 'all';
    $('aggregateLogSearch').value = '';
    loadAggregateLogs();
  }
});
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && aggregateLogsActive() && $('aggregateLogLive').checked) loadAggregateLogs();
});
