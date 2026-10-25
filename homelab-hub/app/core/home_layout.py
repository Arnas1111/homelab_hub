"""User-configurable Home modules stored with the existing Hub preferences."""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

MODULES = ('welcome', 'status', 'host', 'services', 'attention', 'connections', 'zigbee')
DEFAULT_LAYOUT = [
    {'id': 'welcome', 'width': 2}, {'id': 'status', 'width': 2},
    {'id': 'host', 'width': 2}, {'id': 'services', 'width': 2},
    {'id': 'attention', 'width': 1}, {'id': 'connections', 'width': 1},
]


class HomeModule(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: Literal['welcome', 'status', 'host', 'services', 'attention', 'connections', 'zigbee']
    width: Literal[1, 2] = 1


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
        return {'modules': preferences.read('home_layout', DEFAULT_LAYOUT)}

    @router.put('')
    def save(layout: HomeLayout):
        modules = [module.model_dump() for module in layout.modules]
        preferences.write('home_layout', modules)
        return {'modules': modules}

    return router
