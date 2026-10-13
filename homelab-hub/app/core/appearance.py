"""Persistent workspace theme independent of connection and image settings."""
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict


class Appearance(BaseModel):
    model_config = ConfigDict(extra='forbid')
    theme: Literal['dark', 'paper', 'paper-dark'] = 'dark'


def appearance_settings(preferences):
    return Appearance.model_validate(preferences.read('appearance', {})).model_dump()


def appearance_router(preferences, require_auth):
    router = APIRouter(prefix='/api/appearance', dependencies=[Depends(require_auth)])

    @router.get('')
    def read():
        return appearance_settings(preferences)

    @router.put('')
    def save(payload: Appearance):
        preferences.write('appearance', payload.model_dump())
        return read()

    return router
