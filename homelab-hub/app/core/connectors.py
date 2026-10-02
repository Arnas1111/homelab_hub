"""The supported service connectors and their persisted configuration fields."""
from urllib.parse import urlsplit, urlunsplit
from app.modules.docker.discovery import safe_url


def unraid_webui_url(api_url):
    safe = safe_url(api_url)
    if not safe:
        return ''
    url = urlsplit(safe)
    try:
        url.port
    except ValueError:
        return ''
    return urlunsplit((url.scheme, url.netloc, '', '', ''))


CONNECTOR_FIELDS = {
    'unraid': ('unraid_url', 'unraid_api_key'),
    'jellyfin': ('jellyfin_url', 'jellyfin_public_url', 'jellyfin_api_key'),
    'home_assistant': ('home_assistant_url', 'home_assistant_token', 'home_assistant_entities'),
}


def configured_connectors(values):
    return [name for name, fields in CONNECTOR_FIELDS.items()
            if any(values.get(field) for field in fields)]
