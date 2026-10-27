"""L1 player values and validation; life branches are mutually exclusive."""
import math

from .time import identifier, integer


def _fields(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f'Invalid {name} fields')


def _number(value, name, *, minimum=None, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f'{name} out of range')
    return value


def validate_player(player: dict, profile: dict, *, tick: int) -> None:
    _fields(player, ('player_id','team_id','life_index','stats','progression','cooldowns','life'), 'player')
    identifier(player['player_id'], 'player_id')
    identifier(player['team_id'], 'team_id')
    integer(player['life_index'], 'life_index', 1)
    _fields(player['stats'], ('kills','deaths','final_kills','final_deaths'), 'stats')
    for value in player['stats'].values():
        integer(value, 'statistic')
    progress = player['progression']
    _fields(progress, ('armor_tier','shears_unlocked','pickaxe_tier','axe_tier'), 'progression')
    if type(progress['armor_tier']) is not int or progress['armor_tier'] not in (0, 1):
        raise ValueError('Invalid L1 armor tier')
    if type(progress['shears_unlocked']) is not bool or not progress['shears_unlocked']:
        raise ValueError('L1 shears must be unlocked')
    if progress['pickaxe_tier'] is not None or progress['axe_tier'] is not None:
        raise ValueError('Pickaxes and axes are disabled in L1')
    cooldowns = player['cooldowns']
    if not isinstance(cooldowns, dict) or cooldowns.keys() - {'attack','hurt'}:
        raise ValueError('Unknown cooldown')
    for value in cooldowns.values():
        integer(value, 'ready_at')
    life = player['life']
    if not isinstance(life, dict) or life.get('kind') not in ('alive','respawning','eliminated'):
        raise ValueError('Invalid life branch')
    if life['kind'] == 'respawning':
        _fields(life, ('kind','died_at','respawn_at'), 'respawning')
        integer(life['died_at'], 'died_at')
        integer(life['respawn_at'], 'respawn_at', 1)
        if life['died_at'] > tick or life['respawn_at'] <= life['died_at']:
            raise ValueError('Invalid respawn interval')
        return
    if life['kind'] == 'eliminated':
        _fields(life, ('kind','eliminated_at','reason'), 'eliminated')
        integer(life['eliminated_at'], 'eliminated_at')
        if life['eliminated_at'] > tick or life['reason'] != 'final_death':
            raise ValueError('Invalid eliminated state')
        return
    _fields(life, ('kind','spatial','vitality','inventory','held_item','effects',
                   'movement','interaction','last_attacker'), 'alive')
    spatial = life['spatial']
    _fields(spatial, ('x','z','facing_x','facing_z','knockback_x','knockback_z'), 'spatial')
    for key, value in spatial.items():
        _number(value, key)
    facing = math.hypot(spatial['facing_x'], spatial['facing_z'])
    if not math.isclose(facing, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError('Facing must be a unit vector')
    if math.hypot(spatial['knockback_x'], spatial['knockback_z']) > profile['physics']['knockback_speed_cap'] + 1e-9:
        raise ValueError('Knockback exceeds configured cap')
    vitality = life['vitality']
    _fields(vitality, ('health','absorption'), 'vitality')
    _number(vitality['health'], 'health', minimum=0, maximum=profile['combat']['max_hp'])
    if vitality['health'] <= 0 or type(vitality['absorption']) not in (int,float) or vitality['absorption'] != 0:
        raise ValueError('Alive L1 player must have positive HP and no absorption')
    inventory = life['inventory']
    if not isinstance(inventory, dict) or inventory.keys() - profile['inventory']['stack_limits'].keys():
        raise ValueError('Unknown inventory item')
    slots = 0
    for item, count in inventory.items():
        integer(count, f'{item} count', 1)
        limit = profile['inventory']['stack_limits'][item]
        slots += (count + limit - 1) // limit
    if slots > profile['inventory']['stack_capacity']:
        raise ValueError('Inventory capacity exceeded')
    if life['held_item'] is not None and life['held_item'] not in inventory:
        raise ValueError('Held item is absent from inventory')
    if not isinstance(life['effects'], list):
        raise ValueError('Effects must be an array')
    ids = set()
    for effect in life['effects']:
        _fields(effect, ('effect_id','effect_type','source','level','expires_at','next_trigger_at'), 'effect')
        identifier(effect['effect_id'], 'effect_id')
        if effect['effect_id'] in ids:
            raise ValueError('Duplicate effect id')
        ids.add(effect['effect_id'])
        if effect['effect_type'] != 'spawn_protection' or effect['source'] != {'kind':'system','source_id':'spawn'} or effect['level'] is not None or effect['next_trigger_at'] is not None:
            raise ValueError('Unsupported L1 effect')
        integer(effect['expires_at'], 'expires_at', 1)
    for name in ('movement','interaction'):
        action = life[name]
        if action is None:
            continue
        _fields(action, ('action_id','kind','target','params','started_at','progress','phase'), 'action')
        identifier(action['action_id'], 'action_id')
        identifier(action['kind'], 'action kind')
        if not isinstance(action['params'], dict):
            raise ValueError('Action params must be an object')
        if name == 'movement':
            if action['kind'] != 'move' or action['target'] is not None or set(action['params']) != {'x','z'}:
                raise ValueError('Invalid L1 movement action')
            _number(action['params']['x'], 'movement x')
            _number(action['params']['z'], 'movement z')
        integer(action['started_at'], 'started_at')
        if action['started_at'] > tick:
            raise ValueError('Action start time is in the future')
        _number(action['progress'], 'progress', minimum=0)
        identifier(action['phase'], 'action phase')
    attacker = life['last_attacker']
    if attacker is not None:
        _fields(attacker, ('player_id','attacked_at'), 'last attacker')
        identifier(attacker['player_id'], 'attacker')
        integer(attacker['attacked_at'], 'attacked_at')
        if attacker['attacked_at'] > tick:
            raise ValueError('Attack time is in the future')
