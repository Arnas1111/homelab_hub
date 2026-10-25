"""Explicit dashboard routes; never accept an arbitrary post-login redirect."""
PAGES = ('home', 'services', 'containers', 'container-details', 'metrics', 'integrations', 'zigbee',
         'automations', 'logs', 'settings', 'connectors', 'database', 'history')


def safe_page(path):
    return path if isinstance(path, str) and path in ('/', *('/' + page for page in PAGES)) else '/'
