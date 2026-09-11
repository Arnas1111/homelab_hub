const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/static/history.js'), 'utf8');
function context() {
  const elements = { historyContainer: { value: '' }, historyContent: {}, historyNotice: {} };
  const ctx = vm.createContext({
    $: id => elements[id], bytes: n => `${n} B`, escapeHtml: value => String(value).replace(/</g, '&lt;'),
    patchContent: (el, html) => el.html = html,
  });
  vm.runInContext(source.slice(source.indexOf('function historyFormat'), source.indexOf('async function loadHistory')), ctx);
  return { ctx, elements };
}
test('history charts show gaps, missing values and CPU above one core', () => {
  const { ctx } = context();
  assert.equal(ctx.historyFormat(null, '%'), '—');
  assert.equal(ctx.historyFormat(200, '% cores'), '200.0%');
  const series = { key: 'cpu', label: 'CPU', unit: '% cores' };
  const points = [{ time: '2026-01-01T00:00:00Z', cpu: 200, cpu_max: 200 }, { time: '2026-01-01T00:00:30Z', cpu: null, cpu_max: null }, { time: '2026-01-01T00:01:00Z', cpu: 100, cpu_max: 100 }];
  const html = ctx.historyChart(points, series, points[0].time, points[2].time, 30);
  const average = html.match(/class="history-average" d="([^"]+)"/)[1];
  assert.equal((average.match(/M/g) || []).length, 2);
  assert.doesNotMatch(average, /L/);
  assert.match(html, /200.0%/);
});
test('range averages weight valid samples and expose accessible sampled values', () => {
  const { ctx, elements } = context();
  ctx.renderHistory({ metric: 'cpu', start: '2026-01-01T00:00:00Z', end: '2026-01-01T01:00:00Z', bucket_seconds: 30,
    sample_seconds: 30, retention_days: 30, enabled: true,
    series: [{ key: 'cpu_percent', label: 'CPU', unit: '%' }],
    points: [{ time: '2026-01-01T00:00:00Z', cpu_percent: 10, cpu_percent_max: 10, cpu_percent_count: 1 }, { time: '2026-01-01T00:00:30Z', cpu_percent: 30, cpu_percent_max: 40, cpu_percent_count: 3 }],
    latest: { sampled_at: '2026-01-01T00:00:30Z', payload: { cpu_percent: 40, cores: { cpu0: 40 } } },
  });
  assert.match(elements.historyContent.html, /25.0%/);
  assert.match(elements.historyContent.html, /View sampled values/);
  assert.match(elements.historyNotice.textContent, /Samples are stale/);
});
