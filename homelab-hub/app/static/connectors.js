/* One workspace for selecting, configuring and using service connectors. */
const CONNECTOR_TYPES = {
  unraid: {name:'Unraid', description:'Array, disks and hardware', url:'unraidUrl', fields:{unraid_url:'unraidUrl', unraid_api_key:'unraidApiKey', unraid_api_key_clear:'unraidApiKeyClear'}},
  jellyfin: {name:'Jellyfin', description:'Media activity and sessions', url:'jellyfinUrl', fields:{jellyfin_url:'jellyfinUrl', jellyfin_public_url:'jellyfinPublicUrl', jellyfin_api_key:'jellyfinApiKey', jellyfin_api_key_clear:'jellyfinApiKeyClear'}},
  home_assistant: {name:'Home Assistant', description:'Lights, controls and sensor readings', url:'homeAssistantUrl', fields:{home_assistant_url:'homeAssistantUrl', home_assistant_token:'homeAssistantToken', home_assistant_token_clear:'homeAssistantTokenClear', home_assistant_entities:'homeAssistantEntities'}},
};
let editingConnector = null;
let connectorSaving = false;

function renderConnectorCards() {
  const selected = integrationSettings?.connectors || [];
  patchContent($('connectorCards'), selected.length ? selected.map(key => {
    const type = CONNECTOR_TYPES[key];
    if (!type) return '';
    const ready = key === 'unraid' ? integrationSettings.unraid_api_key_configured : key === 'jellyfin' ? integrationSettings.jellyfin_api_key_configured : integrationSettings.home_assistant_token_configured;
    const enabled = integrationSettings[key + '_enabled'] !== false;
    return `<article class="connection-card" data-connector="${key}"><div><h3>${type.name}</h3><p>${type.description}</p><small>${!enabled ? 'Disabled' : ready ? 'Configured' : 'Setup incomplete'}</small></div><label class="check"><input type="checkbox" data-enable-connector="${key}" ${enabled ? 'checked' : ''}> Enabled</label><div class="connection-card-actions"><button class="btn" data-edit-connector="${key}">Configure</button><button class="btn" data-reconnect-connector="${key}" ${enabled ? '' : 'disabled'}>Reconnect</button><button class="text-btn" data-remove-connector="${key}">Remove connection</button></div></article>`;
  }).join('') : '<div class="board-empty">No integrations added yet. Use + Add integration to connect a service.</div>');
  $('unraidPanel').hidden = !selected.includes('unraid') || integrationSettings.unraid_enabled === false;
  renderIntegrations();
}

async function loadConnectorWorkspace() {
  try {
    integrationSettings = await api('/api/integration-settings');
    renderConnectorCards();
    loadUnraid();
    loadIntegrations();
  } catch (error) { $('connectorCards').textContent = error.message; }
}

async function showConnectorPicker() {
  // Read the current configuration before offering unused connectors.
  try {
    integrationSettings = await api('/api/integration-settings');
    const available = Object.entries(CONNECTOR_TYPES).filter(([key]) => !integrationSettings.connectors.includes(key));
    $('connectorOptions').innerHTML = available.length ? available.map(([key, type]) => `<button class="connector-option" data-add-connector="${key}"><strong>${type.name}</strong><span>${type.description}</span></button>`).join('') : '<p class="muted">All available integrations have been added.</p>';
    $('connectorPicker').showModal();
  } catch (error) { toast(error.message); }
}

async function editConnector(key) {
  const type = CONNECTOR_TYPES[key];
  if (!type) return;
  try {
    fillIntegrationSettingsForm(await api('/api/integration-settings'));
    editingConnector = key;
    const article = $(type.url).closest('.connector-card');
    document.querySelectorAll('#integrationSettingsForm .connector-card').forEach(card => {
      card.hidden = card !== article;
      card.querySelectorAll('input,textarea').forEach(input => input.disabled = card !== article);
    });
    $(type.url).required = true;
    $('connectorEditorTitle').textContent = `Connect ${type.name}`;
    $('integrationSettingsSaved').textContent = '';
    $('connectorPicker').close();
    $('connectorEditor').showModal();
  } catch (error) { toast(error.message); }
}

async function saveConnectorConfiguration() {
  if (!editingConnector || connectorSaving) return;
  connectorSaving = true;
  $('saveConnector').disabled = true;
  const type = CONNECTOR_TYPES[editingConnector];
  try {
    const payload = Object.fromEntries(Object.entries(type.fields).map(([key, id]) => [key, $(id).type === 'checkbox' ? $(id).checked : $(id).value]));
    integrationSettings = await api('/api/integration-settings', {method:'PUT', body:JSON.stringify(payload)});
    fillIntegrationSettingsForm(integrationSettings);
    integrationData = null;
    renderConnectorCards();
    $('connectorEditor').close();
    editingConnector = null;
    loadUnraid();
    loadIntegrations({force:true});
    refresh();
    toast('Connection saved.');
  } catch (error) { $('integrationSettingsSaved').textContent = error.message; }
  finally { connectorSaving = false; $('saveConnector').disabled = false; }
}

$('addConnector').addEventListener('click', showConnectorPicker);
$('connectorEditor').addEventListener('cancel', event => { if (connectorSaving) event.preventDefault(); });
document.addEventListener('change', async event => {
  const toggle = event.target.closest('[data-enable-connector]');
  if (!toggle) return;
  toggle.disabled = true;
  try {
    integrationSettings = await api('/api/integration-settings', {method:'PUT', body:JSON.stringify({[toggle.dataset.enableConnector + '_enabled']:toggle.checked})});
    integrationData = null;
    renderConnectorCards();
    loadUnraid(); loadIntegrations({force:true});
  } catch (error) { toggle.checked = !toggle.checked; toast(error.message); }
  finally { toggle.disabled = false; }
});
document.addEventListener('click', async event => {
  const reconnect = event.target.closest('[data-reconnect-connector]');
  if (reconnect) {
    reconnect.disabled = true;
    try {
      await api(`/api/connectors/${reconnect.dataset.reconnectConnector}/reconnect`, {method:'POST'});
      loadUnraid(); loadIntegrations({force:true});
      toast('Checking connection.');
    } catch (error) { toast(error.message); }
    finally { reconnect.disabled = false; }
  }
  const edit = event.target.closest('[data-add-connector], [data-edit-connector]');
  if (edit) editConnector(edit.dataset.addConnector || edit.dataset.editConnector);
  if (event.target.closest('[data-close-connector]') && !connectorSaving) $('connectorEditor').close();
  if (event.target.closest('[data-close-picker]')) $('connectorPicker').close();
  const remove = event.target.closest('[data-remove-connector]');
  if (remove) {
    remove.disabled = true;
    try {
      integrationSettings = await api(`/api/connectors/${remove.dataset.removeConnector}`, {method:'DELETE'});
      integrationData = null;
      renderConnectorCards();
      loadIntegrations({force:true});
      refresh();
    } catch (error) { toast(error.message); }
    finally { remove.disabled = false; }
  }
});
