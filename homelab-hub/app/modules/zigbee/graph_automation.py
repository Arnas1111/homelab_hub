"""Validated, item-based Zigbee automation graphs."""
from typing import Literal
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.zigbee.time_conditions import TimeCondition


class Node(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    kind: Literal['item', 'trigger', 'condition', 'time', 'window', 'action', 'delay']
    item: str = Field(default='', max_length=160)
    property: str = Field(default='', max_length=100)
    operator: Literal['eq', 'ne', 'gt', 'gte', 'lt', 'lte'] = 'eq'
    value: bool | str | int | float | None = None
    action: str = Field(default='', max_length=80)
    seconds: int = Field(default=0, ge=0, le=86400)
    time_condition: TimeCondition | None = None
    start: str = Field(default='18:00', pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    end: str = Field(default='00:00', pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    x: int = Field(default=0, ge=0, le=2400)
    y: int = Field(default=0, ge=0, le=1600)

    @model_validator(mode='after')
    def bounded_value(self):
        if isinstance(self.value, str) and len(self.value) > 120:
            raise ValueError('Card value is too long')
        if type(self.value) is float and not math.isfinite(self.value):
            raise ValueError('Card value must be finite')
        return self


class Edge(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source: str
    target: str


class GraphRule(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    nodes: list[Node] = Field(min_length=4, max_length=50)
    edges: list[Edge] = Field(min_length=3, max_length=80)


def compare(actual, expected, operator):
    if actual is None or expected is None:
        return False
    if operator in ('eq', 'ne'):
        numeric = type(actual) in (int, float) and type(expected) in (int, float)
        equal = actual == expected and (numeric or type(actual) is type(expected))
        return equal if operator == 'eq' else not equal
    if type(actual) not in (int, float) or type(expected) not in (int, float):
        return False
    return {'gt': actual > expected, 'gte': actual >= expected,
            'lt': actual < expected, 'lte': actual <= expected}[operator]


def validate_graph(graph: GraphRule, module, automation_time):
    nodes = {node.id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise HTTPException(422, 'Node IDs must be unique')
    incoming = {key: [] for key in nodes}
    outgoing = {key: [] for key in nodes}
    for edge in graph.edges:
        if edge.source not in nodes or edge.target not in nodes or edge.source == edge.target:
            raise HTTPException(422, 'Connection refers to a missing or identical card')
        if edge.target in outgoing[edge.source]:
            raise HTTPException(422, 'Duplicate connection')
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)
    roots = [key for key, node in nodes.items() if node.kind == 'item' and not incoming[key]]
    triggers = [key for key, node in nodes.items() if node.kind == 'trigger']
    if not roots or not triggers or not any(n.kind == 'action' for n in nodes.values()):
        raise HTTPException(422, 'Add an item, a trigger, and an action')
    if any(len(incoming[key]) != 1 or nodes[incoming[key][0]].kind != 'item' for key in triggers):
        raise HTTPException(422, 'Connect each trigger directly after an item')
    visited, active = set(), set()
    def visit(key):
        if key in active:
            raise HTTPException(422, 'Connections must not contain a loop')
        if key in visited:
            return
        active.add(key)
        for target in outgoing[key]:
            visit(target)
        active.remove(key)
        visited.add(key)
    for root in roots:
        visit(root)
    if len(visited) != len(nodes):
        raise HTTPException(422, 'Every card must connect to an item-trigger path')
    objects = {obj.id: obj for obj in module.objects()}
    for node in nodes.values():
        if node.kind == 'item':
            if node.item not in objects:
                raise HTTPException(422, 'Choose a discovered item for each item card')
        elif node.kind in ('trigger', 'condition'):
            if not node.property or node.value is None or node.kind == 'trigger' and node.operator != 'eq':
                raise HTTPException(422, 'Set a property and value on each state card')
        elif node.kind == 'action':
            if not node.action.startswith('set_') or node.value is None:
                raise HTTPException(422, 'Choose an action and value')
        elif node.kind == 'delay':
            if not 1 <= node.seconds <= 86400:
                raise HTTPException(422, 'Delay must be between 1 second and 24 hours')
        elif node.kind == 'time':
            if node.time_condition is None:
                raise HTTPException(422, 'Choose a time boundary')
            if automation_time.preferences.read('automation_time') is None:
                raise HTTPException(422, 'Set the automation timezone in Settings first')
            if node.time_condition.boundary != 'clock' and not automation_time.settings().solar_enabled:
                raise HTTPException(422, 'Set timezone and solar location in Settings first')
        elif node.kind == 'window':
            if automation_time.preferences.read('automation_time') is None:
                raise HTTPException(422, 'Set the automation timezone in Settings first')
            if node.start == node.end:
                raise HTTPException(422, 'Time window needs different start and end times')
    # Each path carries an item context; item cards may change it before a condition/action.
    def check_context(key, item_id, saw_trigger, trigger_source=''):
        node = nodes[key]
        if node.kind == 'item':
            item_id = node.item
        elif node.kind == 'trigger':
            if saw_trigger or item_id not in objects:
                raise HTTPException(422, 'A trigger must follow a source item')
            cap = objects[item_id].capabilities.get(node.property)
            if not cap or cap.type not in ('boolean', 'enum', 'number'):
                raise HTTPException(422, 'Source item does not report this property')
            if not valid_value(cap, node.value):
                raise HTTPException(422, 'Trigger value does not match item property')
            saw_trigger = True
            trigger_source = item_id
        elif not saw_trigger:
            raise HTTPException(422, 'Place a trigger before conditions and actions')
        elif node.kind in ('condition', 'action'):
            obj = objects.get(item_id)
            if not obj:
                raise HTTPException(422, 'Place an item before state checks and actions')
            if node.kind == 'condition':
                cap = obj.capabilities.get(node.property)
                if not cap or cap.type not in ('boolean', 'enum', 'number'):
                    raise HTTPException(422, 'Item does not report this property')
                if not valid_value(cap, node.value):
                    raise HTTPException(422, 'Condition value does not match item property')
            else:
                cap = obj.capabilities.get(node.action.removeprefix('set_'))
                if node.action not in obj.actions or not cap or not valid_value(cap, node.value):
                    raise HTTPException(422, 'Item does not support this action or value')
                if item_id == trigger_source:
                    raise HTTPException(422, 'An action cannot target its own trigger item')
        for target in outgoing[key]:
            check_context(target, item_id, saw_trigger, trigger_source)
    for root in roots:
        check_context(root, '', False)
    if not any(nodes[key].kind == 'action' for key in visited):
        raise HTTPException(422, 'Add an action')


def valid_value(cap, value):
    if cap.type == 'boolean':
        return type(value) is bool
    if cap.type == 'enum':
        return type(value) is str and value in cap.options
    if cap.type == 'number':
        return (type(value) in (int, float) and float('-inf') < value < float('inf') and
                (cap.minimum is None or value >= cap.minimum) and
                (cap.maximum is None or value <= cap.maximum))
    return False


def window_allows(start, end, stamp, timezone):
    local = datetime.fromtimestamp(stamp, ZoneInfo(timezone)).strftime('%H:%M')
    return start <= local < end if start < end else local >= start or local < end


def paths(graph):
    nodes = {node['id']: node for node in graph['nodes']}
    outgoing = {key: [] for key in nodes}
    incoming = {key: [] for key in nodes}
    for edge in graph['edges']:
        outgoing[edge['source']].append(edge['target'])
        incoming[edge['target']].append(edge['source'])
    return nodes, incoming, outgoing
