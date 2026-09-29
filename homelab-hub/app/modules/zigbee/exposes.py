"""Map discovery metadata to a small, validated object contract."""
import math
from app.core.objects import Capability

WRITABLE = {'power', 'brightness', 'color_temp', 'color_xy', 'color_hs', 'effect'}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def features(exposes):
    result = {}
    for feature in exposes:
        if not isinstance(feature, dict) or not isinstance(feature.get('property'), str):
            continue
        if type(feature.get('access')) is not int:
            continue
        key = 'power' if feature.get('name') == 'state' else feature['property']
        if feature.get('name') in WRITABLE:
            key = feature['name']
        if key == 'power' and feature.get('type') == 'numeric':
            key = 'power_measurement'
        if feature.get('name') == 'brightness':
            low, high = feature.get('value_min', 0), feature.get('value_max', 254)
            if not number(low) or not number(high) or low >= high:
                continue
        if feature.get('type') in ('numeric', 'binary', 'enum') or key in WRITABLE:
            result[key] = feature
    return result


def capability(key, feature):
    kind = {'numeric':'number', 'binary':'boolean', 'enum':'enum'}.get(feature.get('type'), 'number')
    if key == 'power':
        kind = 'boolean'
    if key in ('color_xy', 'color_hs'):
        kind = key
    low, high = feature.get('value_min'), feature.get('value_max')
    if key == 'brightness':
        low, high = 0, 100
    bounded = key not in ('color_temp',) or (number(low) and number(high) and low < high)
    return Capability(type=kind, label=feature.get('label') or key.replace('_', ' ').title(),
                      writable=key in WRITABLE and bool(feature['access'] & 2) and bounded,
                      minimum=low if number(low) else None, maximum=high if number(high) else None,
                      unit='%' if key == 'brightness' else feature.get('unit'),
                      options=[v for v in feature.get('values', []) if isinstance(v, str)])


def state_value(key, feature, value):
    if key == 'power' or feature.get('type') == 'binary':
        if value == feature.get('value_on', 'ON'):
            return True
        if value == feature.get('value_off', 'OFF'):
            return False
        return None
    if key == 'brightness' and number(value):
        low, high = feature.get('value_min', 0), feature.get('value_max', 254)
        return round(max(0, min(100, (value-low)*100/(high-low))), 1)
    if number(value) or isinstance(value, (str, bool)):
        return value
    if key in ('color_xy', 'color_hs') and isinstance(value, dict):
        keys = ('x','y') if key == 'color_xy' else ('hue','saturation')
        return {k:value[k] for k in keys if number(value.get(k))}
    return None


def command_value(key, feature, value):
    cap = capability(key, feature)
    if not cap.writable:
        raise ValueError('Read-only capability')
    if key == 'power':
        if type(value) is not bool:
            raise ValueError('Expected boolean')
        return feature.get('value_on', 'ON') if value else feature.get('value_off', 'OFF')
    if key == 'effect':
        if not isinstance(value, str) or value not in cap.options:
            raise ValueError('Unknown effect')
        return value
    if key in ('color_xy', 'color_hs'):
        limits = {'x':1, 'y':1} if key == 'color_xy' else {'hue':360, 'saturation':100}
        if not isinstance(value, dict) or set(value) != set(limits):
            raise ValueError('Invalid color')
        if any(not number(value[k]) or not 0 <= value[k] <= high for k, high in limits.items()):
            raise ValueError('Invalid color range')
        if key == 'color_xy' and (value['y'] <= 0 or value['x'] + value['y'] > 1):
            raise ValueError('Invalid chromaticity')
        return value
    if not number(value) or cap.minimum is None or cap.maximum is None or not cap.minimum <= value <= cap.maximum:
        raise ValueError('Invalid numeric range')
    if key == 'brightness':
        low, high = feature.get('value_min', 0), feature.get('value_max', 254)
        return round(low + value*(high-low)/100)
    return round(value)
