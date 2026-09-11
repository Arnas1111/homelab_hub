const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');

function metricsContext() {
  const now = Date.now();
  const points = Array.from({ length: 60 }, (_, i) => ({ time: now - (59 - i) * 5000, value: 10 + Math.sin(i) * 3 }));
  const target = {};
  const ctx = vm.createContext({
    settings: { refresh_seconds: 5 }, metricHistory: { cpu: points, memory: points.map(p => ({ ...p, value: 39.1 })) },
    currentData: { containers: [{ name: 'sonarr', cpu_percent: 11.4, memory_used: 100 }, { name: 'tdarr', cpu_percent: 2, memory_used: 800 }] },
    escapeHtml: value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;'),
    bytes: value => `${value} B`, addMetricHistory: () => {}, $: () => target,
    patchContent: (_, html) => target.html = html,
  });
  vm.runInContext(functionSource('metricLevel', 'containerTopList'), ctx);
  return { ctx, target };
}

test('utilization colors have consistent thresholds and missing data is not zero', () => {
  const { ctx } = metricsContext();
  for (const [value, expected] of [[0, 'normal'], [74.9, 'normal'], [75, 'warning'], [90, 'critical'], [null, 'unknown'], [undefined, 'unknown']]) {
    assert.equal(ctx.metricLevel(value).kind, expected);
  }
});

test('trend uses elapsed time, fixed percentage scale and breaks across gaps', () => {
  const { ctx } = metricsContext();
  const now = Date.now();
  const html = ctx.utilizationTrend([{ time: now - 90000, value: 0 }, { time: now, value: 100 }], 'CPU');
  assert.match(html, /M32.0 100.0 M360.0 12.0/);
  assert.match(html, /0 to 100 percent/);
  assert.match(ctx.utilizationTrend([{ time: now - 3600000, value: 25 }], 'CPU'), /Collecting trend/);
});

test('metrics render capacity, unavailable states and expandable details', () => {
  const { ctx, target } = metricsContext();
  ctx.renderServerMetrics({ metrics: {} });
  assert.equal((target.html.match(/utilization-status unknown/g) || []).length, 3);
  assert.match(target.html, /<details class="metrics-details">/);
  ctx.renderServerMetrics({ cpus: 4, metrics: {
    cpu: { total_percent: 9.7, cores: [{ name: 'CPU 0', percent: 9.5 }, { name: 'CPU 1', percent: 10.7 }] },
    memory: { total: 16000, percent: 39.1, used_human: '6.0 GB', total_human: '15.4 GB', available_human: '9.4 GB' },
    data_mount: { total: 180000, percent: 74.3, free_human: '478.1 GB', total_human: '1.8 TB' },
    network: { rx_rate_human: '345 B/s', tx_rate_human: '5 KB/s' },
  } });
  assert.match(target.html, /stroke-dasharray="74.3 100"/);
  assert.match(target.html, /478.1 GB/);
  const memory = target.html.split('Top containers · memory')[1];
  assert.ok(memory.indexOf('tdarr') < memory.indexOf('sonarr'));
  if (process.env.HUB_PREVIEW_PATH) {
    const css = fs.readFileSync(path.join(__dirname, '../app/static/style.css'), 'utf8');
    fs.writeFileSync(process.env.HUB_PREVIEW_PATH, `<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{padding:24px}h2{padding:18px;margin:0}</style><body><section class="panel"><h2>Server metrics</h2><div id="serverMetrics">${target.html}</div></section></body></html>`);
  }
});

function functionSource(name, nextName) {
  return source.slice(source.indexOf(`function ${name}(`), source.indexOf(`function ${nextName}(`));
}

function renderer() {
  let writes = 0;
  const table = { children: [], set innerHTML(value) { this.html = value; this.children = [{}]; writes++; } };
  const search = { value: '' };
  const ctx = vm.createContext({
    currentData: { containers: [{ id: 'a', name: 'tdarr', image: 'tdarr', ports: [], status: 'running' }] },
    collapsedGroups: new Set(), containerStructureKey: '', updates: 0, applied: 0,
    $: id => id === 'containerRows' ? table : search,
    containerSearchText: c => c.name, containerIcon: c => c.icon || 'docker',
    webuiLinkForContainer: c => c.link, escapeHtml: String, iconPath: String,
    statusBadge: c => c.status, bytes: String, portText: () => '',
    updateContainerStats: () => ctx.updates++, applySectionState: () => ctx.applied++,
  });
  vm.runInContext(functionSource('renderContainers', 'updateContainerStats') +
    functionSource('groupedContainers', 'toggleGroup'), ctx);
  return { ctx, table, search, writes: () => writes, render: () => vm.runInContext('renderContainers()', ctx) };
}

test('metric and status updates preserve container rows', () => {
  const r = renderer(); r.render();
  r.ctx.currentData.containers[0].cpu_percent = 150;
  r.ctx.currentData.containers[0].status = 'paused';
  r.render();
  assert.equal(r.writes(), 1);
  assert.equal(r.ctx.updates, 1);
});

test('group folding and unfolding update visible rows', () => {
  const r = renderer(); r.render();
  r.ctx.collapsedGroups.add('Ungrouped'); r.render();
  assert.doesNotMatch(r.table.html, /class="container-row"/);
  r.ctx.collapsedGroups.clear(); r.render();
  assert.match(r.table.html, /class="container-row"/);
  assert.equal(r.writes(), 3);
});

test('search expands groups even when the result set is unchanged', () => {
  const r = renderer(); r.ctx.collapsedGroups.add('Ungrouped'); r.render();
  r.search.value = 'tdarr'; r.render();
  assert.match(r.table.html, /class="container-row"/);
  assert.equal(r.writes(), 2);
  assert.equal(r.ctx.applied, 2);
});

test('icon, WebUI and group order changes invalidate the row cache', () => {
  const r = renderer(); r.render();
  r.ctx.currentData.containers[0].icon = 'jellyfin'; r.render();
  assert.match(r.table.html, /src="jellyfin"/);
  r.ctx.currentData.containers[0].link = { url: '/example', label: 'Example' }; r.render();
  assert.match(r.table.html, /href="\/example"/);
  r.ctx.currentData.group_order = { Ungrouped: 2 }; r.render();
  assert.equal(r.writes(), 4);
});

test('failed refresh preserves rows and schedules another attempt', async () => {
  let scheduled = 0;
  const label = {};
  const ctx = vm.createContext({
    document: { activeElement: null }, window: { scrollY: 0 },
    overviewQuery: () => '', api: async () => { throw new Error('Offline'); },
    $: () => label, toast: () => {}, scheduleRefresh: () => scheduled++,
  });
  vm.runInContext('async ' + functionSource('refresh', 'scheduleRefresh'), ctx);
  await vm.runInContext('refresh()', ctx);
  assert.equal(scheduled, 1);
  assert.match(label.textContent, /Refresh failed/);
  assert.equal(label.innerHTML, undefined);
});
