"""L1 start/settlement geometry and target checks, shared by controls and later handlers."""
import math

from .geometry import AABB, Vec2, distance, distance_to_aabb
from .terrain import Terrain


def _aim(player, target, angle):
    spatial=player['life']['spatial']
    dx,dz=target.x-spatial['x'],target.z-spatial['z']
    length=math.hypot(dx,dz)
    if length == 0:
        return True
    return (dx*spatial['facing_x']+dz*spatial['facing_z'])/length >= math.cos(math.radians(angle))-1e-12


def _center(player):
    spatial=player['life']['spatial']
    return Vec2(spatial['x'],spatial['z'])


def _pending_void(state,player):
    pid=player['player_id'];life_index=player['life_index']
    return (any(d['player_id']==pid and d['life_index']==life_index
                for d in state['execution']['pending_deaths']) or
            any(i['kind']=='void_death_candidate' and i['payload'].get('player_id')==pid and
                i['payload'].get('life_index')==life_index
                for i in state['execution']['pending_intents']))


def interaction_error(state,definitions,player_id,kind,payload):
    """Return a stable public reason, or None when startup is legal now."""
    profile=definitions.profile.data
    map_data=definitions.map.data
    player=state['players'][player_id]
    if player['life']['kind'] != 'alive':
        return 'WRONG_LIFE'
    if _pending_void(state,player):
        return 'WRONG_LIFE'
    terrain=Terrain.from_world(state,map_data)
    source=_center(player)
    held=player['life']['held_item']
    if kind=='attack':
        target=state['players'].get(payload['player_id'])
        if target is None or target['life']['kind']!='alive' or target['life_index']!=payload['life_index'] or _pending_void(state,target):
            return 'INVALID_TARGET'
        if target['team_id']==player['team_id']:
            return 'FRIENDLY_TARGET'
        if held not in ('wooden_sword','iron_sword'):
            return 'ITEM_NOT_HELD'
        target_center=_center(target)
        box=AABB.centered(target_center,profile['physics']['player_width'],profile['physics']['player_depth'])
        if distance_to_aabb(source,box)>profile['combat']['range_blocks']:
            return 'OUT_OF_RANGE'
        if not _aim(player,target_center,profile['combat']['facing_half_angle_degrees']):
            return 'BAD_FACING'
        if not terrain.line_of_sight(source,target_center):
            return 'OCCLUDED'
        return None
    if kind=='break_bed':
        team=state['teams'].get(payload['team_id'])
        if team is None or team['bed_state']['status']!='present':
            return 'INVALID_TARGET'
        if payload['team_id']==player['team_id']:
            return 'FRIENDLY_TARGET'
        if held=='wool':
            return 'ITEM_NOT_HELD'
        definition=next(t for t in map_data['teams'] if t['team_id']==payload['team_id'])
        x,z=definition['bed']['x'],definition['bed']['z']
        target=Vec2(x+0.5,z+0.5)
        ignored=(x,z,'bed',payload['team_id'])
    elif kind in ('break_block','place_block'):
        x,z=payload['x'],payload['z']
        bounds=map_data['bounds']
        if not (bounds['min_x'] <= x < bounds['max_x'] and bounds['min_z'] <= z < bounds['max_z']):
            return 'OUT_OF_BOUNDS'
        y=-1 if payload['layer']=='bridge' else 0
        key=f'{x},{y},{z}'
        block=state['terrain'].get(key)
        target=Vec2(x+0.5,z+0.5)
        ignored=(x,z,'wall','') if y==0 and block else None
        if kind=='break_block':
            if block is None:
                return 'TARGET_GONE'
            if block['instance_id']!=payload['instance_id']:
                return 'TARGET_CHANGED'
            if block['kind']!='wool':
                return 'INVALID_TARGET'
            if held=='wool':
                return 'ITEM_NOT_HELD'
            if y==-1 and f'{x},0,{z}' in state['terrain']:
                return 'WALL_ABOVE_BRIDGE'
        else:
            if held!='wool' or player['life']['inventory'].get('wool',0)<1:
                return 'ITEM_NOT_HELD'
            if block is not None:
                return 'OCCUPIED'
            target_box=AABB(x,x+1,z,z+1)
            if any(target_box.overlaps(AABB(r['bounds']['min_x'],r['bounds']['max_x'],r['bounds']['min_z'],r['bounds']['max_z']))
                   for r in map_data['protected_regions']):
                return 'PROTECTED_REGION'
            if y==0:
                if not terrain.ground_at(x,z):
                    return 'UNSUPPORTED_BLOCK'
                if any(bx==x and bz==z for _,bx,bz in terrain.beds):
                    return 'OCCUPIED'
                for other in state['players'].values():
                    if other['life']['kind']=='alive':
                        box=AABB.centered(_center(other),profile['physics']['player_width'],profile['physics']['player_depth'])
                        if target_box.overlaps(box):
                            return 'OCCUPIED'
            elif not any(terrain.ground_at(x+dx,z+dz) for dx,dz in ((1,0),(-1,0),(0,1),(0,-1))):
                return 'UNSUPPORTED_BLOCK'
    else:
        return 'UNKNOWN_ACTION'
    if distance(source,target)>profile['building']['range_blocks']:
        return 'OUT_OF_RANGE'
    if not _aim(player,target,profile['building']['facing_half_angle_degrees']):
        return 'BAD_FACING'
    if not terrain.line_of_sight(source,target,ignore=ignored):
        return 'OCCLUDED'
    return None
