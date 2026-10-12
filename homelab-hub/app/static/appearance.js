/* Saved Homelab theme; previews stay independent of polling and other forms. */
let appearanceSaved = document.body.dataset.theme === 'paper' ? 'paper' : 'dark';
let appearanceDirty = false, appearanceBusy = false;
function applyHubTheme(theme) { document.body.dataset.theme = theme === 'paper' ? 'paper' : 'dark'; }
applyHubTheme(appearanceSaved);
$('appearanceTheme').value = appearanceSaved;
async function loadAppearance() {
  try {
    const config = await api('/api/appearance');
    appearanceSaved = config.theme;
    if (!appearanceDirty) { $('appearanceTheme').value = appearanceSaved; applyHubTheme(appearanceSaved); }
    $('appearanceSave').disabled = false;
  } catch (error) { $('appearanceStatus').textContent = error.message; }
}
$('appearanceTheme').addEventListener('change', () => {
  appearanceDirty = true; applyHubTheme($('appearanceTheme').value);
  $('appearanceStatus').textContent = 'Previewing theme. Save to keep this change.';
});
$('appearanceCancel').addEventListener('click', () => {
  appearanceDirty = false; $('appearanceTheme').value = appearanceSaved; applyHubTheme(appearanceSaved);
  $('appearanceStatus').textContent = 'Saved theme restored.';
});
$('appearanceForm').addEventListener('submit', async event => {
  event.preventDefault(); if (appearanceBusy) return;
  appearanceBusy = true; $('appearanceSave').disabled = true; $('appearanceTheme').disabled = true; $('appearanceCancel').disabled = true;
  try {
    const config = await api('/api/appearance', {method:'PUT', body:JSON.stringify({theme:$('appearanceTheme').value})});
    appearanceSaved = config.theme; appearanceDirty = false; applyHubTheme(appearanceSaved);
    $('appearanceStatus').textContent = 'Theme saved.';
  } catch (error) { $('appearanceStatus').textContent = error.message; }
  finally { appearanceBusy = false; $('appearanceSave').disabled = false; $('appearanceTheme').disabled = false; $('appearanceCancel').disabled = false; }
});
document.querySelector('[data-view="settings"]').addEventListener('click', loadAppearance);
loadAppearance();
