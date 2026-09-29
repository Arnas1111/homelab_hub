/* Uses only the generic object contract for rendering and actions. */
let zigbeeLoading = false;
let zigbeeSending = false;
const zigbeeCards = new Map();

function renderZigbeeObject(object) {
  const disabled = !object.available || zigbeeSending;
  const power = object.state.power;
  const brightness = object.state.brightness;
  const e = escapeHtml;
  return `<h3>${e(object.name)}</h3><p class="muted tiny">${object.available ? 'Connected' : 'Unavailable — last reported state'}</p>
    <p>Power: <strong>${power === true ? 'On' : power === false ? 'Off' : 'Unknown'}</strong>${brightness == null ? '' : ` · ${e(brightness)} %`}</p>
    ${object.actions.includes('set_power') ? `<div class="zigbee-actions"><button class="btn" data-zigbee-action="set_power" data-value="true" ${disabled ? 'disabled' : ''}>On</button><button class="btn" data-zigbee-action="set_power" data-value="false" ${disabled ? 'disabled' : ''}>Off</button></div>` : ''}
    ${object.actions.includes('set_brightness') ? `<label class="zigbee-brightness">Brightness (0–100 %)<input type="range" min="0" max="100" step="1" value="${brightness ?? 0}" aria-label="${e(object.name)} brightness" data-zigbee-action="set_brightness" ${disabled ? 'disabled' : ''}></label>` : ''}
    <p class="muted tiny">${object.updated_at ? `Last report: ${e(new Date(object.updated_at).toLocaleString())}` : 'No state report received yet'}</p>`;
}

async function loadZigbee() {
  if (zigbeeLoading || zigbeeSending) return;
  zigbeeLoading = true;
  try {
    const [modules, result] = await Promise.all([api('/api/v1/modules'), api('/api/v1/objects?module=zigbee')]);
    if (zigbeeSending) return;
    const module = modules.modules.find(item => item.id === 'zigbee');
    const messages = {
      disabled: 'Zigbee is disabled. Open Settings → Zigbee / MQTT to configure your broker.',
      authentication_failed: 'Broker rejected authentication. Check username and password in Settings → Zigbee / MQTT.',
      connecting: 'Connecting to MQTT…', connection_failed: 'MQTT connection failed. Check broker, credentials and network access.',
      configuration_error: 'MQTT configuration is invalid. Check Settings → Zigbee / MQTT.',
      subscription_failed: 'MQTT subscription failed. Check broker permissions.',
      disconnected: 'MQTT disconnected. Reconnecting automatically…',
      bridge_offline: 'MQTT connected; waiting for Zigbee2MQTT to report online.',
      online: result.objects.length ? 'Zigbee2MQTT online' : 'Zigbee2MQTT online. No supported lights discovered; pair a light in Zigbee2MQTT.'
    };
    $('zigbeeStatus').textContent = messages[module?.status] || 'Zigbee module unavailable';
    const ids = new Set(result.objects.map(object => object.id));
    for (const [id, card] of zigbeeCards) {
      if (!ids.has(id)) { card.remove(); zigbeeCards.delete(id); }
    }
    for (const object of result.objects) {
      let card = zigbeeCards.get(object.id);
      if (!card) {
        card = document.createElement('article');
        card.className = 'board-panel';
        card.dataset.objectId = object.id;
        zigbeeCards.set(object.id, card);
        $('zigbeeLights').appendChild(card);
      }
      // Preserve slider focus and its current value during polling.
      if (!card.contains(document.activeElement)) patchContent(card, renderZigbeeObject(object));
      for (const input of card.querySelectorAll('button, input')) input.disabled = !object.available;
    }
  } catch (error) {
    $('zigbeeStatus').textContent = `Unable to refresh: ${error.message}. Showing last received values.`;
    for (const card of zigbeeCards.values()) {
      for (const input of card.querySelectorAll('button, input')) input.disabled = true;
    }
  } finally { zigbeeLoading = false; }
}

async function sendZigbeeAction(control) {
  if (zigbeeSending || control.disabled) return;
  zigbeeSending = true;
  const id = control.closest('[data-object-id]').dataset.objectId;
  const value = control.dataset.zigbeeAction === 'set_power' ? control.dataset.value === 'true' : Number(control.value);
  for (const card of zigbeeCards.values()) {
    for (const input of card.querySelectorAll('button, input')) input.disabled = true;
  }
  try {
    await api(`/api/v1/objects/${encodeURIComponent(id)}/actions`, {method: 'POST', body: JSON.stringify({action: control.dataset.zigbeeAction, value})});
    $('zigbeeFeedback').textContent = 'Command sent. Waiting for the device to report its state.';
  } catch (error) { $('zigbeeFeedback').textContent = `Command failed: ${error.message}`; }
  finally { zigbeeSending = false; loadZigbee(); }
}

$('zigbeeRefresh').addEventListener('click', loadZigbee);
$('zigbeeLights').addEventListener('click', event => {
  const control = event.target.closest('button[data-zigbee-action]');
  if (control) sendZigbeeAction(control);
});
$('zigbeeLights').addEventListener('change', event => {
  if (event.target.matches('input[data-zigbee-action]')) sendZigbeeAction(event.target);
});
setInterval(() => {
  if (!document.hidden && $('zigbeeView').classList.contains('active')) loadZigbee();
}, 5000);
