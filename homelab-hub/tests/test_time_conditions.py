"""Local dates, timezone transitions, solar offsets and unavailable solar events."""
from datetime import datetime
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1]))
from pydantic import ValidationError
from app.modules.zigbee.time_conditions import AutomationTime, TimeCondition, TimeSettings
from app.core.connectors import unraid_webui_url
from test_automations import MemoryPreferences


class TimeConditionTests(unittest.TestCase):
    def setUp(self):
        self.preferences = MemoryPreferences()
        self.time = AutomationTime(self.preferences)
        self.time.save(TimeSettings(timezone='Europe/Berlin', solar_enabled=True,
                                    latitude=52.52, longitude=13.405, location='Example city'))

    def stamp(self, date, fold=0):
        return datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('Europe/Berlin'), fold=fold).timestamp()

    def test_clock_before_after_exact_boundary_and_midnight(self):
        condition = TimeCondition(time='18:00').model_dump()
        self.assertFalse(self.time.allows(condition, self.stamp('2026-10-02T17:59:59')))
        self.assertTrue(self.time.allows(condition, self.stamp('2026-10-02T18:00:00')))
        condition['after'] = False
        self.assertFalse(self.time.allows(condition, self.stamp('2026-10-02T18:00:00')))
        self.assertTrue(self.time.allows(condition, self.stamp('2026-10-03T00:00:00')))
        self.assertTrue(self.time.allows(None, self.stamp('2026-10-02T12:00:00')))

    def test_clock_condition_follows_local_clock_through_dst(self):
        condition = TimeCondition(time='02:30').model_dump()
        self.assertFalse(self.time.allows(condition, self.stamp('2026-03-29T01:59:00')))
        self.assertTrue(self.time.allows(condition, self.stamp('2026-03-29T03:00:00')))
        for fold in (0, 1):
            self.assertTrue(self.time.allows(condition, self.stamp('2026-10-25T02:45:00', fold)))
            self.assertFalse(self.time.allows(condition, self.stamp('2026-10-25T02:15:00', fold)))

    def test_solar_dates_offsets_and_changed_location(self):
        now = self.stamp('2026-10-02T12:00:00')
        condition = TimeCondition(boundary='sunset', offset_minutes=15).model_dump()
        sunset = datetime.fromisoformat(self.time.snapshot(now)['sunset'])
        self.assertEqual(sunset.date().isoformat(), '2026-10-02')
        self.assertGreater(sunset.hour, 17)
        self.assertFalse(self.time.allows(condition, sunset.timestamp() + 899))
        self.assertTrue(self.time.allows(condition, sunset.timestamp() + 900))
        next_day = self.time.snapshot(now + 86400)
        self.assertTrue(next_day['sunset'].startswith('2026-10-03'))
        self.time.save(TimeSettings(timezone='Europe/London', solar_enabled=True, latitude=51.5, longitude=-.1))
        changed = AutomationTime(self.preferences).snapshot(now)
        self.assertNotEqual(changed['sunset'], sunset.isoformat())
        self.assertEqual(changed['timezone'], 'Europe/London')
        self.assertIsNotNone(changed['sunrise'])

    def test_polar_and_disabled_solar_conditions_are_unavailable(self):
        self.time.save(TimeSettings(timezone='Europe/Oslo', solar_enabled=True, latitude=78.22, longitude=15.65))
        now = datetime(2026, 6, 21, 12, tzinfo=ZoneInfo('Europe/Oslo')).timestamp()
        snapshot = self.time.snapshot(now)
        self.assertIsNone(snapshot['sunset'])
        self.assertIn('No ', snapshot['status'])
        for after in (False, True):
            with self.assertRaises(ValueError):
                self.time.allows(TimeCondition(boundary='sunset', after=after).model_dump(), now)
        self.time.save(TimeSettings(timezone='UTC'))
        with self.assertRaises(ValueError):
            self.time.allows(TimeCondition(boundary='sunset').model_dump(), now)

    def test_settings_and_condition_validation(self):
        for data in ({'timezone':'Invalid/Timezone'}, {'latitude':91}, {'longitude':181},
                     {'solar_enabled':True}, {'latitude':float('nan')}):
            with self.assertRaises(ValidationError): TimeSettings(**data)
        for data in ({'time':'24:00'}, {'time':'12:60'}, {'offset_minutes':181}, {'boundary':'unknown'}):
            with self.assertRaises(ValidationError): TimeCondition(**data)

    def test_unraid_link_strips_api_path_and_contains_invalid_configuration(self):
        self.assertEqual(unraid_webui_url('https://unraid.test:443/graphql?query=info'), 'https://unraid.test:443')
        for value in ('', 'javascript:alert(1)', 'http://user:secret@unraid.test', 'http://[broken'):
            self.assertEqual(unraid_webui_url(value), '')


if __name__ == '__main__': unittest.main()
