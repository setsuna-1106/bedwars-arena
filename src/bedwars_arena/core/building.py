"""L1 timed building, bed breaking and wool recovery."""
from copy import deepcopy

from .controls import _outcome
from .entities import capacity_for, create_ground
from .geometry import AABB, Vec2
from .legality import interaction_error
from .messages import Intent
from .terrain import Terrain
from .transactions import ChangeSet


def _finish(plan,state,pid,player,action,tick,reason='COMPLETED'):
    updated=deepcopy(player);updated['life']['interaction']=None
    plan.players[pid]=updated
    outcomes=deepcopy(state['execution']['action_outcomes'])
    execution={'request_records':state['execution']['request_records'],'action_outcomes':outcomes}
    _outcome(execution,pid,action,tick,reason,status='completed' if reason=='COMPLETED' else 'interrupted')
    plan.execution_updates['action_outcomes']=outcomes
    return updated


def _support_after_removal(plan,state,definitions,tick):
    """Terrain changes must produce void candidates/removals in the same commit."""
    work=deepcopy(state)
    for key,block in plan.terrain.items():
        if block is None: work['terrain'].pop(key,None)
        else: work['terrain'][key]=deepcopy(block)
    terrain=Terrain.from_world(work,definitions.map.data)
    profile=definitions.profile.data;physics=profile['physics'];ground=profile['ground_items']
    existing={(d['player_id'],d['life_index']) for d in state['execution']['pending_deaths']}
    existing.update((i['payload']['player_id'],i['payload']['life_index'])
                    for i in state['execution']['pending_intents'] if i['kind']=='void_death_candidate')
    for player in state['players'].values():
        if player['life']['kind']!='alive' or (player['player_id'],player['life_index']) in existing:
            continue
        pos=player['life']['spatial'];center=Vec2(pos['x'],pos['z'])
        if not terrain.supported(AABB.centered(center,physics['player_width'],physics['player_depth'])):
            plan.add_intents.append(Intent.create(intent_id=plan.allocate(),kind='void_death_candidate',
                created_at=tick,target_phase=60,payload={'player_id':player['player_id'],
                'life_index':player['life_index'],'position':{'x':pos['x'],'z':pos['z']}}))
    for eid,entity in state['entities'].items():
        pos=entity['spatial'];box=AABB.centered(Vec2(pos['x'],pos['z']),ground['width'],ground['depth'])
        if not terrain.supported(box):
            plan.entities[eid]=None
            plan.emit(kind='ground_item_voided',tick=tick,phase=50,
                      payload={'entity_id':eid,'item':entity['item_key'],'quantity':entity['quantity']})
    return work


def place(state,definitions,tick,pid):
    player=state['players'][pid]
    if player['life']['kind']!='alive': return None
    action=player['life']['interaction']
    if action is None or action['kind']!='place_block': return None
    duration=definitions.profile.data['building']['placement_duration_ticks']
    if tick < action['started_at']+duration: return None
    plan=ChangeSet.from_state(state)
    if interaction_error(state,definitions,pid,action['kind'],action['params']) is not None:
        _finish(plan,state,pid,player,action,tick,'TARGET_INVALIDATED');return plan
    updated=_finish(plan,state,pid,player,action,tick)
    inventory=updated['life']['inventory'];inventory['wool']-=1
    if not inventory['wool']:
        del inventory['wool'];updated['life']['held_item']=None
    payload=action['params'];y=-1 if payload['layer']=='bridge' else 0
    key=f"{payload['x']},{y},{payload['z']}";block_id=plan.allocate()
    plan.terrain[key]={'instance_id':block_id,'kind':'wool'}
    plan.emit(kind='block_placed',tick=tick,phase=45,
              payload={'player_id':pid,'x':payload['x'],'z':payload['z'],'layer':payload['layer'],
                       'instance_id':block_id,'item':'wool','quantity':1})
    return plan


def break_action(state,definitions,tick,pid):
    player=state['players'][pid]
    if player['life']['kind']!='alive': return None
    action=player['life']['interaction']
    if action is None or action['kind'] not in ('break_block','break_bed'): return None
    profile=definitions.profile.data;rules=profile['building']
    duration=rules['wool_break_duration_ticks'] if action['kind']=='break_block' else rules['bed_break_duration_ticks']
    if tick < action['started_at']+duration: return None
    plan=ChangeSet.from_state(state)
    if interaction_error(state,definitions,pid,action['kind'],action['params']) is not None:
        _finish(plan,state,pid,player,action,tick,'TARGET_INVALIDATED');return plan
    updated=_finish(plan,state,pid,player,action,tick)
    if action['kind']=='break_bed':
        team_id=action['params']['team_id'];team=deepcopy(state['teams'][team_id])
        team['bed_state']={'status':'destroyed','destroyed_at':tick};plan.teams[team_id]=team
        attributed=deepcopy(state['execution']['attributed_beds']);attributed[player['team_id']]+=1
        plan.execution_updates['attributed_beds']=attributed
        plan.emit(kind='bed_destroyed',tick=tick,phase=50,
                  payload={'player_id':pid,'team_id':team_id,'attacker_team_id':player['team_id']})
        return plan
    payload=action['params'];y=-1 if payload['layer']=='bridge' else 0
    key=f"{payload['x']},{y},{payload['z']}";plan.terrain[key]=None
    work=_support_after_removal(plan,state,definitions,tick)
    recovery={'received':0,'dropped':0,'destroyed':0};created=[]
    if player['life']['held_item']==rules['recovery_tool']:
        amount=rules['recovery_quantity']
        receive=min(amount,capacity_for(updated['life']['inventory'],'wool',profile))
        if receive:
            inv=updated['life']['inventory'];inv['wool']=inv.get('wool',0)+receive
        recovery['received']=receive;overflow=amount-receive
        if overflow:
            pos=updated['life']['spatial'];gp=profile['ground_items']
            terrain=Terrain.from_world(work,definitions.map.data)
            if terrain.safe_drop(Vec2(pos['x'],pos['z']),gp['width'],gp['depth']):
                created=create_ground(plan,work,definitions,tick=tick,item='wool',quantity=overflow,
                    x=pos['x'],z=pos['z'],delay=gp['recovery_pickup_delay_ticks'],
                    source={'kind':'recovery','source_id':pid})
                recovery['dropped']=overflow
            else:
                recovery['destroyed']=overflow
    plan.emit(kind='block_broken',tick=tick,phase=50,
              payload={'player_id':pid,'instance_id':payload['instance_id'],'x':payload['x'],'z':payload['z'],
                       'layer':payload['layer'],'recovery':recovery,'entity_ids':created})
    return plan
