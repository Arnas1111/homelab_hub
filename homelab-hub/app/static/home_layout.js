/* The catalog reuses the live Home components instead of duplicating their IDs. */
const HOME_CATALOG = [
  ['welcome','Welcome & search'], ['status','Discovery status'], ['host','Host readings'],
  ['services','Favorite services'], ['attention','Needs attention'],
  ['connections','Connections'], ['zigbee','Zigbee overview'],
];
const HOME_DEFAULT = ['welcome','status','host','services','attention','connections'].map(id =>
  ({id, width:['welcome','status','host','services'].includes(id) ? 2 : 1}));
let homeLayout = HOME_DEFAULT.map(row => ({...row}));

function renderHomeLayout() {
  const host = $('homeModules');
  for (const {id, width} of homeLayout) {
    const node = host.querySelector(`[data-home-module="${id}"]`);
    if (node) { node.hidden = false; node.dataset.width = width; host.append(node); }
  }
  for (const node of host.querySelectorAll('[data-home-module]'))
    if (!homeLayout.some(row => row.id === node.dataset.homeModule)) node.hidden = true;
  if (homeLayout.some(row => row.id === 'zigbee')) loadHomeZigbee();
}
async function loadHomeZigbee() {
  if (!homeLayout.some(row => row.id === 'zigbee') || document.hidden) return;
  try {
    const data = await api('/api/v1/objects?module=zigbee');
    const objects = data.objects || [], online = objects.filter(item => item.available).length;
    $('homeZigbee').textContent = `${objects.length} devices · ${online} available`;
  } catch (error) { $('homeZigbee').textContent = 'Zigbee status unavailable'; }
}
function renderHomeEditor() {
  const host = $('homeModuleList'); host.replaceChildren();
  const active = new Map(homeLayout.map((row, index) => [row.id, {row,index}]));
  for (const [id, label] of HOME_CATALOG) {
    const wrapper = document.createElement('div'); wrapper.className = 'home-layout-row'; wrapper.dataset.module = id;
    const enabled = active.has(id);
    wrapper.innerHTML = `<label class="check"><input type="checkbox" data-enabled ${enabled ? 'checked' : ''}>${escapeHtml(label)}</label>
      <label>Width <select data-width><option value="1">Half</option><option value="2">Full</option></select></label>
      <button type="button" class="btn" data-move="-1" aria-label="Move ${escapeHtml(label)} up">↑</button>
      <button type="button" class="btn" data-move="1" aria-label="Move ${escapeHtml(label)} down">↓</button>`;
    wrapper.querySelector('[data-width]').value = String(active.get(id)?.row.width || 1);
    wrapper.querySelector('[data-enabled]').onchange = event => {
      if (event.target.checked) homeLayout.push({id, width:Number(wrapper.querySelector('[data-width]').value)});
      else homeLayout = homeLayout.filter(row => row.id !== id);
      renderHomeLayout(); renderHomeEditor();
    };
    wrapper.querySelector('[data-width]').onchange = event => {
      const row = homeLayout.find(row => row.id === id);
      if (row) { row.width = Number(event.target.value); renderHomeLayout(); }
    };
    for (const button of wrapper.querySelectorAll('[data-move]')) button.onclick = () => {
      const index = homeLayout.findIndex(row => row.id === id);
      const other = index + Number(button.dataset.move);
      if (index < 0 || other < 0 || other >= homeLayout.length) return;
      [homeLayout[index], homeLayout[other]] = [homeLayout[other], homeLayout[index]];
      renderHomeLayout(); renderHomeEditor();
    };
    wrapper.style.order = enabled ? active.get(id).index : HOME_CATALOG.length + HOME_CATALOG.findIndex(row => row[0] === id);
    host.append(wrapper);
  }
}
$('customizeHome').onclick = () => { renderHomeEditor(); $('homeLayoutDialog').showModal(); };
$('homeLayoutClose').onclick = () => $('homeLayoutDialog').close();
$('homeLayoutForm').onsubmit = async event => {
  event.preventDefault();
  try {
    const result = await api('/api/home/layout', {method:'PUT', body:JSON.stringify({modules:homeLayout})});
    homeLayout = result.modules; renderHomeLayout(); $('homeLayoutDialog').close();
  } catch (error) { $('homeLayoutFeedback').textContent = error.message; }
};
async function initializeHomeLayout() {
  try {
    const result = await api('/api/home/layout');
    if (Array.isArray(result.modules)) homeLayout = result.modules.filter(row => HOME_CATALOG.some(([id]) => id === row.id));
  } catch (_) { /* Home remains usable if the preference endpoint is unavailable. */ }
  renderHomeLayout();
}
renderHomeLayout(); initializeHomeLayout();
setInterval(loadHomeZigbee, 30000);
