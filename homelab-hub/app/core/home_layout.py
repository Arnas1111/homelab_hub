"""User-configurable Home modules stored with the existing Hub preferences."""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODULES = ('welcome', 'status', 'host', 'services', 'attention', 'connections', 'zigbee', 'clock', 'notes')
DEFAULT_LAYOUT = [
    {'id': 'welcome', 'width': 3}, {'id': 'status', 'width': 3},
    {'id': 'host', 'width': 3}, {'id': 'services', 'width': 3},
    {'id': 'attention', 'width': 1}, {'id': 'connections', 'width': 1},
    {'id': 'zigbee', 'width': 1}, {'id': 'clock', 'width': 1},
]


class HomeModule(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: Literal['welcome', 'status', 'host', 'services', 'attention', 'connections', 'zigbee', 'clock', 'notes']
    width: Literal[1, 2, 3] = 1
    content: str | None = Field(default=None, max_length=2000)
    accent: Literal['default', 'blue', 'mint', 'amber', 'rose', 'violet'] | None = None


class HomeLayout(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    modules: list[HomeModule] = Field(max_length=len(MODULES))

    @model_validator(mode='after')
    def unique(self):
        if len({module.id for module in self.modules}) != len(self.modules):
            raise ValueError('Each Home module may appear once')
        return self


def home_layout_router(preferences, require_auth):
    router = APIRouter(prefix='/api/home/layout', dependencies=[Depends(require_auth)])

    @router.get('')
    def read():
        modules = preferences.read('home_layout', DEFAULT_LAYOUT)
        if preferences.read('home_layout_version', 1) < 2:
            modules = [{**module, 'width': 3 if module.get('width') == 2 else module.get('width', 1)} for module in modules]
        return {'modules': modules}

    @router.put('')
    def save(layout: HomeLayout):
        modules = [module.model_dump(exclude_none=True) for module in layout.modules]
        preferences.write('home_layout', modules)
        preferences.write('home_layout_version', 2)
        return {'modules': modules}

    return router
