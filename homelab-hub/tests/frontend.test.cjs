const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');

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
