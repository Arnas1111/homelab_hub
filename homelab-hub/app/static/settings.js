const mqttMessages = {
  disabled: 'Zigbee is disabled.', connecting: 'Connecting to MQTT…', online: 'Connected. Zigbee2MQTT is online.',
  bridge_offline: 'Broker connected. Waiting for Zigbee2MQTT to report online.',
  authentication_failed: 'Broker rejected authentication. Check username and password.',
  connection_failed: 'Cannot connect to broker. Check address, port, TLS and network access.',
  disconnected: 'MQTT disconnected. Reconnecting automatically…',
  subscription_failed: 'Broker rejected the subscription. Check account permissions.',
  configuration_error: 'Invalid connection configuration. Check the settings below.'
};
let mqttSaving = false;
let mqttReady = false;
function showMqttStatus(status) {
  $('mqttStatus').textContent = mqttMessages[status?.status] || 'Connection status unavailable.';
}
async function loadHubSettings() {
  try {
    const config = await api('/api/zigbee/settings');
    $('mqttEnabled').checked = config.enabled;
    $('mqttHost').value = config.host;
    $('mqttPort').value = config.port;
    $('mqttUser').value = config.username;
    $('mqttTls').checked = config.tls;
    $('mqttTopic').value = config.base_topic;
    $('mqttPassword').value = '';
    $('mqttClear').checked = false;
    $('mqttSecretStatus').textContent = config.password_set ? 'A password is saved. Leave blank to keep it.' : 'No broker password saved.';
    showMqttStatus(config.status);
    mqttReady = true;
  } catch (error) { $('mqttStatus').textContent = error.message; }
}
document.querySelector('[data-view="settings"]').addEventListener('click', loadHubSettings);
$('mqttForm').addEventListener('submit', async event => {
  event.preventDefault();
  if (!mqttReady || mqttSaving) return;
  mqttSaving = true;
  try {
    const config = await api('/api/zigbee/settings', {method:'PUT', body:JSON.stringify({
      enabled:$('mqttEnabled').checked, host:$('mqttHost').value.trim(), port:Number($('mqttPort').value),
      username:$('mqttUser').value, password:$('mqttPassword').value, clear_password:$('mqttClear').checked,
      tls:$('mqttTls').checked, base_topic:$('mqttTopic').value.trim()
    })});
    $('mqttPassword').value = '';
    $('mqttClear').checked = false;
    $('mqttSecretStatus').textContent = config.password_set ? 'Password saved.' : 'No broker password saved.';
    showMqttStatus(config.status);
  } catch (error) { $('mqttStatus').textContent = error.message; }
  finally { mqttSaving = false; }
});
$('mqttReconnect').addEventListener('click', async () => {
  try { showMqttStatus((await api('/api/zigbee/reconnect', {method:'POST'})).status); }
  catch (error) { $('mqttStatus').textContent = error.message; }
});
setInterval(async () => {
  if (document.hidden || !$('settingsView').classList.contains('active') || mqttSaving) return;
  try {
    const result = await api('/api/v1/modules');
    showMqttStatus(result.modules.find(module => module.id === 'zigbee'));
  } catch (_) { /* Keep the useful save/load feedback on transient errors. */ }
}, 5000);
async function updateBrand(kind, reset) {
  try {
    const file = $(`${kind}File`).files[0];
    if (!reset && !file) throw new Error('Choose an image first.');
    if (!reset && file.size > 512 * 1024) throw new Error('Image must be at most 512 KB.');
    const result = await api(`/api/branding/${kind}`, {method:reset ? 'DELETE' : 'PUT',
      ...(reset ? {} : {body:file, headers:{'Content-Type':file.type}})});
    const target = kind === 'logo' ? $('hubLogo') : $('hubFavicon');
    target.setAttribute(kind === 'logo' ? 'src' : 'href', `/branding/${kind}?v=${result.revision || Date.now()}`);
    $(`${kind}File`).value = '';
    $('brandingStatus').textContent = reset ? 'Default image restored.' : 'Image saved.';
  } catch (error) { $('brandingStatus').textContent = error.message; }
}
for (const button of document.querySelectorAll('[data-brand-upload]')) button.addEventListener('click', () => updateBrand(button.dataset.brandUpload, false));
for (const button of document.querySelectorAll('[data-brand-reset]')) button.addEventListener('click', () => updateBrand(button.dataset.brandReset, true));
$('passwordForm').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('newPassword').value !== $('confirmPassword').value) { $('passwordStatus').textContent = 'New passwords must match.'; return; }
  try {
    await api('/api/account/password', {method:'PUT', body:JSON.stringify({current_password:$('currentPassword').value, new_password:$('newPassword').value})});
    location.href = '/login';
  } catch (error) { $('passwordStatus').textContent = error.message; }
});
