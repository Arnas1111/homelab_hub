/* Restore deep links and browser history through the existing view lifecycle. */
function restoreHubRoute() {
  window.hubRestoringRoute = true;
  try {
    if (location.hash.startsWith('#metrics/')) { openMetricPage(location.hash.split('/')[1]); return; }
    let view = location.pathname.replace(/^\//, '') || 'home';
    if (view === 'connectors') { view = 'integrations'; history.replaceState(null, '', '/integrations'); }
    if (view === 'history') { openMetricPage('cpu'); return; }
    const button = [...document.querySelectorAll('.nav-item[data-view]')].find(node => node.dataset.view === view);
    if (!button) return;
    // Cancel anchor navigation even if an older cached view handler does not.
    button.addEventListener('click', event => event.preventDefault(), { once: true, capture: true });
    button.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  }
  finally { window.hubRestoringRoute = false; }
}
window.addEventListener('popstate', restoreHubRoute);
restoreHubRoute();
