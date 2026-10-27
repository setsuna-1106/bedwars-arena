"""Deterministic event ordering v1, a simulator convention, not Hypixel internals."""

from dataclasses import dataclass
from enum import IntEnum
import heapq
import json
import math

from .time import MAX_SAFE_INTEGER, identifier, integer


class Phase(IntEnum):
    EFFECT_EXPIRATION = 0
    RESPAWN = 10
    CONTROLS = 20
    MOVEMENT = 30
    PURCHASES = 40
    BED_DESTRUCTION = 50
    DAMAGE_AND_DEATH = 60
    TEAM_ELIMINATION = 70
    TRAPS = 80
    OUTCOME = 90


def _json(value: object) -> str:
    def validate(item: object) -> None:
        if item is None or isinstance(item, (str, bool)):
            return
        if type(item) is int and -MAX_SAFE_INTEGER <= item <= MAX_SAFE_INTEGER:
            return
        if type(item) is float and math.isfinite(item):
            return
        if isinstance(item, list):
            for child in item:
                validate(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for child in item.values():
                validate(child)
            return
        raise ValueError("Payload must contain JSON values with safe integers and finite numbers")
    validate(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    tick: int
    phase: Phase
    actor_order: int
    event_id: str
    payload_json: str

    def __post_init__(self) -> None:
        integer(self.tick, "tick")
        integer(self.actor_order, "actor_order")
        identifier(self.event_id, "event_id")
        if not isinstance(self.phase, Phase):
            raise ValueError("Invalid event phase")
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError("Event payload must be an object")
        object.__setattr__(self, "payload_json", _json(value))

    @classmethod
    def create(cls, *, tick: int, phase: Phase, actor_order: int,
               event_id: str, payload: dict) -> "ScheduledEvent":
        return cls(tick, phase, actor_order, event_id, _json(payload))

    @property
    def key(self) -> tuple[int, int, int, str]:
        return self.tick, int(self.phase), self.actor_order, self.event_id

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)

    def to_dict(self) -> dict:
        return {"tick": self.tick, "phase": self.phase.name.lower(),
                "actor_order": self.actor_order, "event_id": self.event_id,
                "payload": self.payload}

    @classmethod
    def from_dict(cls, value: dict) -> "ScheduledEvent":
        if not isinstance(value, dict) or set(value) != {
            "tick", "phase", "actor_order", "event_id", "payload"
        }:
            raise ValueError("Invalid event fields")
        try:
            phase = Phase[value["phase"].upper()]
        except (AttributeError, KeyError) as error:
            raise ValueError("Unknown phase") from error
        if value["phase"] != phase.name.lower():
            raise ValueError("Phase encoding must be canonical lowercase")
        return cls.create(tick=value["tick"], phase=phase, actor_order=value["actor_order"],
                          event_id=value["event_id"], payload=value["payload"])


class EventQueue:
    """Ordered by tick, phase, fixed roster order, then stable event ID.

    IDs are match-unique. The seen ledger survives dispatch and snapshots, so
    transport retry cannot repeat a completed purchase. A different ID denotes
    a different request, even when its semantic payload is identical.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[tuple[int, int, int, str], ScheduledEvent]] = []
        self._seen: dict[str, str] = {}
        self._cursor: tuple[int, int, int, str] | None = None

    def schedule(self, event: ScheduledEvent) -> bool:
        if not isinstance(event, ScheduledEvent):
            raise ValueError("Expected ScheduledEvent")
        fingerprint = _json(event.to_dict())
        if event.event_id in self._seen:
            if self._seen[event.event_id] != fingerprint:
                raise ValueError("An event ID cannot be reused with different content")
            return False
        if self._cursor is not None and event.key <= self._cursor:
            raise ValueError("Cannot insert an event behind the committed cursor")
        self._seen[event.event_id] = fingerprint
        heapq.heappush(self._heap, (event.key, event))
        return True

    def peek(self) -> ScheduledEvent | None:
        return self._heap[0][1] if self._heap else None

    def pop(self) -> ScheduledEvent | None:
        if not self._heap:
            return None
        key, event = heapq.heappop(self._heap)
        self._cursor = key
        return event

    def snapshot(self) -> dict:
        return {"schema_version": 1,
                "cursor": None if self._cursor is None else list(self._cursor),
                "pending": [event.to_dict() for _, event in sorted(self._heap)],
                "seen": dict(sorted(self._seen.items()))}

    @classmethod
    def restore(cls, value: dict) -> "EventQueue":
        if not isinstance(value, dict) or set(value) != {"schema_version", "cursor", "pending", "seen"}:
            raise ValueError("Invalid event queue snapshot")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("Unknown event queue schema version")
        if not isinstance(value["seen"], dict) or not isinstance(value["pending"], list):
            raise ValueError("Invalid queue collections")
        known = {}
        for event_id, fingerprint in value["seen"].items():
            event = ScheduledEvent.from_dict(json.loads(fingerprint))
            if event_id != event.event_id or fingerprint != _json(event.to_dict()):
                raise ValueError("Invalid seen event fingerprint")
            known[event_id] = event
        queue = cls()
        cursor = value["cursor"]
        if cursor is not None:
            if not isinstance(cursor, list) or len(cursor) != 4:
                raise ValueError("Invalid queue cursor")
            integer(cursor[0], "cursor tick")
            integer(cursor[1], "cursor phase")
            integer(cursor[2], "cursor actor order")
            identifier(cursor[3], "cursor event ID")
            committed = known.get(cursor[3])
            if committed is None or list(committed.key) != cursor:
                raise ValueError("Cursor must refer to a known committed event")
            queue._cursor = committed.key
        pending_ids = set()
        for raw in value["pending"]:
            event = ScheduledEvent.from_dict(raw)
            if event.event_id in pending_ids or known.get(event.event_id) != event:
                raise ValueError("Pending IDs must be unique and present in the ledger")
            if queue._cursor is not None and event.key <= queue._cursor:
                raise ValueError("Pending event precedes the committed cursor")
            pending_ids.add(event.event_id)
            heapq.heappush(queue._heap, (event.key, event))
        for event_id, event in known.items():
            if event_id not in pending_ids and (queue._cursor is None or event.key > queue._cursor):
                raise ValueError("Snapshot lost an uncommitted event")
        queue._seen = dict(value["seen"])
        return queue
