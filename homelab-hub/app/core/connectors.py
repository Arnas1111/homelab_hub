"""The supported service connectors and their persisted configuration fields."""
CONNECTOR_FIELDS = {
    'unraid': ('unraid_url', 'unraid_api_key'),
    'jellyfin': ('jellyfin_url', 'jellyfin_public_url', 'jellyfin_api_key'),
    'home_assistant': ('home_assistant_url', 'home_assistant_token', 'home_assistant_entities'),
}


def configured_connectors(values):
    return [name for name, fields in CONNECTOR_FIELDS.items()
            if any(values.get(field) for field in fields)]
