"""Construction and strict validation for the L1 world and its execution state."""
from copy import deepcopy
from hashlib import sha256
from functools import lru_cache
import json
import math
from pathlib import Path
import random
import re
import sys
from uuid import uuid4

from bedwars_arena import __version__
from .definitions import L1Definitions, validate_l1_definitions
from .messages import Intent, PHASES, ScheduledTask, fact_from_dict
from .player import validate_player
from .scheduler import _json
from .team import BedState, BedStatus, TeamState
from .time import identifier, integer
from .transactions import schedule

RNG_STREAMS = ('world', 'physics', 'economy', 'combat')
SNAPSHOT_VERSION = 1


@lru_cache(maxsize=128)
def _verified_definition_ref(definitions: L1Definitions) -> str:
    if not isinstance(definitions, L1Definitions):
        raise ValueError('Expected L1Definitions')
    checked = validate_l1_definitions(definitions.profile.data, definitions.map.data,
                                      definitions.scenario.data, expected_hashes=definitions.hashes)
    for key in ('profile','map','scenario'):
        if getattr(checked, key) != getattr(definitions, key):
            raise ValueError('Inconsistent definition identity or content')
    return _json({name: {'id': getattr(definitions, name).id, 'version': getattr(definitions, name).version,
                        'sha256': getattr(definitions, name).sha256}
                  for name in ('profile','map','scenario')})


def definition_ref(definitions: L1Definitions) -> dict:
    # Never expose the cached object itself as mutable world state.
    return json.loads(_verified_definition_ref(definitions))


@lru_cache(maxsize=1)
def _package_code_hash() -> str:
    root=Path(__file__).resolve().parent.parent
    digest=sha256()
    files=sorted(path for path in root.rglob('*') if path.is_file() and path.suffix in ('.py','.json'))
    for path in files:
        name=path.relative_to(root).as_posix().encode('utf-8')
        content=path.read_bytes()
        digest.update(len(name).to_bytes(8,'big'));digest.update(name)
        digest.update(len(content).to_bytes(8,'big'));digest.update(content)
    return digest.hexdigest()


def runtime_info() -> dict:
    return {'package_version': __version__, 'implementation': sys.implementation.name,
            'python': '.'.join(map(str, sys.version_info[:3])), 'rng_derivation': 'sha256-v1',
            'world_engine_revision': 'l1-p6-1', 'code_sha256':_package_code_hash()}


def _seed_states(seed: int) -> dict:
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('seed must be an unsigned 64-bit integer')
    states = {}
    for name in RNG_STREAMS:
        material = b'BedWarsArena.RNG.v1\0' + seed.to_bytes(8, 'big') + b'\0' + name.encode('utf-8')
        derived = int.from_bytes(sha256(material).digest(), 'big')
        state = random.Random(derived).getstate()
        states[name] = [state[0], list(state[1]), state[2]]
    return states


def _id(execution: dict) -> str:
    value = execution['next_id']
    integer(value, 'next_id', 1)
    execution['next_id'] += 1
    return f'i{value:016x}'


def _require_fields(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f'Invalid {name} fields')


def _terrain_key(x, y, z):
    return f'{x},{y},{z}'


def _new_task(execution, *, kind, due, phase, order, payload, budget):
    task = ScheduledTask.create(task_id=_id(execution), kind=kind, created_at=0,
                                execute_at=due, phase=phase, source_order=order, payload=payload)
    return task


def create_state(definitions: L1Definitions, *, seed: int, match_id: str | None = None,
                 preset: dict | None = None) -> tuple[dict, tuple[dict, ...]]:
    """Build a standard game or an explicit, validated tick-0 training preset."""
    refs = definition_ref(definitions)
    profile, map_data, scenario = definitions.profile.data, definitions.map.data, definitions.scenario.data
    if match_id is None:
        match_id = uuid4().hex
    identifier(match_id, 'match_id')
    if preset is None:
        preset = {}
    if not isinstance(preset, dict) or preset.keys() - {'players','beds','generator_first_ticks','ground_items','source'}:
        raise ValueError('Unknown training preset field')
    overrides = preset.get('players', {})
    beds = preset.get('beds', {})
    generator_first = preset.get('generator_first_ticks', {})
    if not all(isinstance(x, dict) for x in (overrides, beds, generator_first)):
        raise ValueError('Preset players, beds and generator times must be objects')
    if 'source' in preset:
        identifier(preset['source'], 'preset source')
    expected_players = {p['player_id'] for p in scenario['players']}
    team_ids = {t['team_id'] for t in map_data['teams']}
    generator_ids = {g['generator_id'] for g in map_data['generators']}
    if overrides.keys() - expected_players or beds.keys() - team_ids or generator_first.keys() - generator_ids:
        raise ValueError('Preset references an unknown player, team or generator')
    execution = {'version': 2, 'next_id': 1, 'revision': 0, 'cursor': {'tick': 0, 'phase': 90},
                 'pending_tasks': [], 'pending_intents': [], 'seen_messages': {}, 'cancelled': [],
                 'pending_requests': [], 'request_records': {}, 'round': None, 'round_history': {},
                 'action_outcomes': {}, 'packet_errors': {}, 'pending_deaths': [], 'diagnostics': [],
                 'rng_seed_hex': f'{seed:016x}' if type(seed) is int and 0 <= seed < 2**64 else '',
                 'rng_states': _seed_states(seed), 'log_cursor': 0,
                 'attributed_beds': {team_id: 0 for team_id in sorted(team_ids)}}
    state = {'match_id': match_id, 'definition_ref': refs, 'tick': 0, 'players': {}, 'teams': {},
             'terrain': {}, 'generators': {}, 'containers': {}, 'entities': {},
             'execution': execution, 'result': None, 'preset_source': preset.get('source')}
    for island in map_data['terrain']['islands']:
        b = island['bounds']
        for x in range(b['min_x'], b['max_x']):
            for z in range(b['min_z'], b['max_z']):
                state['terrain'][_terrain_key(x, -1, z)] = {'instance_id': _id(execution), 'kind': 'original'}
    team_map = {team['team_id']: team for team in map_data['teams']}
    for team_id in (team['team_id'] for team in map_data['teams']):
        present = beds.get(team_id, True)
        if type(present) is not bool:
            raise ValueError('Preset bed must be a boolean')
        team = TeamState.initial(team_id, t0=0)
        if not present:
            team = TeamState(team_id, BedState(BedStatus.DESTROYED, 0))
        state['teams'][team_id] = team.to_dict()
    budget = profile['budget']
    initial_facts = []
    commit_id = _id(execution)
    for order, entry in enumerate(scenario['players']):
        pid, team_id = entry['player_id'], entry['team_id']
        override = overrides.get(pid, {})
        if not isinstance(override, dict) or override.keys() - {'x','z','facing_x','facing_z','inventory',
                      'held_item','health','armor_tier','protection_ticks','knockback_x','knockback_z'}:
            raise ValueError(f'Invalid player preset: {pid}')
        team = team_map[team_id]
        spatial = {'x': override.get('x', team['spawn']['x']), 'z': override.get('z', team['spawn']['z']),
                   'facing_x': override.get('facing_x', team['facing']['x']),
                   'facing_z': override.get('facing_z', team['facing']['z']),
                   'velocity_x': 0.0, 'velocity_z': 0.0,
                   'knockback_x': override.get('knockback_x', 0.0),
                   'knockback_z': override.get('knockback_z', 0.0)}
        protection = override.get('protection_ticks', profile['life']['protection_duration_ticks'])
        integer(protection, 'protection_ticks')
        effects = []
        if protection:
            effect_id = _id(execution)
            effects.append({'effect_id': effect_id, 'effect_type': 'spawn_protection',
                            'source': {'kind':'system','source_id':'spawn'}, 'level': None,
                            'expires_at': protection, 'next_trigger_at': None})
            task = _new_task(execution, kind='expire_protection', due=protection, phase=0, order=order,
                             payload={'player_id':pid, 'life_index':1, 'effect_id':effect_id}, budget=budget)
            schedule(state, task, budget)
        inventory = deepcopy(override.get('inventory', profile['inventory']['initial_items']))
        player = {'player_id': pid, 'team_id': team_id, 'life_index': 1,
                  'stats': {'kills':0,'deaths':0,'final_kills':0,'final_deaths':0},
                  'progression': {'armor_tier':override.get('armor_tier', profile['inventory']['initial_armor_tier']),
                                  'shears_unlocked':True,'pickaxe_tier':None,'axe_tier':None},
                  'cooldowns': {},
                  'life': {'kind':'alive', 'spatial':spatial,
                           'vitality': {'health':override.get('health', profile['combat']['max_hp']), 'absorption':0},
                           'inventory':inventory, 'held_item':override.get('held_item', profile['inventory']['initial_held_item']),
                           'effects':effects, 'movement':None, 'interaction':None, 'last_attacker':None}}
        state['players'][pid] = player
        fact = {'version':1,'category':'fact','id':_id(execution),'commit_id':commit_id,
                'kind':'player_spawned','happened_at':0,'phase':0,
                'payload':{'player_id':pid,'life_index':1},'caused_by':None}
        execution['seen_messages'][fact['id']] = _json(fact)
        initial_facts.append(fact)
    for order, definition in enumerate(map_data['generators']):
        gid = definition['generator_id']
        due = generator_first.get(gid, profile['generators'][definition['kind']]['first_spawn_ticks'])
        integer(due, 'generator_first_tick', 1)
        schedule_id = _id(execution)
        state['generators'][gid] = {'generator_id': gid, 'next_spawn_at': due, 'schedule_id':schedule_id}
        task = _new_task(execution, kind='generator_spawn', due=due, phase=25, order=order,
                         payload={'generator_id':gid,'schedule_id':schedule_id}, budget=budget)
        schedule(state, task, budget)
    for kind, when, stage in (('global_bed_destruction',profile['schedule']['global_bed_destruction_tick'],50),
                               ('game_end',profile['schedule']['game_end_tick'],90)):
        task = _new_task(execution, kind=kind, due=when, phase=stage, order=0, payload={}, budget=budget)
        schedule(state, task, budget)
    ground_items=preset.get('ground_items',[])
    if not isinstance(ground_items,list):
        raise ValueError('Preset ground_items must be an array')
    from .entities import make_item
    for spec in ground_items:
        if not isinstance(spec,dict) or not {'item_key','quantity','x','z'} <= spec.keys() or spec.keys() - {'item_key','quantity','x','z','pickup_ready_at'}:
            raise ValueError('Invalid preset ground item')
        item=spec['item_key']
        if item not in profile['ground_items']['entity_limits']:
            raise ValueError('Unknown preset ground item')
        quantity=integer(spec['quantity'],'quantity',1)
        ready=integer(spec.get('pickup_ready_at',0),'pickup_ready_at')
        limit=profile['ground_items']['entity_limits'][item]
        while quantity:
            count=min(limit,quantity);quantity-=count
            if len(state['entities'])>=budget['ground_entities']:
                raise ValueError('Ground entity budget exceeded')
            entity_id=_id(execution);expires=profile['ground_items']['lifetime_ticks']
            state['entities'][entity_id]=make_item(entity_id=entity_id,item=item,quantity=count,
                x=spec['x'],z=spec['z'],created_at=0,pickup_ready_at=ready,expires_at=expires,
                source={'kind':'preset','source_id':'training'},profile=profile)
            task=_new_task(execution,kind='expire_ground_item',due=expires,phase=0,order=0,
                           payload={'entity_id':entity_id},budget=budget)
            schedule(state,task,budget)
            fact={'version':1,'category':'fact','id':_id(execution),'commit_id':commit_id,
                  'kind':'ground_item_preset','happened_at':0,'phase':0,
                  'payload':{'entity_id':entity_id,'item':item,'quantity':count},'caused_by':None}
            execution['seen_messages'][fact['id']]=_json(fact)
            initial_facts.append(fact)
    execution['log_cursor'] = len(initial_facts)
    validate_state(state, definitions, boundary=True)
    return state, tuple(initial_facts)


def validate_state(state: dict, definitions: L1Definitions, *, boundary: bool = False) -> None:
    _require_fields(state, ('match_id','definition_ref','tick','players','teams','terrain','generators',
                            'containers','entities','execution','result','preset_source'), 'WorldState')
    _json(state)  # recursively reject non-JSON, unsafe integers and nonfinite floats
    identifier(state['match_id'], 'match_id')
    integer(state['tick'], 'tick')
    if state['definition_ref'] != definition_ref(definitions):
        raise ValueError('World definition reference mismatch')
    if state['preset_source'] is not None:
        identifier(state['preset_source'], 'preset_source')
    profile, map_data, scenario = definitions.profile.data, definitions.map.data, definitions.scenario.data
    if not all(isinstance(state[k], dict) for k in ('players','teams','terrain','generators','containers','entities','execution')):
        raise ValueError('Invalid world collections')
    if state['containers']:
        raise ValueError('Containers are disabled in L1')
    if len(state['entities']) > profile['budget']['ground_entities']:
        raise ValueError('Ground entity budget exceeded')
    entries = {p['player_id']:p['team_id'] for p in scenario['players']}
    if set(state['players']) != set(entries) or set(state['teams']) != {t['team_id'] for t in map_data['teams']}:
        raise ValueError('World roster mismatch')
    execution = state['execution']
    _require_fields(execution, ('version','next_id','revision','cursor','pending_tasks','pending_intents','seen_messages',
                                'cancelled','pending_requests','request_records','round','round_history','action_outcomes','packet_errors',
                                'pending_deaths','diagnostics',
                                'rng_seed_hex','rng_states','log_cursor','attributed_beds'), 'execution')
    if type(execution['version']) is not int or execution['version'] != 2:
        raise ValueError('Unsupported execution schema (legacy queue is not a world snapshot)')
    integer(execution['next_id'], 'next_id', 1)
    integer(execution['revision'], 'revision')
    integer(execution['log_cursor'], 'log_cursor')
    cursor = execution['cursor']
    _require_fields(cursor, ('tick','phase'), 'cursor')
    integer(cursor['tick'], 'cursor tick')
    if type(cursor['phase']) is not int or cursor['phase'] not in PHASES:
        raise ValueError('Invalid phase cursor')
    if boundary and cursor != {'tick':state['tick'],'phase':90}:
        raise ValueError('Snapshot is not at a complete tick boundary')
    if cursor['tick'] not in (state['tick'], state['tick'] + 1):
        raise ValueError('Cursor is not at the current/next tick')
    now = cursor['tick']
    for player_id, player in state['players'].items():
        validate_player(player, profile, tick=now)
        if player['player_id'] != player_id or player['team_id'] != entries[player_id]:
            raise ValueError('Player identity/roster mismatch')
    for team_id, raw in state['teams'].items():
        team = TeamState.from_dict(raw)
        if team.team_id != team_id or team.upgrades or team.trap_queue:
            raise ValueError('Invalid L1 team or disabled team mechanic')
        if team.bed_state.destroyed_at is not None and team.bed_state.destroyed_at > now:
            raise ValueError('Future bed destruction')
    gids = {g['generator_id'] for g in map_data['generators']}
    if set(state['generators']) != gids:
        raise ValueError('Generator set mismatch')
    all_ids = set()
    def unique(value):
        identifier(value, 'instance id')
        if value in all_ids:
            raise ValueError('Duplicate live instance ID')
        all_ids.add(value)
    original_cells = {(x, -1, z) for island in map_data['terrain']['islands']
                      for x in range(island['bounds']['min_x'], island['bounds']['max_x'])
                      for z in range(island['bounds']['min_z'], island['bounds']['max_z'])}
    present_originals = set()
    for key, block in state['terrain'].items():
        if not isinstance(key,str) or not re.fullmatch(r'-?(0|[1-9][0-9]*),-?(0|[1-9][0-9]*),-?(0|[1-9][0-9]*)',key):
            raise ValueError('Invalid terrain coordinate')
        x,y,z = (int(n) for n in key.split(','))
        if key != _terrain_key(x,y,z):
            raise ValueError('Terrain coordinate must use canonical integer encoding')
        bounds = map_data['bounds']
        if not (bounds['min_x'] <= x < bounds['max_x'] and bounds['min_z'] <= z < bounds['max_z'] and y in (-1,0)):
            raise ValueError('Terrain outside L1 map/layers')
        _require_fields(block, ('instance_id','kind'), 'terrain block')
        if block['kind'] not in ('original','wool') or block['kind'] == 'original' and y != -1:
            raise ValueError('Unknown terrain block')
        if block['kind'] == 'original':
            present_originals.add((x,y,z))
        unique(block['instance_id'])
    if present_originals != original_cells:
        raise ValueError('Original island terrain must remain intact')
    for gid, gen in state['generators'].items():
        _require_fields(gen, ('generator_id','next_spawn_at','schedule_id'), 'generator')
        if gen['generator_id'] != gid:
            raise ValueError('Generator identity mismatch')
        integer(gen['next_spawn_at'], 'next_spawn_at', 1)
        unique(gen['schedule_id'])
    from .entities import validate_item
    from .terrain import Terrain
    terrain_view = Terrain.from_world(state,map_data)
    for entity_id, entity in state['entities'].items():
        if entity.get('entity_id') != entity_id:
            raise ValueError('Ground item identity mismatch')
        unique(entity_id)
        validate_item(entity,profile=profile,terrain=terrain_view,now=now,phase=cursor['phase'])
        source=entity['source']
        if source['kind']=='generator' and source['source_id'] not in gids:
            raise ValueError('Unknown generator source')
        if source['kind'] in ('player_drop','recovery','death') and source['source_id'] not in entries:
            raise ValueError('Unknown player source')
    for player in state['players'].values():
        if player['life']['kind'] == 'alive':
            for effect in player['life']['effects']:
                unique(effect['effect_id'])
            for channel in ('movement','interaction'):
                if player['life'][channel] is not None:
                    unique(player['life'][channel]['action_id'])
            attacker = player['life']['last_attacker']
            if attacker is not None and attacker['player_id'] not in entries:
                raise ValueError('Unknown attacker')
    for name in ('pending_tasks','pending_intents','cancelled','pending_requests','pending_deaths','diagnostics'):
        if not isinstance(execution[name], list):
            raise ValueError(f'{name} must be an array')
    from bedwars_arena.interfaces.actions import validate_execution_requests
    validate_execution_requests(execution,state,profile)
    if not isinstance(execution['seen_messages'], dict) or not isinstance(execution['request_records'], dict):
        raise ValueError('Invalid message ledger')
    if len(execution['seen_messages']) > profile['budget']['seen_messages_and_requests']:
        raise ValueError('Message ledger budget exceeded')
    if len(execution['pending_tasks']) > profile['budget']['active_scheduled_tasks'] or len(execution['pending_intents']) > profile['budget']['pending_intents']:
        raise ValueError('Pending message budget exceeded')
    facts_seen = 0
    for message_id, encoded in execution['seen_messages'].items():
        if not isinstance(encoded, str):
            raise ValueError('Invalid message fingerprint')
        try:
            raw = json.loads(encoded)
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid message fingerprint') from error
        if not isinstance(raw,dict) or _json(raw) != encoded or raw.get('id') != message_id:
            raise ValueError('Noncanonical message fingerprint')
        category = raw.get('category')
        if category == 'task':
            ScheduledTask.from_dict(raw)
        elif category == 'intent':
            Intent.from_dict(raw)
        elif category == 'fact':
            fact_from_dict(raw)
            facts_seen += 1
        else:
            raise ValueError('Unknown message category')
        if not re.fullmatch(r'i[0-9a-f]{16}',message_id) or int(message_id[1:],16) >= execution['next_id']:
            raise ValueError('Message ID outside allocator history')
        if category == 'fact':
            commit_id = raw['commit_id']
            if not re.fullmatch(r'i[0-9a-f]{16}',commit_id) or int(commit_id[1:],16) >= execution['next_id']:
                raise ValueError('Commit ID outside allocator history')
        cause = raw.get('caused_by')
        if cause is not None and cause['id'] not in execution['seen_messages']:
            raise ValueError('Unknown causal message')
    if execution['log_cursor'] != facts_seen:
        raise ValueError('Fact log cursor mismatch')
    for instance_id in all_ids:
        if not re.fullmatch(r'i[0-9a-f]{16}',instance_id) or int(instance_id[1:],16) >= execution['next_id']:
            raise ValueError('Instance ID outside allocator history')
        if instance_id in execution['seen_messages']:
            raise ValueError('Instance and message IDs collide')
    tasks = [ScheduledTask.from_dict(item) for item in execution['pending_tasks']]
    if [t.key for t in tasks] != sorted(t.key for t in tasks) or len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError('Task order or identity invalid')
    for task in tasks:
        if ((task.execute_at,task.phase) < (cursor['tick'],cursor['phase'])
                or boundary and (task.execute_at,task.phase) <= (cursor['tick'],cursor['phase'])):
            raise ValueError('Task lies behind phase cursor')
        if execution['seen_messages'].get(task.task_id) != _json(task.to_dict()):
            raise ValueError('Task ledger mismatch')
    for entity_id, entity in state['entities'].items():
        if not any(t.kind == 'expire_ground_item' and t.execute_at == entity['expires_at'] and
                   t.payload == {'entity_id':entity_id} and t.task_id not in execution['cancelled'] for t in tasks):
            raise ValueError('Ground item has no matching expiry task')
    for gid, gen in state['generators'].items():
        if not any(t.kind == 'generator_spawn' and t.execute_at == gen['next_spawn_at']
                   and t.payload == {'generator_id':gid,'schedule_id':gen['schedule_id']}
                   and t.task_id not in execution['cancelled'] for t in tasks):
            raise ValueError('Generator has no matching current schedule')
    for pid, player in state['players'].items():
        if player['life']['kind'] == 'respawning':
            due=player['life']['respawn_at']
            expected={'player_id':pid,'life_index':player['life_index'],'respawn_at':due}
            if not any(t.kind=='respawn' and t.execute_at==due and t.payload==expected and
                       t.task_id not in execution['cancelled'] for t in tasks):
                raise ValueError('Respawning life has no matching task')
            continue
        if player['life']['kind'] != 'alive':
            continue
        for effect in player['life']['effects']:
            expected = {'player_id':pid,'life_index':player['life_index'],'effect_id':effect['effect_id']}
            if not any(t.kind == 'expire_protection' and t.execute_at == effect['expires_at']
                       and t.payload == expected and t.task_id not in execution['cancelled'] for t in tasks):
                raise ValueError('Effect has no matching expiration task')
    intents = [Intent.from_dict(item) for item in execution['pending_intents']]
    if len({i.intent_id for i in intents}) != len(intents):
        raise ValueError('Duplicate intent')
    for intent in intents:
        if intent.created_at != cursor['tick'] or intent.target_phase < cursor['phase'] or execution['seen_messages'].get(intent.intent_id) != _json(intent.to_dict()):
            raise ValueError('Invalid intent or ledger')
        raw = intent.to_dict()
        if intent.kind == 'void_death_candidate':
            payload = raw['payload']
            if set(payload) != {'player_id','life_index','position'} or intent.target_phase != 60:
                raise ValueError('Invalid void intent payload')
            player = state['players'].get(payload['player_id'])
            if player is None or player['life']['kind'] != 'alive' or player['life_index'] != payload['life_index']:
                raise ValueError('Void intent references an inactive life')
            spatial = player['life']['spatial']
            if payload['position'] != {'x':spatial['x'],'z':spatial['z']}:
                raise ValueError('Void intent position mismatch')
    if len(set(execution['cancelled'])) != len(execution['cancelled']) or any(i not in execution['seen_messages'] or json.loads(execution['seen_messages'][i])['category'] != 'task' for i in execution['cancelled']):
        raise ValueError('Invalid cancellations')
    death_keys = set()
    for candidate in execution['pending_deaths']:
        _require_fields(candidate, ('intent_id','player_id','life_index','tick','reason','position'), 'death candidate')
        identifier(candidate['intent_id'], 'intent_id')
        pid = candidate['player_id']
        player = state['players'].get(pid)
        if player is None or player['life']['kind'] != 'alive' or candidate['life_index'] != player['life_index']:
            raise ValueError('Death candidate references an inactive life')
        integer(candidate['tick'], 'candidate tick', 1)
        if candidate['tick'] > now or candidate['reason'] != 'void':
            raise ValueError('Invalid death candidate')
        _require_fields(candidate['position'], ('x','z'), 'candidate position')
        for value in candidate['position'].values():
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError('Invalid candidate position')
        spatial = player['life']['spatial']
        if candidate['position'] != {'x':spatial['x'],'z':spatial['z']}:
            raise ValueError('Death candidate position mismatch')
        key = (pid,candidate['life_index'])
        if key in death_keys:
            raise ValueError('Duplicate death candidate for a life')
        death_keys.add(key)
        fingerprint = execution['seen_messages'].get(candidate['intent_id'])
        raw = json.loads(fingerprint) if fingerprint is not None else None
        if (not isinstance(raw,dict) or raw.get('category') != 'intent' or
                raw.get('kind') != 'void_death_candidate' or raw.get('target_phase') != 60 or
                raw.get('created_at') != candidate['tick'] or raw.get('payload') !=
                {'player_id':pid,'life_index':candidate['life_index'],'position':candidate['position']}):
            raise ValueError('Death candidate intent mismatch')
    if not isinstance(execution['attributed_beds'],dict) or set(execution['attributed_beds']) != set(state['teams']):
        raise ValueError('Invalid bed attribution counters')
    for count in execution['attributed_beds'].values():
        integer(count, 'attributed beds')
    if not isinstance(execution['rng_seed_hex'],str) or not re.fullmatch(r'[0-9a-f]{16}',execution['rng_seed_hex']):
        raise ValueError('Invalid 64-bit seed')
    if not isinstance(execution['rng_states'],dict) or set(execution['rng_states']) != set(RNG_STREAMS):
        raise ValueError('Invalid RNG streams')
    for value in execution['rng_states'].values():
        if not isinstance(value,list) or len(value) != 3 or not isinstance(value[1],list):
            raise ValueError('Invalid RNG state')
        try:
            random.Random().setstate((value[0], tuple(value[1]), value[2]))
        except (TypeError, ValueError) as error:
            raise ValueError('Invalid RNG state') from error
    if state['result'] is not None:
        result=state['result']
        _require_fields(result,('kind','winner_team_id','reason','tick'),'world result')
        integer(result['tick'],'result tick',1)
        if result['tick']>now or result['kind'] not in ('win','draw') or result['reason'] not in ('elimination','mutual_elimination','game_end'):
            raise ValueError('Invalid world result')
        if result['kind']=='win' and result['winner_team_id'] not in state['teams'] or result['kind']=='draw' and result['winner_team_id'] is not None:
            raise ValueError('Invalid result winner')
        if result['tick'] != now or cursor['phase'] != 90:
            raise ValueError('Result must be at its completed outcome phase')
        active=[team_id for team_id in state['teams'] if any(
            p['team_id']==team_id and p['life']['kind']!='eliminated' for p in state['players'].values())]
        if result['reason']=='mutual_elimination' and (active or result['kind']!='draw'):
            raise ValueError('Mutual-elimination result does not match lives')
        if result['reason']=='elimination' and (len(active)!=1 or result['winner_team_id']!=active[0] or result['kind']!='win'):
            raise ValueError('Elimination result does not match lives')
        if result['reason']=='game_end':
            if result['tick']!=profile['schedule']['game_end_tick'] or len(active)<2:
                raise ValueError('Invalid Game End boundary')
            scores={team_id:(sum(p['team_id']==team_id and p['life']['kind']!='eliminated' for p in state['players'].values()),
                             execution['attributed_beds'][team_id]) for team_id in active}
            best=max(scores.values());winners=[team_id for team_id in active if scores[team_id]==best]
            if (result['kind']=='win' and (len(winners)!=1 or result['winner_team_id']!=winners[0]) or
                    result['kind']=='draw' and len(winners)==1):
                raise ValueError('Game End result does not match scores')
    # An internal plan must not introduce penetration or unrecorded loss of support.
    _validate_initial_positions(state, profile, map_data)


def _validate_initial_positions(state, profile, map_data):
    half_x, half_z = profile['physics']['player_width']/2, profile['physics']['player_depth']/2
    b = map_data['bounds']
    pending = {(item['player_id'],item['life_index']) for item in state['execution']['pending_deaths']}
    pending.update((intent['payload']['player_id'],intent['payload']['life_index'])
                   for intent in state['execution']['pending_intents']
                   if intent['kind'] == 'void_death_candidate'
                   and set(intent['payload']) == {'player_id','life_index','position'})
    for player in state['players'].values():
        if player['life']['kind'] != 'alive':
            continue
        pos = player['life']['spatial']
        x,z = pos['x'],pos['z']
        awaiting_death = (player['player_id'],player['life_index']) in pending
        if not awaiting_death and not (b['min_x'] <= x < b['max_x'] and b['min_z'] <= z < b['max_z']):
            raise ValueError('Player outside map')
        supported = False
        for ix in range(math.floor(x-half_x), math.ceil(x+half_x)):
            for iz in range(math.floor(z-half_z), math.ceil(z+half_z)):
                if _terrain_key(ix,-1,iz) in state['terrain'] and max(x-half_x,ix) < min(x+half_x,ix+1) and max(z-half_z,iz) < min(z+half_z,iz+1):
                    supported = True
                if _terrain_key(ix,0,iz) in state['terrain'] and max(x-half_x,ix) < min(x+half_x,ix+1) and max(z-half_z,iz) < min(z+half_z,iz+1):
                    raise ValueError('Player penetrates a wall')
        for team in map_data['teams']:
            if state['teams'][team['team_id']]['bed_state']['status'] == 'present':
                bed = team['bed']
                if max(x-half_x,bed['x']) < min(x+half_x,bed['x']+1) and max(z-half_z,bed['z']) < min(z+half_z,bed['z']+1):
                    raise ValueError('Player penetrates a bed')
        if not supported and not awaiting_death:
            raise ValueError('Player has no positive-area support')
