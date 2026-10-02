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
  loadAccessSettings();
  loadAutomationTimeSettings();
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

function renderAccessSetting(config) {
  $('loginRequired').checked = config.login_required;
  $('signOutForm').hidden = !config.login_required;
  $('accessStatus').textContent = config.login_required ? 'Password login is on.' : 'Password login is off.';
}
async function loadAccessSettings() {
  $('accessSave').disabled = true;
  try {
    renderAccessSetting(await api('/api/account/access'));
    $('accessSave').disabled = false;
  } catch (error) { $('accessStatus').textContent = error.message; }
}
$('accessForm').addEventListener('submit', async event => {
  event.preventDefault();
  $('accessSave').disabled = true;
  try {
    const config = await api('/api/account/access', {method:'PUT', body:JSON.stringify({login_required:$('loginRequired').checked})});
    renderAccessSetting(config);
    if (config.login_required) location.href = '/login?next=%2Fsettings';
  } catch (error) { $('accessStatus').textContent = error.message; }
  finally { $('accessSave').disabled = false; }
});
loadAccessSettings();

function showSolarTimes(config) {
  const format = value => value ? new Date(value).toLocaleTimeString([], {timeZone:config.timezone, hour:'2-digit', minute:'2-digit'}) : 'Unavailable';
  $('solarTimeStatus').textContent = `${config.status}${config.solar_enabled ? ` Sunrise ${format(config.sunrise)} · Sunset ${format(config.sunset)} · ${config.timezone}` : ''}`;
}
async function loadAutomationTimeSettings() {
  $('saveAutomationTime').disabled = true;
  try {
    const config = await api('/api/zigbee/automations/time-settings');
    $('automationTimezone').value = config.configured ? config.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone;
    $('solarEnabled').checked = config.solar_enabled;
    $('solarLocation').value = config.location || '';
    $('solarLatitude').value = config.latitude ?? '';
    $('solarLongitude').value = config.longitude ?? '';
    $('solarLatitude').required = config.solar_enabled;
    $('solarLongitude').required = config.solar_enabled;
    showSolarTimes(config);
    $('saveAutomationTime').disabled = false;
  } catch (error) { $('automationTimeSettingsFeedback').textContent = error.message; }
}
$('solarEnabled').addEventListener('change', () => {
  $('solarLatitude').required = $('solarEnabled').checked;
  $('solarLongitude').required = $('solarEnabled').checked;
});
$('automationTimeSettingsForm').addEventListener('submit', async event => {
  event.preventDefault();
  $('saveAutomationTime').disabled = true;
  try {
    const config = await api('/api/zigbee/automations/time-settings', {method:'PUT', body:JSON.stringify({
      timezone:$('automationTimezone').value.trim(), solar_enabled:$('solarEnabled').checked, location:$('solarLocation').value.trim(),
      latitude:$('solarLatitude').value === '' ? null : Number($('solarLatitude').value), longitude:$('solarLongitude').value === '' ? null : Number($('solarLongitude').value)
    })});
    showSolarTimes(config);
    $('automationTimeSettingsFeedback').textContent = 'Time and location settings saved.';
  } catch (error) { $('automationTimeSettingsFeedback').textContent = error.message; }
  finally { $('saveAutomationTime').disabled = false; }
});
$('refreshSolarTimes').addEventListener('click', async () => {
  try { showSolarTimes(await api('/api/zigbee/automations/time-settings/refresh', {method:'POST'})); }
  catch (error) { $('automationTimeSettingsFeedback').textContent = error.message; }
});
$('solarUseLocation').addEventListener('click', () => {
  if (!navigator.geolocation) { $('automationTimeSettingsFeedback').textContent = 'Location is unavailable here. Enter latitude and longitude manually.'; return; }
  $('automationTimeSettingsFeedback').textContent = 'Requesting your location…';
  navigator.geolocation.getCurrentPosition(position => {
    $('solarLatitude').value = position.coords.latitude.toFixed(5);
    $('solarLongitude').value = position.coords.longitude.toFixed(5);
    $('automationTimezone').value = Intl.DateTimeFormat().resolvedOptions().timeZone;
    $('automationTimeSettingsFeedback').textContent = 'Location filled. Save to apply it.';
  }, () => { $('automationTimeSettingsFeedback').textContent = 'Browser location is unavailable or not permitted. Enter latitude and longitude manually.'; }, {timeout:10000, maximumAge:60000});
});
