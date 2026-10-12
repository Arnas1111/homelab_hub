"""Independent Unraid control center. No host shell or arbitrary GraphQL proxy."""
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import Store
from .unraid import ACTIONS, SELECTIONS, ApiError, Unraid

ROOT = Path(__file__).resolve().parents[1]


def safe_url(value):
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        _port = parsed.port
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError()
    except ValueError:
        raise ValueError('Use an http(s) URL without embedded credentials, query or fragment') from None
    return value.rstrip('/')


class Connection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = True
    url: str = Field(default='', max_length=500)
    api_key: str = Field(default='', max_length=2000)
    clear_api_key: bool = False
    controls_enabled: bool = False
    login_required: bool = True
    homelab_url: str = Field(default='', max_length=500)
    title: str = Field(default='Unraid Control', min_length=1, max_length=80)

    @field_validator('url', 'homelab_url')
    @classmethod
    def valid_url(cls, value):
        return safe_url(value.strip())


class Password(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class Tile(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=500)
    icon: Literal['server', 'automation', 'network', 'media', 'files', 'shield', 'chart', 'backup'] = 'server'
    group: str = Field(default='Services', min_length=1, max_length=80)
    enabled: bool = True

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        # Service routes can include fragments and query strings, but never credentials.
        parsed = urlsplit(value)
        try:
            _port = parsed.port
        except ValueError:
            raise ValueError('Invalid URL port') from None
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Use an http(s) service URL without embedded credentials')
        return value


class Tiles(BaseModel):
    tiles: list[Tile] = Field(max_length=200)

    @field_validator('tiles')
    @classmethod
    def unique_ids(cls, values):
        if len({v.id for v in values}) != len(values):
            raise ValueError('Tile IDs must be unique')
        return values


class Action(BaseModel):
    operation: str = Field(max_length=60)
    target: str = Field(default='', max_length=200)


class Execute(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    confirmation: str = Field(max_length=100)


def create_app(directory=None):
    store = Store(directory or os.getenv('CONTROL_DATA', '/data'))
    api = Unraid(lambda:store.read('connection', Connection().model_dump()))
    app = FastAPI(title='Unraid Control', docs_url=None, redoc_url=None)
    app.state.store, app.state.unraid = store, api
    tickets, ticket_lock = {}, threading.Lock()
    connection_lock = threading.RLock()

    @app.middleware('http')
    async def same_origin(request, next_call):
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'Request origin does not match this control center.'}, status_code=403)
        response = await next_call(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    def auth(request: Request):
        config = store.read('connection', {})
        if not store.read('identity') or (config.get('login_required', True) and not store.authenticated(request.cookies.get('control_session', ''))):
            raise HTTPException(401, 'Sign in to continue.')

    def audit(operation, target, outcome):
        with store.lock:
            records = store.read('audit', [])
            records.insert(0, {'time':time.time(), 'operation':operation, 'target':target, 'outcome':outcome})
            store.write('audit', records[:200])

    @app.get('/api/access')
    def access(request: Request):
        setup = not bool(store.read('identity'))
        required = store.read('connection', {}).get('login_required', True)
        return {'setup':setup, 'authenticated':not setup and (not required or store.authenticated(request.cookies.get('control_session', '')))}

    @app.post('/api/setup')
    def setup(body: Password, response: Response, request: Request):
        with store.lock:
            if store.read('identity'):
                raise HTTPException(409, 'Administrator already configured.')
            store.password(body.password)
        response.set_cookie('control_session', store.session(), httponly=True, samesite='strict', secure=request.url.scheme == 'https', max_age=43200)
        return {'ok':True}

    @app.post('/api/login')
    def login(body: Password, response: Response, request: Request):
        if not store.verify(body.password):
            raise HTTPException(401, 'Incorrect password.')
        response.set_cookie('control_session', store.session(), httponly=True, samesite='strict', secure=request.url.scheme == 'https', max_age=43200)
        return {'ok':True}

    @app.post('/api/logout')
    def logout(request: Request, response: Response):
        store.logout(request.cookies.get('control_session', ''))
        response.delete_cookie('control_session')
        return {'ok':True}

    @app.get('/api/settings', dependencies=[Depends(auth)])
    def settings():
        config = store.read('connection', Connection().model_dump())
        return {k:v for k,v in config.items() if k not in ('api_key', 'clear_api_key')} | {'api_key_configured':bool(config.get('api_key'))}

    @app.put('/api/settings', dependencies=[Depends(auth)])
    def save_settings(body: Connection):
        with connection_lock:
            with store.lock:
                old = store.read('connection', {})
                config = body.model_dump(exclude={'clear_api_key'})
                config['api_key'] = '' if body.clear_api_key else body.api_key or old.get('api_key', '')
                store.write('connection', config)
                if config['login_required'] != old.get('login_required', True):
                    store.sessions.clear()
            api.reset()
            with ticket_lock:
                tickets.clear()
        return settings()

    @app.post('/api/reconnect', dependencies=[Depends(auth)])
    def reconnect():
        with connection_lock:
            api.reset()
            try:
                return {'actions':api.capabilities()}
            except ApiError as error:
                raise HTTPException(503, str(error)) from None

    @app.get('/api/capabilities', dependencies=[Depends(auth)])
    def capabilities():
        try:
            return {'actions':api.capabilities(), 'controls_enabled':store.read('connection', {}).get('controls_enabled', False)}
        except ApiError as error:
            return {'actions':[], 'controls_enabled':False, 'error':str(error)}

    @app.get('/api/sections/{section}', dependencies=[Depends(auth)])
    def section(section: str, fresh: bool = False):
        if section not in SELECTIONS:
            raise HTTPException(404, 'Section not found.')
        return api.read(section, fresh=fresh)

    @app.post('/api/actions/prepare', dependencies=[Depends(auth)])
    def prepare(body: Action):
        if not store.read('connection', {}).get('controls_enabled'):
            raise HTTPException(403, 'Enable server controls in Settings first.')
        try:
            if body.operation not in ACTIONS or body.operation not in api.capabilities():
                raise HTTPException(422, 'Operation unavailable on this API.')
        except ApiError as error:
            raise HTTPException(503, str(error)) from None
        if body.operation.startswith(('docker.', 'vm.', 'notification.')) and not body.target:
            raise HTTPException(422, 'Select an operation target.')
        token = secrets.token_urlsafe(32)
        with ticket_lock:
            now = time.time()
            for key in list(tickets):
                if tickets[key]['expires'] < now:
                    del tickets[key]
            tickets[token] = {'action':body, 'expires':now + 60, 'generation':api.generation}
        return {'token':token, 'confirmation':body.operation, 'expires_in':60,
                'impact':'Stopping the array also stops dependent Docker/VM workloads and may stop this control center.' if body.operation == 'array.stop' else
                         'Parity verification reads all array disks; this operation does not correct parity.' if body.operation == 'parity.start' else
                         'This sends a command to the server. The next reading verifies its resulting state.'}

    @app.post('/api/actions/execute', dependencies=[Depends(auth)])
    def execute(body: Execute):
        with ticket_lock:
            ticket = tickets.pop(body.token, None)
        with connection_lock:
            if not ticket or ticket['expires'] < time.time() or ticket['generation'] != api.generation or body.confirmation != ticket['action'].operation:
                raise HTTPException(409, 'Confirmation expired or invalid. Review the operation again.')
            if not store.read('connection', {}).get('controls_enabled'):
                raise HTTPException(403, 'Server controls are disabled.')
            action = ticket['action']
            try:
                api.act(action.operation, action.target)
            except ApiError as error:
                audit(action.operation, action.target, 'Not confirmed; inspect server state before retrying')
                raise HTTPException(503, str(error)) from None
            audit(action.operation, action.target, 'Command accepted; awaiting state verification')
        return {'ok':True}

    @app.get('/api/tiles', dependencies=[Depends(auth)])
    def tiles():
        return {'tiles':store.read('tiles', [])}

    @app.put('/api/tiles', dependencies=[Depends(auth)])
    def save_tiles(body: Tiles):
        store.write('tiles', [tile.model_dump() for tile in body.tiles])
        return tiles()

    @app.get('/api/audit', dependencies=[Depends(auth)])
    def activity():
        return {'events':store.read('audit', [])}

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/')
    @app.get('/{page}')
    def index(page: str = 'overview'):
        if page not in ('overview', 'storage', 'docker', 'vms', 'shares', 'services', 'network', 'notifications', 'plugins', 'tools', 'settings', 'activity'):
            raise HTTPException(404, 'Page not found.')
        return FileResponse(ROOT / 'static/index.html')

    return app


app = create_app()
