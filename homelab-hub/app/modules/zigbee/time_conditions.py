"""Local calendar boundaries and offline solar times for sensor conditions."""
from datetime import datetime
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astral import Observer
from astral.sun import sunrise, sunset
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    timezone: str = Field(default='UTC', min_length=1, max_length=100)
    solar_enabled: bool = False
    location: str = Field(default='', max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid_location(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Choose a valid IANA timezone')
        if self.solar_enabled and (self.latitude is None or self.longitude is None):
            raise ValueError('Set latitude and longitude to enable solar times')
        return self


class TimeCondition(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    boundary: Literal['clock', 'sunrise', 'sunset'] = 'clock'
    time: str = Field(default='18:00', pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    after: bool = True
    offset_minutes: int = Field(default=0, ge=-180, le=180)


@lru_cache(maxsize=64)
def solar_boundary(boundary, date, latitude, longitude, timezone):
    calculate = sunrise if boundary == 'sunrise' else sunset
    return calculate(Observer(latitude, longitude), date=date, tzinfo=ZoneInfo(timezone))


class AutomationTime:
    def __init__(self, preferences):
        self.preferences = preferences

    def settings(self):
        return TimeSettings.model_validate(self.preferences.read('automation_time', {}))

    def save(self, settings):
        self.preferences.write('automation_time', settings.model_dump())
        solar_boundary.cache_clear()

    def boundary(self, condition, stamp):
        settings = self.settings()
        now = datetime.fromtimestamp(stamp, ZoneInfo(settings.timezone))
        if condition['boundary'] == 'clock':
            hour, minute = map(int, condition['time'].split(':'))
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if not settings.solar_enabled:
            raise ValueError('Enable solar times and set your location in Settings')
        solar = solar_boundary(condition['boundary'], now.date(), settings.latitude, settings.longitude, settings.timezone)
        return datetime.fromtimestamp(solar.timestamp() + condition.get('offset_minutes', 0) * 60, now.tzinfo)

    def allows(self, condition, stamp):
        if not condition:
            return True
        boundary = self.boundary(condition, stamp)
        if condition['boundary'] == 'clock':
            # A wall-clock condition follows the local clock, including DST jumps.
            now = datetime.fromtimestamp(stamp, boundary.tzinfo)
            is_after = now.replace(tzinfo=None) >= boundary.replace(tzinfo=None)
        else:
            is_after = stamp >= boundary.timestamp()
        return is_after if condition['after'] else not is_after

    def snapshot(self, stamp):
        settings = self.settings()
        now = datetime.fromtimestamp(stamp, ZoneInfo(settings.timezone))
        result = {**settings.model_dump(), 'local_time':now.isoformat(), 'sunrise':None, 'sunset':None,
                  'configured':self.preferences.read('automation_time') is not None, 'status':'Solar times disabled.'}
        if settings.solar_enabled:
            errors = []
            for boundary in ('sunrise', 'sunset'):
                try:
                    result[boundary] = solar_boundary(boundary, now.date(), settings.latitude,
                                                      settings.longitude, settings.timezone).isoformat()
                except ValueError:
                    errors.append(boundary)
            result['status'] = 'Calculated locally for today.' if not errors else 'No ' + '/'.join(errors) + ' for this location today.'
        return result
