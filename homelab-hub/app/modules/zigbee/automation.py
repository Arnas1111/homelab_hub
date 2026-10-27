"""Persisted rules and switch-off deadlines, driven by fresh MQTT reports."""
import queue
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.core.objects import ActionRequest
from app.modules.zigbee.time_conditions import AutomationTime, TimeCondition, TimeSettings
from app.modules.zigbee.graph_automation import GraphRule, compare, paths, validate_graph, window_allows


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    source: str = Field(min_length=1, max_length=160)
    property: str = Field(min_length=1, max_length=100)
    equals: bool | str | float | int
    target: str = Field(min_length=1, max_length=160)
    seconds: int = Field(ge=1, le=86400)
    while_occupied: bool = False
    time_condition: TimeCondition | None = None


class Automations:
    def __init__(self, preferences, module, clock=time.time):
        self.preferences, self.module, self.clock = preferences, module, clock
        self.lock = threading.RLock()
        self.events = queue.Queue(maxsize=1000)
        self.stop_event = threading.Event()
        self.thread = None
        self.rules, self.pending, self.status = {}, {}, {}
        self.graphs, self.graph_jobs, self.graph_status, self.graph_fired = {}, {}, {}, {}
        self.holds = {}
        self.time = AutomationTime(preferences)

    def start(self):
        with self.lock:
            saved = self.preferences.read('zigbee_automations', {})
            self.rules = saved.get('rules', {})
            self.pending = saved.get('pending', {})
            self.holds = saved.get('holds', {})
            self.graphs = saved.get('graphs', {})
            self.graph_jobs = saved.get('graph_jobs', {})
            self.graph_fired = saved.get('graph_fired', {})
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='zigbee-automations')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _save(self):
        self.preferences.write('zigbee_automations', {'rules': self.rules, 'pending': self.pending, 'holds': self.holds,
                                                       'graphs': self.graphs, 'graph_jobs': self.graph_jobs,
                                                       'graph_fired': self.graph_fired})

    def notify(self, object_id, values):
        # MQTT must never wait on storage or an actuator publish.
        try:
            self.events.put_nowait((self.clock(), object_id, values))
        except queue.Full:
            pass

    def _run(self):
        while not self.stop_event.is_set():
            try:
                stamp, source, values = self.events.get(timeout=.25)
                if self.clock() - stamp < 5:
                    self.process(source, values)
            except queue.Empty:
                pass
            except Exception:
                # A bad event/integration must not terminate timer processing.
                pass
            try:
                self.tick()
            except Exception:
                pass

    def snapshot(self):
        with self.lock:
            return {'graphs': [dict(id=key, **graph, status=self.graph_status.get(key, 'Ready' if graph['enabled'] else 'Disabled'))
                               for key, graph in self.graphs.items()],
                    'graph_pending_count': len(self.graph_jobs),
                    'rules': [dict(id=key, **rule, status=self.status.get(key, 'Occupied; light held on' if key in self.holds else 'Ready' if rule['enabled'] else 'Disabled'),
                                  off_at=None if self._held(rule['target']) else self.pending.get(rule['target'], {}).get('due'))
                              for key, rule in self.rules.items()],
                    'pending_count': sum(not self._held(target) for target in self.pending), 'connection': self.module.describe()['status']}

    def save_rule(self, rule, rule_id=None):
        with self.lock:
            if rule_id is not None and rule_id not in self.rules:
                raise HTTPException(404, 'Rule not found')
            if rule_id is None and len(self.rules) >= 100:
                raise HTTPException(422, 'Maximum 100 rules')
            objects = {obj.id: obj for obj in self.module.objects()}
            source, target = objects.get(rule.source), objects.get(rule.target)
            cap = source.capabilities.get(rule.property) if source else None
            if not cap or source.type != 'sensor' or cap.type not in ('boolean', 'enum', 'number'):
                raise HTTPException(422, 'Choose a discovered boolean, numeric or button property')
            value = rule.equals
            valid = ((cap.type == 'boolean' and type(value) is bool) or
                     (cap.type == 'enum' and isinstance(value, str) and value in cap.options) or
                     (cap.type == 'number' and type(value) in (int, float) and float('-inf') < value < float('inf')))
            if not valid or not target or 'set_power' not in target.actions:
                raise HTTPException(422, 'Invalid trigger value or target does not support power')
            if rule.while_occupied and (rule.property != 'occupancy' or cap.type != 'boolean' or value is not True):
                raise HTTPException(422, 'Occupancy mode requires occupancy = true')
            if rule.source == rule.target:
                raise HTTPException(422, 'Trigger and target must be different devices')
            if rule.time_condition:
                if self.preferences.read('automation_time') is None:
                    raise HTTPException(422, 'Save your automation timezone in Settings first')
                if rule.time_condition.boundary != 'clock' and not self.time.settings().solar_enabled:
                    raise HTTPException(422, 'Enable solar times and set your location in Settings first')
            rule_id = rule_id or uuid.uuid4().hex
            if rule_id in self.holds:
                old = self.rules[rule_id]
                if not rule.enabled or not rule.while_occupied or rule.source != old['source'] or rule.target != old['target']:
                    self._release(rule_id)
            self.rules[rule_id] = rule.model_dump()
            self.status.pop(rule_id, None)
            self._save()
            return {'id': rule_id}

    def delete(self, rule_id):
        with self.lock:
            if rule_id not in self.rules:
                raise HTTPException(404, 'Rule not found')
            self._release(rule_id)
            del self.rules[rule_id]
            self.status.pop(rule_id, None)
            # Already scheduled OFF remains even when its rule is deleted/disabled.
            self._save()

    def _held(self, target):
        return any(key in self.holds and rule['target'] == target and rule['enabled'] and rule.get('while_occupied')
                   for key, rule in self.rules.items())

    def _schedule_off(self, target, seconds):
        due = self.clock() + seconds
        previous = self.pending.get(target, {}).get('due', 0)
        self.pending[target] = {'due': max(previous, due), 'retry': 0}

    def _release(self, key):
        if key in self.holds:
            self.holds.pop(key)
            rule = self.rules[key]
            self._schedule_off(rule['target'], rule['seconds'])

    def process(self, source, values):
        with self.lock:
            self._process_graphs(source, values)
            for key, rule in self.rules.items():
                if not rule['enabled'] or rule['source'] != source or rule['property'] not in values:
                    continue
                value = values[rule['property']]
                if rule.get('while_occupied'):
                    if value is False:
                        if key in self.holds:
                            self._release(key)
                            self.status[key] = 'Unoccupied; switch-off countdown started'
                            self._save()
                        continue
                    if value is not True:
                        continue
                    if not self._time_allows(key, rule):
                        continue
                    self.holds[key] = True
                    self._save()
                    try:
                        self.module.act(rule['target'], ActionRequest(action='set_power', value=True))
                        self.status[key] = 'Occupied; light held on'
                    except Exception:
                        self.status[key] = 'On command failed; check Zigbee connection'
                    continue
                if value != rule['equals'] or isinstance(value, bool) != isinstance(rule['equals'], bool):
                    continue
                if not self._time_allows(key, rule):
                    continue
                target = rule['target']
                self._schedule_off(target, rule['seconds'])
                # Persist cleanup before sending ON, including ambiguous publish failures.
                self._save()
                try:
                    self.module.act(target, ActionRequest(action='set_power', value=True))
                    self.status[key] = 'Light on; countdown restarted'
                except Exception:
                    self.status[key] = 'On command failed; check Zigbee connection'

    def _time_allows(self, key, rule):
        try:
            allowed = self.time.allows(rule.get('time_condition'), self.clock())
        except ValueError:
            self.status[key] = 'Time condition unavailable; check timezone and solar settings'
            return False
        if not allowed:
            self.status[key] = 'Skipped; time condition is false'
        return allowed

    def tick(self):
        with self.lock:
            self._tick_clock_triggers()
            self._tick_graphs()
            now = self.clock()
            for target, job in list(self.pending.items()):
                if self._held(target):
                    continue
                if now < max(job['due'], job.get('retry', 0)):
                    continue
                try:
                    self.module.act(target, ActionRequest(action='set_power', value=False))
                except Exception:
                    job['retry'] = now + 5
                    for key, rule in self.rules.items():
                        if rule['target'] == target:
                            self.status[key] = 'Off pending; retrying when device is reachable'
                else:
                    del self.pending[target]
                    for key, rule in self.rules.items():
                        if rule['target'] == target:
                            self.status[key] = 'Off command sent'
                self._save()

    def save_graph(self, graph: GraphRule, graph_id=None):
        with self.lock:
            if graph_id is not None and graph_id not in self.graphs:
                raise HTTPException(404, 'Automation not found')
            if graph_id is None and len(self.graphs) + len(self.rules) >= 100:
                raise HTTPException(422, 'Maximum 100 automations')
            validate_graph(graph, self.module, self.time)
            graph_id = graph_id or uuid.uuid4().hex
            self.graphs[graph_id] = graph.model_dump()
            self.graph_fired = {key: day for key, day in self.graph_fired.items() if not key.startswith(graph_id + ':')}
            self.graph_status.pop(graph_id, None)
            self._save()
            return {'id': graph_id}

    def delete_graph(self, graph_id):
        with self.lock:
            if graph_id not in self.graphs:
                raise HTTPException(404, 'Automation not found')
            del self.graphs[graph_id]
            self.graph_fired = {key: day for key, day in self.graph_fired.items() if not key.startswith(graph_id + ':')}
            self.graph_status.pop(graph_id, None)
            # Scheduled branches hold a copy of their graph and still finish.
            self._save()

    def _process_graphs(self, source, values):
        for graph_id, graph in self.graphs.items():
            if not graph['enabled']:
                continue
            nodes, incoming, outgoing = paths(graph)
            for key, node in nodes.items():
                if node['kind'] != 'trigger':
                    continue
                item = nodes[incoming[key][0]]['item']
                if item != source or node['property'] not in values:
                    continue
                if not compare(values[node['property']], node['value'], node['operator']):
                    continue
                try:
                    self._walk_graph(graph_id, graph, outgoing[key], item)
                    self.graph_status[graph_id] = 'Triggered'
                except Exception:
                    self.graph_status[graph_id] = 'Action failed; check Zigbee connection'

    def _tick_clock_triggers(self):
        now = self.clock()
        for graph_id, graph in self.graphs.items():
            if not graph['enabled']:
                continue
            nodes, _, outgoing = paths(graph)
            for key, node in nodes.items():
                if node['kind'] != 'clock_trigger':
                    continue
                try:
                    boundary = self.time.boundary(node['time_condition'], now)
                    elapsed = now - boundary.timestamp()
                    day = boundary.date().isoformat()
                    fired_key = graph_id + ':' + key
                    if not 0 <= elapsed < 60 or self.graph_fired.get(fired_key) == day:
                        continue
                    # Persist before acting so restarts in this minute cannot repeat it.
                    self.graph_fired[fired_key] = day
                    self._save()
                    self._walk_graph(graph_id, graph, outgoing[key], '')
                    self.graph_status[graph_id] = 'Triggered'
                except Exception:
                    self.graph_status[graph_id] = 'Clock trigger failed; check time settings or Zigbee connection'

    def _walk_graph(self, graph_id, graph, next_ids, context):
        nodes, _, outgoing = paths(graph)
        for key in next_ids:
            node = nodes[key]
            kind = node['kind']
            if kind == 'item':
                self._walk_graph(graph_id, graph, outgoing[key], node['item'])
            elif kind == 'condition':
                obj = next((obj for obj in self.module.objects() if obj.id == context), None)
                if obj and obj.available and compare(obj.state.get(node['property']), node['value'], node['operator']):
                    self._walk_graph(graph_id, graph, outgoing[key], context)
            elif kind == 'time':
                if self.time.allows(node['time_condition'], self.clock()):
                    self._walk_graph(graph_id, graph, outgoing[key], context)
            elif kind == 'window':
                if window_allows(node['start'], node['end'], self.clock(), self.time.settings().timezone):
                    self._walk_graph(graph_id, graph, outgoing[key], context)
            elif kind == 'action':
                self.module.act(node.get('target_item') or context, ActionRequest(action=node['action'], value=node['value']))
                self._walk_graph(graph_id, graph, outgoing[key], context)
            elif kind == 'delay':
                job_key = graph_id + ':' + key + ':' + context
                self.graph_jobs[job_key] = {'graph': graph, 'graph_id': graph_id, 'next': outgoing[key],
                                            'context': context, 'due': self.clock() + node['seconds'], 'retry': 0}
                self._save()

    def _tick_graphs(self):
        now = self.clock()
        for key, job in list(self.graph_jobs.items()):
            if now < max(job['due'], job['retry']):
                continue
            try:
                self._walk_graph(job['graph_id'], job['graph'], job['next'], job['context'])
            except Exception:
                job['retry'] = now + 5
                self.graph_status[job['graph_id']] = 'Delayed action failed; retrying'
            else:
                del self.graph_jobs[key]
                self.graph_status[job['graph_id']] = 'Delayed actions completed'
            self._save()


def automation_router(engine, require_auth):
    router = APIRouter(prefix='/api/zigbee/automations', dependencies=[Depends(require_auth)])

    @router.get('')
    def read():
        return engine.snapshot()

    @router.post('/graphs', status_code=201)
    def create_graph(graph: GraphRule):
        return engine.save_graph(graph)

    @router.put('/graphs/{graph_id}')
    def update_graph(graph_id: str, graph: GraphRule):
        return engine.save_graph(graph, graph_id)

    @router.delete('/graphs/{graph_id}')
    def delete_graph(graph_id: str):
        engine.delete_graph(graph_id)
        return {'ok': True}

    @router.get('/time-settings')
    def time_settings():
        return engine.time.snapshot(engine.clock())

    @router.put('/time-settings')
    def save_time_settings(settings: TimeSettings):
        engine.time.save(settings)
        return engine.time.snapshot(engine.clock())

    @router.post('/time-settings/refresh')
    def refresh_time_settings():
        from app.modules.zigbee.time_conditions import solar_boundary
        solar_boundary.cache_clear()
        return engine.time.snapshot(engine.clock())

    @router.post('', status_code=201)
    def create(rule: Rule):
        return engine.save_rule(rule)

    @router.put('/{rule_id}')
    def update(rule_id: str, rule: Rule):
        return engine.save_rule(rule, rule_id)

    @router.delete('/{rule_id}')
    def delete(rule_id: str):
        engine.delete(rule_id)
        return {'ok': True}

    return router
