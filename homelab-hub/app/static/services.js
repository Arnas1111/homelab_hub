/* Service tiles share the existing persisted Web UI links and favorites. */
const serviceTileSuggestions = [
  ['Unraid', 'unraid', null], ['Automations', 'home-assistant', '/automations'],
  ['Zigbee devices', 'mqtt', '/zigbee'], ['Home Assistant', 'home-assistant', null],
  ['Node-RED', 'node-red', null], ['Uptime Kuma', 'uptime-kuma', null],
  ['Grafana', 'grafana', null], ['Backups', 'duplicati', null],
  ['Files', 'filebrowser', null], ['Network controller', 'unifi', null],
];
const serviceTileIcons = ['docker', 'unraid', 'home-assistant', 'mqtt', 'node-red', 'uptime-kuma',
  'grafana', 'netdata', 'duplicati', 'filebrowser', 'unifi', 'adguard-home', 'nginx-proxy-manager',
  'portainer', 'jellyfin', 'plex', 'sonarr', 'radarr', 'immich', 'nextcloud', 'paperless-ngx', 'vaultwarden'];
let serviceTileEditing = null;

function serviceTilePreview() { $('serviceTilePreview').src = iconPath($('serviceTileIcon').value); }
function openServiceTile(key = '') {
  if (!currentData) return;
  const form = $('serviceTileForm'); form.reset();
  const container = key.startsWith('container:') ? currentData.containers.find(c => `container:${c.name}` === key) : null;
  const link = container ? webuiLinkForContainer(container) : storedWebLinks().find(l => `link:${l.link_key}` === key);
  serviceTileEditing = link || null;
  $('serviceTileTitle').textContent = key ? container ? 'Set service Web UI' : 'Edit service tile' : 'Add service tile';
  $('serviceTilePresetLabel').hidden = Boolean(key);
  $('serviceTileName').value = link?.label || container?.display_name || container?.name || '';
  $('serviceTileUrl').value = link?.url || '';
  $('serviceTileContainer').innerHTML = '<option value="">Standalone tile</option>' +
    (currentData.containers || []).map(c => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.display_name || c.name)}</option>`).join('');
  if (link?.container_name && ![...$('serviceTileContainer').options].some(o => o.value === link.container_name))
    $('serviceTileContainer').add(new Option(link.container_name, link.container_name));
  $('serviceTileContainer').value = container?.name || link?.container_name || '';
  $('serviceTileContainer').disabled = Boolean(container);
  const icon = link?.icon || container?.icon || 'docker';
  $('serviceTileIcon').innerHTML = [...new Set([...serviceTileIcons, icon])].map(i => `<option value="${escapeHtml(i)}">${escapeHtml(i)}</option>`).join('');
  $('serviceTileIcon').value = icon; serviceTilePreview();
  $('serviceTileFeedback').textContent = 'Standalone tiles are links; availability is not monitored.';
  $('serviceTileDelete').hidden = !link || link.source !== 'manual';
  $('serviceTileDialog').showModal();
}
$('serviceTilePreset').innerHTML += serviceTileSuggestions.map(([name], index) => `<option value="${index}">${escapeHtml(name)}</option>`).join('');
$('serviceTilePreset').onchange = () => {
  const choice = $('serviceTilePreset').value;
  if (choice === '') return;
  const [name, icon, path] = serviceTileSuggestions[Number(choice)];
  $('serviceTileName').value = name; $('serviceTileIcon').value = icon;
  $('serviceTileUrl').value = path ? new URL(path, location.origin).href : name === 'Unraid' ? currentData?.server?.webui_url || '' : '';
  serviceTilePreview();
};
$('serviceTileIcon').onchange = serviceTilePreview;
$('addServiceTile').onclick = () => openServiceTile();
$('serviceTileClose').onclick = () => $('serviceTileDialog').close();
document.addEventListener('click', event => {
  const button = event.target.closest('[data-service-edit]');
  if (button) openServiceTile(button.dataset.serviceEdit);
});
$('serviceTileForm').onsubmit = async event => {
  event.preventDefault();
  const url = boardLink($('serviceTileUrl').value.trim());
  const name = $('serviceTileName').value.trim();
  if (!url || !name) { $('serviceTileFeedback').textContent = 'Enter a name and an http(s) URL without embedded credentials.'; return; }
  const button = event.target.querySelector('[type="submit"]'); button.disabled = true;
  try {
    const links = mergedWebLinks({includeDisabled:true});
    const link = {...serviceTileEditing, link_key:serviceTileEditing?.link_key || `manual:${Date.now()}:${Math.random().toString(36).slice(2)}`,
      label:name, url, icon:$('serviceTileIcon').value, container_name:$('serviceTileContainer').value,
      enabled:true, source:serviceTileEditing?.source || 'manual'};
    await saveWebuiLinks([...links.filter(l => l.link_key !== link.link_key), link]);
    $('serviceTileDialog').close();
  } catch (error) { $('serviceTileFeedback').textContent = error.message; }
  finally { button.disabled = false; }
};
$('serviceTileDelete').onclick = async () => {
  if (!serviceTileEditing || !confirm('Delete this custom tile or Web UI link?')) return;
  const button = $('serviceTileDelete'); button.disabled = true;
  try { await deleteWebuiLink(serviceTileEditing.link_key); $('serviceTileDialog').close(); }
  catch (error) { $('serviceTileFeedback').textContent = error.message; }
  finally { button.disabled = false; }
};
