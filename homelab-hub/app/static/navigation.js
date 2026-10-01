/* Restore deep links and browser history through the existing view lifecycle. */
function restoreHubRoute() {
  if (location.hash.startsWith('#metrics/')) { openMetricPage(location.hash.split('/')[1]); return; }
  const view = location.pathname.replace(/^\//, '') || 'home';
  if (view === 'history') { openMetricPage('cpu'); return; }
  const button = [...document.querySelectorAll('.nav-item[data-view]')].find(node => node.dataset.view === view);
  if (!button) return;
  window.hubRestoringRoute = true;
  try { button.click(); } finally { window.hubRestoringRoute = false; }
}
window.addEventListener('popstate', restoreHubRoute);
restoreHubRoute();
