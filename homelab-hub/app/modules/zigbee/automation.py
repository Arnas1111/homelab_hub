"""Persisted rules and switch-off deadlines, driven by fresh MQTT reports."""
import queue
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.core.objects import ActionRequest


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    source: str = Field(min_length=1, max_length=160)
    property: str = Field(min_length=1, max_length=100)
    equals: bool | str | float | int
    target: str = Field(min_length=1, max_length=160)
    seconds: int = Field(ge=1, le=86400)


class Automations:
    def __init__(self, preferences, module, clock=time.time):
        self.preferences, self.module, self.clock = preferences, module, clock
        self.lock = threading.RLock()
        self.events = queue.Queue(maxsize=1000)
        self.stop_event = threading.Event()
        self.thread = None
        self.rules, self.pending, self.status = {}, {}, {}

    def start(self):
        with self.lock:
            saved = self.preferences.read('zigbee_automations', {})
            self.rules = saved.get('rules', {})
            self.pending = saved.get('pending', {})
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='zigbee-automations')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _save(self):
        self.preferences.write('zigbee_automations', {'rules': self.rules, 'pending': self.pending})

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
            return {'rules': [dict(id=key, **rule, status=self.status.get(key, 'Ready' if rule['enabled'] else 'Disabled'),
                                  off_at=self.pending.get(rule['target'], {}).get('due'))
                              for key, rule in self.rules.items()],
                    'pending_count': len(self.pending), 'connection': self.module.describe()['status']}

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
            if rule.source == rule.target:
                raise HTTPException(422, 'Trigger and target must be different devices')
            rule_id = rule_id or uuid.uuid4().hex
            self.rules[rule_id] = rule.model_dump()
            self.status.pop(rule_id, None)
            self._save()
            return {'id': rule_id}

    def delete(self, rule_id):
        with self.lock:
            if rule_id not in self.rules:
                raise HTTPException(404, 'Rule not found')
            del self.rules[rule_id]
            self.status.pop(rule_id, None)
            # Already scheduled OFF remains even when its rule is deleted/disabled.
            self._save()

    def process(self, source, values):
        with self.lock:
            for key, rule in self.rules.items():
                if not rule['enabled'] or rule['source'] != source or rule['property'] not in values:
                    continue
                value = values[rule['property']]
                if value != rule['equals'] or isinstance(value, bool) != isinstance(rule['equals'], bool):
                    continue
                target = rule['target']
                due = self.clock() + rule['seconds']
                previous = self.pending.get(target, {}).get('due', 0)
                self.pending[target] = {'due': max(previous, due), 'retry': 0}
                # Persist cleanup before sending ON, including ambiguous publish failures.
                self._save()
                try:
                    self.module.act(target, ActionRequest(action='set_power', value=True))
                    self.status[key] = 'Light on; countdown restarted'
                except Exception:
                    self.status[key] = 'On command failed; check Zigbee connection'

    def tick(self):
        with self.lock:
            now = self.clock()
            for target, job in list(self.pending.items()):
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


def automation_router(engine, require_auth):
    router = APIRouter(prefix='/api/zigbee/automations', dependencies=[Depends(require_auth)])

    @router.get('')
    def read():
        return engine.snapshot()

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
