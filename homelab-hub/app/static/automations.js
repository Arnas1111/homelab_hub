let automationObjects = [], automationRules = [], automationEditing = null, automationBusy = false;
const automationOptions = (items, selected) => items.map(([value, label]) => `<option value="${escapeHtml(value)}"${value === selected ? ' selected' : ''}>${escapeHtml(label)}</option>`).join('');

function automationProperties(selected, value) {
  const object = automationObjects.find(o => o.id === $('automationSource').value);
  const entries = Object.entries(object?.capabilities || {}).filter(([, cap]) => ['boolean', 'enum', 'number'].includes(cap.type));
  $('automationProperty').innerHTML = automationOptions(entries.map(([key, cap]) => [key, cap.label || key]), selected);
  automationValue(value);
}
function automationValue(value) {
  const object = automationObjects.find(o => o.id === $('automationSource').value);
  const cap = object?.capabilities[$('automationProperty').value];
  const host = $('automationValueHost');
  host.replaceChildren();
  const input = document.createElement(cap?.type === 'number' ? 'input' : 'select');
  input.id = 'automationValue'; input.required = true;
  if (cap?.type === 'number') { input.type = 'number'; input.step = 'any'; input.value = value ?? 0; }
  else input.innerHTML = automationOptions((cap?.type === 'boolean' ? ['true', 'false'] : cap?.options || []).map(v => [v, v]), String(value ?? 'true'));
  host.append(input);
}
function automationDevices() {
  const source = $('automationSource').value, target = $('automationTarget').value;
  $('automationSource').innerHTML = automationOptions(automationObjects.filter(o => o.type === 'sensor' && Object.values(o.capabilities).some(c => ['boolean', 'enum', 'number'].includes(c.type))).map(o => [o.id, o.name]), source);
  $('automationTarget').innerHTML = automationOptions(automationObjects.filter(o => o.actions.includes('set_power')).map(o => [o.id, o.name]), target);
  automationProperties();
}
function automationRender() {
  const host = $('automationRules');
  const ids = new Set(automationRules.map(r => r.id));
  for (const node of [...host.children]) if (!ids.has(node.dataset.rule)) node.remove();
  if (!automationRules.length) { host.textContent = 'No automations yet. Add your first motion or button rule.'; return; }
  if (!host.firstElementChild) host.textContent = '';
  for (const rule of automationRules) {
    let card = [...host.children].find(n => n.dataset.rule === rule.id);
    if (!card) {
      card = document.createElement('article'); card.className = 'panel automation-card'; card.dataset.rule = rule.id;
      card.innerHTML = '<h3></h3><p class="automation-summary"></p><p class="muted automation-state"></p><div class="automation-pair"><button class="btn" data-edit>Edit</button><button class="btn" data-delete>Delete</button></div>';
      card.querySelector('[data-edit]').onclick = () => automationEdit(card.dataset.rule);
      card.querySelector('[data-delete]').onclick = async () => {
        if (!confirm('Delete this automation? An existing switch-off timer will still finish.')) return;
        try { await api('/api/zigbee/automations/' + rule.id, {method:'DELETE'}); if (automationEditing === rule.id) automationReset(); await loadAutomations(); }
        catch (e) { $('automationFeedback').textContent = e.message; }
      };
      host.append(card);
    }
    const name = id => automationObjects.find(o => o.id === id)?.name || id;
    card.querySelector('h3').textContent = rule.name + (rule.enabled ? '' : ' · Disabled');
    card.querySelector('.automation-summary').textContent = `${name(rule.source)}: ${rule.property} = ${rule.equals} → ${name(rule.target)} on → ${rule.seconds}s → off`;
    card.querySelector('.automation-state').textContent = rule.status + (rule.off_at ? ` · Off due ${new Date(rule.off_at * 1000).toLocaleTimeString()}` : '');
  }
}
function automationEdit(id) {
  const rule = automationRules.find(r => r.id === id); if (!rule) return;
  automationEditing = id;
  $('automationEditorTitle').textContent = 'Edit automation';
  $('automationName').value = rule.name;
  // Keep missing devices visible so an unrelated device is never silently selected.
  for (const [field, value] of [['automationSource', rule.source], ['automationTarget', rule.target]]) {
    if (![...$(field).options].some(o => o.value === value)) $(field).add(new Option('Unavailable: ' + value, value));
    $(field).value = value;
  }
  automationProperties(rule.property, rule.equals);
  $('automationSeconds').value = rule.seconds; $('automationEnabled').checked = rule.enabled;
  $('automationName').focus();
}
function automationReset() {
  automationEditing = null; $('automationForm').reset(); $('automationEditorTitle').textContent = 'New automation';
  automationDevices(); $('automationFeedback').textContent = '';
}
async function loadAutomations() {
  if (automationBusy) return;
  automationBusy = true;
  try {
    const [data, devices] = await Promise.all([api('/api/zigbee/automations'), api('/api/v1/objects?module=zigbee')]);
    const first = !automationObjects.length;
    automationObjects = devices.objects; automationRules = data.rules;
    if (first && !automationEditing) automationDevices();
    $('automationStatus').textContent = `Zigbee: ${data.connection} · ${data.pending_count} active switch-off timer(s)`;
    automationRender();
  } catch (e) { $('automationStatus').textContent = e.message; }
  finally { automationBusy = false; }
}
$('automationSource').onchange = () => automationProperties();
$('automationProperty').onchange = () => automationValue();
$('automationCancel').onclick = automationReset;
$('automationRefresh').onclick = async () => { await loadAutomations(); if (!automationEditing) automationDevices(); };
$('automationForm').onsubmit = async event => {
  event.preventDefault();
  const cap = automationObjects.find(o => o.id === $('automationSource').value)?.capabilities[$('automationProperty').value];
  let value = $('automationValue')?.value;
  if (cap?.type === 'boolean') value = value === 'true';
  if (cap?.type === 'number') value = Number(value);
  const rule = {name:$('automationName').value.trim(), enabled:$('automationEnabled').checked, source:$('automationSource').value,
    property:$('automationProperty').value, equals:value, target:$('automationTarget').value, seconds:Number($('automationSeconds').value)};
  const submit = event.target.querySelector('[type="submit"]'); submit.disabled = true;
  try {
    await api('/api/zigbee/automations' + (automationEditing ? '/' + automationEditing : ''), {method:automationEditing ? 'PUT' : 'POST', body:JSON.stringify(rule)});
    automationReset(); $('automationFeedback').textContent = 'Automation saved.'; await loadAutomations();
  } catch (e) { $('automationFeedback').textContent = e.message; }
  finally { submit.disabled = false; }
};
setInterval(() => { if ($('automationsView').classList.contains('active') && !document.hidden) loadAutomations(); }, 5000);
