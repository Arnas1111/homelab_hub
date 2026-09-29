import threading

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator


class ZigbeeSettings(BaseModel):
    enabled: bool = False
    host: str = Field(default='', max_length=253, pattern=r'^[a-zA-Z0-9_.:-]*$')
    port: int = Field(default=1883, ge=1, le=65535)
    username: str = Field(default='', max_length=200)
    password: str = Field(default='', max_length=2000, repr=False)
    clear_password: bool = False
    tls: bool = False
    base_topic: str = Field(default='zigbee2mqtt', min_length=1, max_length=200, pattern=r'^[^#+\s\x00]+$')

    @model_validator(mode='after')
    def configured(self):
        if self.enabled and not self.host:
            raise ValueError('Broker hostname required')
        if self.base_topic.startswith('/') or self.base_topic.endswith('/'):
            raise ValueError('Invalid base topic')
        return self


class ZigbeeConfiguration:
    def __init__(self, preferences, module):
        self.preferences = preferences
        self.module = module
        self.lock = threading.Lock()
        self.defaults = dict(enabled=bool(module.host), host=module.host, port=module.port, username=module.username,
                             password=module.password, tls=module.tls, base_topic=module.base)

    def config(self):
        saved = self.preferences.read('zigbee')
        if saved is not None:
            return ZigbeeSettings.model_validate(saved)
        try:
            return ZigbeeSettings.model_validate(self.defaults)
        except ValueError:
            # Broken environment defaults must not prevent repair in Settings.
            return ZigbeeSettings()

    def public(self):
        config = self.config()
        return {**config.model_dump(exclude={'password', 'clear_password'}), 'password_set': bool(config.password),
                'status': self.module.describe()}

    def apply(self, config):
        self.module.stop()
        with self.module.lock:
            self.module.host = config.host if config.enabled else ''
            self.module.port = config.port
            self.module.username = config.username
            self.module.password = config.password
            self.module.tls = config.tls
            self.module.base = config.base_topic
            self.module.devices.clear()
            self.module.states.clear()
            self.module.availability.clear()
            self.module.updated.clear()
            self.module.status = 'connecting' if config.enabled else 'disabled'
        self.module.start()

    def start(self):
        try:
            self.apply(self.config())
        except Exception:
            self.module.status = 'configuration_error'

    def save(self, payload):
        with self.lock:
            previous = self.config()
            config = payload.model_copy(deep=True)
            config.password = '' if payload.clear_password else payload.password or previous.password
            config.clear_password = False
            self.preferences.write('zigbee', config.model_dump(exclude={'clear_password'}))
            self.apply(config)
            return self.public()


def settings_router(configuration, require_auth):
    router = APIRouter(prefix='/api/zigbee', dependencies=[Depends(require_auth)])

    @router.get('/settings')
    def get():
        return configuration.public()

    @router.put('/settings')
    def save(payload: ZigbeeSettings):
        return configuration.save(payload)

    @router.post('/reconnect')
    def reconnect():
        with configuration.lock:
            configuration.apply(configuration.config())
        return configuration.public()

    return router
