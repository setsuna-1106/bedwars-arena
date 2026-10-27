"""Versioned complete-boundary JSON snapshot; legacy EventQueue is not a world."""
from copy import deepcopy
import json

from bedwars_arena.core.definitions import _bad_constant, _unique_object
from bedwars_arena.core.world_state import SNAPSHOT_VERSION, definition_ref, runtime_info, validate_state


def encode_snapshot(state: dict, definitions) -> dict:
    validate_state(state, definitions, boundary=True)
    return {'kind':'bedwars-l1-world-snapshot','schema_version':SNAPSHOT_VERSION,
            'runtime':runtime_info(), 'definition_ref':definition_ref(definitions), 'state':deepcopy(state)}


def dumps_snapshot(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def restore_snapshot(snapshot: dict | str, definitions):
    """Verify exact runtime, all definitions and state before publishing a world."""
    from bedwars_arena.core.world import WorldEngine
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot, object_pairs_hook=_unique_object, parse_constant=_bad_constant)
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid snapshot JSON') from error
    if not isinstance(snapshot, dict) or set(snapshot) != {'kind','schema_version','runtime','definition_ref','state'}:
        raise ValueError('Invalid world snapshot; legacy queue is not a complete world')
    if snapshot['kind'] != 'bedwars-l1-world-snapshot' or type(snapshot['schema_version']) is not int or snapshot['schema_version'] != SNAPSHOT_VERSION:
        raise ValueError('Unsupported world snapshot version')
    if snapshot['runtime'] != runtime_info():
        raise ValueError('Snapshot runtime or package version mismatch')
    if snapshot['definition_ref'] != definition_ref(definitions):
        raise ValueError('Snapshot definition hash/version mismatch')
    state = deepcopy(snapshot['state'])
    validate_state(state, definitions, boundary=True, check_positions=True)
    return WorldEngine(definitions, state)
