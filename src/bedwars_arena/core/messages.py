"""Versioned internal messages. These are not external player requests."""
from dataclasses import dataclass
import json
from typing import Any

from .scheduler import _json
from .time import identifier, integer

PHASES = (0, 10, 20, 25, 30, 32, 35, 40, 45, 50, 55, 60, 70, 80, 90)


def phase(value: object) -> int:
    if type(value) is not int or value not in PHASES:
        raise ValueError('Unknown L1 phase')
    return value


def _cause(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'category', 'id'}:
        raise ValueError('Invalid causal reference')
    if value['category'] not in ('task', 'intent', 'fact'):
        raise ValueError('Invalid causal category')
    identifier(value['id'], 'cause id')
    return dict(value)


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    """A scheduled attempt, not proof that its gameplay operation succeeded."""
    task_id: str
    kind: str
    created_at: int
    execute_at: int
    phase: int
    source_order: int
    payload_json: str
    cause_json: str = 'null'

    def __post_init__(self) -> None:
        identifier(self.task_id, 'task id')
        identifier(self.kind, 'task kind')
        integer(self.created_at, 'created_at')
        integer(self.execute_at, 'execute_at', 1)
        if self.execute_at < self.created_at:
            raise ValueError('Task cannot precede creation')
        phase(self.phase)
        integer(self.source_order, 'source_order')
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError('Task payload must be an object')
        object.__setattr__(self, 'payload_json', _json(payload))
        object.__setattr__(self, 'cause_json', _json_cause(_cause(json.loads(self.cause_json))))

    @classmethod
    def create(cls, *, task_id: str, kind: str, created_at: int, execute_at: int,
               phase: int, source_order: int, payload: dict, caused_by: dict | None = None):
        return cls(task_id, kind, created_at, execute_at, phase, source_order,
                   _json(payload), _json_cause(_cause(caused_by)))

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def caused_by(self) -> dict | None:
        return json.loads(self.cause_json)

    @property
    def key(self) -> tuple:
        return self.execute_at, self.phase, self.source_order, self.task_id

    def to_dict(self) -> dict:
        return {'version': 1, 'category': 'task', 'id': self.task_id, 'kind': self.kind,
                'created_at': self.created_at, 'execute_at': self.execute_at, 'phase': self.phase,
                'source_order': self.source_order, 'payload': self.payload, 'caused_by': self.caused_by}

    @classmethod
    def from_dict(cls, value: dict):
        if not isinstance(value, dict) or set(value) != {'version','category','id','kind','created_at',
                'execute_at','phase','source_order','payload','caused_by'}:
            raise ValueError('Invalid ScheduledTask fields')
        if type(value['version']) is not int or value['version'] != 1 or value['category'] != 'task':
            raise ValueError('Unsupported ScheduledTask version/category')
        return cls.create(task_id=value['id'], kind=value['kind'], created_at=value['created_at'],
                          execute_at=value['execute_at'], phase=value['phase'],
                          source_order=value['source_order'], payload=value['payload'],
                          caused_by=value['caused_by'])


def _json_cause(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True, slots=True)
class Intent:
    """A core-produced candidate to be checked in a later phase of this tick."""
    intent_id: str
    kind: str
    created_at: int
    target_phase: int
    payload_json: str
    cause_json: str = 'null'

    def __post_init__(self):
        identifier(self.intent_id, 'intent id')
        identifier(self.kind, 'intent kind')
        integer(self.created_at, 'created_at', 1)
        phase(self.target_phase)
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError('Intent payload must be an object')
        object.__setattr__(self, 'payload_json', _json(value))
        object.__setattr__(self, 'cause_json', _json_cause(_cause(json.loads(self.cause_json))))

    @classmethod
    def create(cls, *, intent_id: str, kind: str, created_at: int, target_phase: int,
               payload: dict, caused_by: dict | None = None):
        return cls(intent_id, kind, created_at, target_phase, _json(payload), _json_cause(_cause(caused_by)))

    def to_dict(self) -> dict:
        return {'version': 1, 'category': 'intent', 'id': self.intent_id, 'kind': self.kind,
                'created_at': self.created_at, 'target_phase': self.target_phase,
                'payload': json.loads(self.payload_json), 'caused_by': json.loads(self.cause_json)}

    @classmethod
    def from_dict(cls, value: dict):
        if not isinstance(value, dict) or set(value) != {'version','category','id','kind','created_at',
                'target_phase','payload','caused_by'} or type(value['version']) is not int or value['version'] != 1 or value['category'] != 'intent':
            raise ValueError('Invalid Intent v1')
        return cls.create(intent_id=value['id'], kind=value['kind'], created_at=value['created_at'],
                          target_phase=value['target_phase'], payload=value['payload'], caused_by=value['caused_by'])


@dataclass(frozen=True, slots=True)
class FactEvent:
    """An immutable fact emitted only after its whole plan has committed."""
    fact_id: str
    commit_id: str
    kind: str
    happened_at: int
    phase: int
    payload_json: str
    cause_json: str = 'null'

    def __post_init__(self):
        identifier(self.fact_id, 'fact id')
        identifier(self.commit_id, 'commit id')
        identifier(self.kind, 'fact kind')
        integer(self.happened_at, 'happened_at')
        phase(self.phase)
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError('Fact payload must be an object')
        object.__setattr__(self, 'payload_json', _json(value))
        object.__setattr__(self, 'cause_json', _json_cause(_cause(json.loads(self.cause_json))))

    @classmethod
    def create(cls, *, fact_id: str, commit_id: str, kind: str, happened_at: int,
               phase: int, payload: dict, caused_by: dict | None = None):
        return cls(fact_id, commit_id, kind, happened_at, phase, _json(payload), _json_cause(_cause(caused_by)))

    def to_dict(self) -> dict:
        return {'version': 1, 'category': 'fact', 'id': self.fact_id, 'commit_id': self.commit_id,
                'kind': self.kind, 'happened_at': self.happened_at, 'phase': self.phase,
                'payload': json.loads(self.payload_json), 'caused_by': json.loads(self.cause_json)}


def fact_from_dict(value: dict) -> FactEvent:
    if not isinstance(value, dict) or set(value) != {'version','category','id','commit_id','kind',
            'happened_at','phase','payload','caused_by'} or type(value['version']) is not int or value['version'] != 1 or value['category'] != 'fact':
        raise ValueError('Invalid FactEvent v1')
    return FactEvent.create(fact_id=value['id'], commit_id=value['commit_id'], kind=value['kind'],
                            happened_at=value['happened_at'], phase=value['phase'],
                            payload=value['payload'], caused_by=value['caused_by'])
