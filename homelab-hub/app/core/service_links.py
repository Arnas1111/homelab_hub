"""Configuration for published-port Web UI guesses."""
import ipaddress
import re
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceLinks(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = True
    host: str = Field(default='', max_length=253)

    @field_validator('host')
    @classmethod
    def valid_host(cls, value):
        value = value.strip()
        if not value:
            return ''
        candidate = value[1:-1] if value.startswith('[') and value.endswith(']') else value
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            if not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label) for label in candidate.rstrip('.').split('.')):
                raise ValueError('Enter an IP address or hostname without a scheme, port or path')
            return candidate.lower()


def service_link_settings(preferences):
    return ServiceLinks.model_validate(preferences.read('service_links', {})).model_dump()


def service_link_host(settings, unraid_url, fallback):
    if settings['host']:
        return settings['host']
    try:
        parsed = urlsplit(unraid_url)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
            return parsed.hostname
    except ValueError:
        pass
    return fallback


def service_link_router(preferences, require_auth):
    router = APIRouter(prefix='/api/service-link-settings', dependencies=[Depends(require_auth)])

    @router.get('')
    def read(): return service_link_settings(preferences)

    @router.put('')
    def save(payload: ServiceLinks):
        preferences.write('service_links', payload.model_dump())
        return read()

    return router
