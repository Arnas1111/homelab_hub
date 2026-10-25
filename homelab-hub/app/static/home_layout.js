const HOME_CATALOG = [
  ['welcome', 'Search & server', '⌕'],
  ['host', 'Performance', '▥'], ['services', 'Favorites', '▦'],
  ['clock', 'Clock', '◷'], ['notes', 'Notes', '▤'],
];
const HOME_DEFAULT = ['welcome','host','services','clock'].map(id =>
  ({id, width:['welcome','host','services'].includes(id) ? 3 : 1}));
let homeLayout = HOME_DEFAULT.map(row => ({...row}));
let homeEditSnapshot = null, homeDragId = null, homeNoteDraft = '', homeSelectedId = null;
const homeModule = id => $('homeModules').querySelector(`[data-home-module="${id}"]`);
const homeEditing = () => $('homeView').classList.contains('home-editing');

function renderHomeLayout() {
  const host = $('homeModules');
  for (const {id, width, accent} of homeLayout) {
    const node = homeModule(id);
    if (node) { node.hidden = false; node.dataset.width = String(width); node.dataset.accent = accent || 'default'; host.append(node); }
  }
  for (const node of host.querySelectorAll('[data-home-module]'))
    if (!homeLayout.some(row => row.id === node.dataset.homeModule)) node.hidden = true;
  $('homeNoteText').textContent = homeLayout.find(row => row.id === 'notes')?.content || 'Add a note in edit mode.';
  for (const node of host.querySelectorAll('[data-home-module]')) node.classList.toggle('home-selected', homeEditing() && node.dataset.homeModule === homeSelectedId);
  renderHomePalette();
  renderHomeInspector();
}
function updateHomeClock() {
  const now = new Date();
  $('homeClock').textContent = now.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  $('homeClock').dateTime = now.toISOString();
  $('homeClockDate').textContent = now.toLocaleDateString([], {weekday:'long', day:'numeric', month:'long'});
}
function renderHomePalette() {
  const tray = $('homePaletteItems'); tray.replaceChildren();
  if (!homeEditing()) return;
  for (const [id, label, symbol] of HOME_CATALOG) {
    if (homeLayout.some(row => row.id === id)) continue;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'home-palette-item';
    button.innerHTML = `<span aria-hidden="true">${symbol}</span><strong>${escapeHtml(label)}</strong><span aria-hidden="true">＋</span>`;
    button.onclick = () => {
      homeLayout.push({id, width:['welcome','host','services'].includes(id) ? 3 : 1, ...(id === 'notes' ? {content:homeNoteDraft} : {})});
      homeSelectedId = id; renderHomeLayout();
      if (id === 'notes') $('homeInspectorNote')?.focus();
    };
    tray.append(button);
  }
  if (!tray.children.length) tray.textContent = 'All modules are on the dashboard.';
}
function renderHomeInspector() {
  const host = $('homeInspector'); host.replaceChildren();
  if (!homeEditing()) return;
  const row = homeLayout.find(item => item.id === homeSelectedId);
  if (!row) { host.innerHTML = '<h3>Selected card</h3><p class="muted tiny">Choose a card on the canvas to adjust it.</p>'; return; }
  const label = HOME_CATALOG.find(item => item[0] === row.id)[1];
  const heading = document.createElement('h3'); heading.textContent = label; host.append(heading);
  const widthLabel = document.createElement('span'); widthLabel.className = 'muted tiny'; widthLabel.textContent = 'Card width'; host.append(widthLabel);
  const widths = document.createElement('div'); widths.className = 'home-inspector-options';
  for (const width of [1,2,3]) {
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'home-inspector-option'; button.textContent = width === 1 ? 'Small' : width === 2 ? 'Medium' : 'Wide';
    button.setAttribute('aria-pressed', String(row.width === width));
    button.onclick = () => { row.width = width; renderHomeLayout(); };
    widths.append(button);
  }
  host.append(widths);
  const colorLabel = document.createElement('span'); colorLabel.className = 'muted tiny'; colorLabel.textContent = 'Accent'; host.append(colorLabel);
  const colors = document.createElement('div'); colors.className = 'home-color-options';
  for (const color of ['default','blue','mint','amber','rose','violet']) {
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'home-color-option'; button.dataset.color = color;
    button.title = color; button.setAttribute('aria-label', color + ' accent');
    button.setAttribute('aria-pressed', String((row.accent || 'default') === color));
    button.onclick = () => { row.accent = color; renderHomeLayout(); };
    colors.append(button);
  }
  host.append(colors);
  if (row.id === 'notes') {
    const noteLabel = document.createElement('label'); noteLabel.className = 'home-inspector-note';
    noteLabel.textContent = 'Note';
    const input = document.createElement('textarea'); input.id = 'homeInspectorNote';
    input.maxLength = 2000; input.value = row.content || homeNoteDraft;
    input.oninput = () => { row.content = input.value; homeNoteDraft = input.value; };
    noteLabel.append(input); host.append(noteLabel);
  }
}
function moveHomeModule(id, direction) {
  const index = homeLayout.findIndex(row => row.id === id), next = index + direction;
  if (index < 0 || next < 0 || next >= homeLayout.length) return;
  [homeLayout[index], homeLayout[next]] = [homeLayout[next], homeLayout[index]];
  renderHomeLayout(); homeModule(id).querySelector('.home-drag-handle').focus();
}
function installHomeControls() {
  for (const node of $('homeModules').querySelectorAll('[data-home-module]')) {
    const id = node.dataset.homeModule, label = HOME_CATALOG.find(row => row[0] === id)[1];
    const controls = document.createElement('div'); controls.className = 'home-tile-controls';
    controls.innerHTML = `<button type="button" class="home-drag-handle" draggable="true" title="Drag ${escapeHtml(label)}" aria-label="Drag ${escapeHtml(label)}">⠿ <span>${escapeHtml(label)}</span></button><span class="home-tile-actions"><button type="button" data-home-action="up" aria-label="Move ${escapeHtml(label)} earlier" title="Move earlier">↑</button><button type="button" data-home-action="down" aria-label="Move ${escapeHtml(label)} later" title="Move later">↓</button><button type="button" data-home-action="resize" aria-label="Resize ${escapeHtml(label)}" title="Change width">↔</button><button type="button" data-home-action="remove" aria-label="Remove ${escapeHtml(label)}" title="Remove from Home">×</button></span>`;
    node.prepend(controls);
    const preview = document.createElement('div'); preview.className = 'home-edit-preview';
    preview.innerHTML = `<span class="home-edit-preview-icon" aria-hidden="true">${HOME_CATALOG.find(row => row[0] === id)[2]}</span><strong>${escapeHtml(label)}</strong>${id === 'services' ? '<div id="homeFavoritePreview" class="home-favorite-preview"></div>' : ''}`;
    controls.after(preview);
    controls.querySelector('.home-drag-handle').addEventListener('click', () => { homeSelectedId = id; renderHomeLayout(); });
    controls.addEventListener('click', event => {
      const action = event.target.closest('[data-home-action]')?.dataset.homeAction;
      if (!action) return;
      if (action === 'up' || action === 'down') moveHomeModule(id, action === 'up' ? -1 : 1);
      if (action === 'resize') { const row = homeLayout.find(item => item.id === id); row.width = row.width % 3 + 1; renderHomeLayout(); }
      if (action === 'remove') {
        if (id === 'notes') homeNoteDraft = homeLayout.find(item => item.id === id)?.content || '';
        homeLayout = homeLayout.filter(item => item.id !== id);
        if (homeSelectedId === id) homeSelectedId = null;
        renderHomeLayout();
      }
    });
    controls.querySelector('.home-drag-handle').addEventListener('dragstart', event => {
      homeDragId = id; homeSelectedId = id; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', id);
      node.classList.add('home-dragging');
    });
    controls.querySelector('.home-drag-handle').addEventListener('dragend', () => {
      homeDragId = null; node.classList.remove('home-dragging');
      for (const tile of $('homeModules').children) tile.classList.remove('home-drop-target');
    });
    let touchPointer = null;
    const grip = controls.querySelector('.home-drag-handle');
    grip.addEventListener('pointerdown', event => {
      if (!homeEditing() || event.pointerType === 'mouse') return;
      touchPointer = event.pointerId; grip.setPointerCapture(event.pointerId);
      node.classList.add('home-dragging'); event.preventDefault();
    });
    grip.addEventListener('pointermove', event => {
      if (touchPointer !== event.pointerId) return;
      for (const tile of $('homeModules').children) tile.classList.remove('home-drop-target');
      const target = document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-home-module]');
      if (target && target !== node) target.classList.add('home-drop-target');
    });
    grip.addEventListener('pointerup', event => {
      if (touchPointer !== event.pointerId) return;
      const targetId = document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-home-module]')?.dataset.homeModule;
      touchPointer = null; node.classList.remove('home-dragging');
      for (const tile of $('homeModules').children) tile.classList.remove('home-drop-target');
      if (!targetId || targetId === id) return;
      const source = homeLayout.find(row => row.id === id);
      homeLayout = homeLayout.filter(row => row.id !== id);
      homeLayout.splice(homeLayout.findIndex(row => row.id === targetId),0,source);
      renderHomeLayout();
    });
    grip.addEventListener('pointercancel', () => { touchPointer = null; node.classList.remove('home-dragging'); });
    node.addEventListener('dragover', event => {
      if (!homeEditing() || !homeDragId || homeDragId === id) return;
      event.preventDefault(); node.classList.add('home-drop-target');
    });
    node.addEventListener('dragleave', () => node.classList.remove('home-drop-target'));
    node.addEventListener('drop', event => {
      event.preventDefault(); event.stopPropagation(); node.classList.remove('home-drop-target');
      if (!homeDragId || homeDragId === id) return;
      const source = homeLayout.find(row => row.id === homeDragId);
      homeLayout = homeLayout.filter(row => row.id !== homeDragId);
      homeLayout.splice(homeLayout.findIndex(row => row.id === id), 0, source);
      renderHomeLayout();
    });
    node.addEventListener('click', event => {
      if (homeEditing() && !event.target.closest('.home-tile-controls,.home-favorite-preview')) {
        homeSelectedId = id; renderHomeLayout();
        event.preventDefault(); event.stopPropagation();
      }
    }, true);
  }
  $('homeModules').addEventListener('dragover', event => { if (homeEditing() && homeDragId) event.preventDefault(); });
  $('homeModules').addEventListener('drop', event => {
    if (event.target.closest('[data-home-module]') || !homeDragId) return;
    event.preventDefault(); const row = homeLayout.find(item => item.id === homeDragId);
    homeLayout = homeLayout.filter(item => item.id !== homeDragId); homeLayout.push(row); renderHomeLayout();
  });
}
function setHomeEditMode(enabled) {
  $('homeView').classList.toggle('home-editing', enabled);
  $('homePalette').hidden = !enabled; $('homeEditBar').hidden = !enabled;
  $('customizeHome').hidden = enabled;
  if (!enabled) homeSelectedId = null;
  $('homeLayoutFeedback').textContent = '';
  renderHomePalette(); renderHomeInspector();
  if (enabled && currentData && typeof renderBoard === 'function') renderBoard();
}
$('customizeHome').onclick = () => { homeEditSnapshot = homeLayout.map(row => ({...row})); setHomeEditMode(true); };
$('homeCancelEdit').onclick = () => {
  homeLayout = homeEditSnapshot.map(row => ({...row}));
  homeEditSnapshot = null; setHomeEditMode(false); renderHomeLayout();
};
$('homeSaveEdit').onclick = async () => {
  $('homeSaveEdit').disabled = true;
  try {
    const result = await api('/api/home/layout', {method:'PUT', body:JSON.stringify({modules:homeLayout})});
    homeLayout = result.modules; homeEditSnapshot = null;
    setHomeEditMode(false); renderHomeLayout();
  } catch (error) { $('homeLayoutFeedback').textContent = error.message; }
  finally { $('homeSaveEdit').disabled = false; }
};
async function initializeHomeLayout() {
  try {
    const result = await api('/api/home/layout');
    if (Array.isArray(result.modules)) homeLayout = result.modules.filter(row => HOME_CATALOG.some(([id]) => id === row.id));
  } catch (_) { /* Home remains usable if preferences are unavailable. */ }
  renderHomeLayout();
}
installHomeControls(); renderHomeLayout(); initializeHomeLayout(); updateHomeClock();
setInterval(updateHomeClock, 15000);
