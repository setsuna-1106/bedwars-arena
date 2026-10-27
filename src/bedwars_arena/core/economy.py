"""L1 generation, pickup, shop and resource drop transactions."""
from copy import deepcopy

from .controls import _outcome
from .entities import capacity_for, create_ground
from .geometry import AABB, Vec2, distance
from .messages import ScheduledTask
from .terrain import Terrain
from .transactions import ChangeSet


def generator_attempt(state,definitions,task):
    tick=task.execute_at
    plan=ChangeSet.from_state(state);plan.consume_tasks.append(task.task_id)
    payload=task.payload
    if set(payload)!={'generator_id','schedule_id'}:
        raise ValueError('Invalid generator task')
    gid=payload['generator_id'];gen=state['generators'].get(gid)
    if gen is None or gen['schedule_id']!=payload['schedule_id'] or gen['next_spawn_at']!=tick:
        plan.diagnostics.append({'tick':tick,'phase':25,'task_id':task.task_id,'reason':'stale_instance'})
        return plan
    profile=definitions.profile.data
    definition=next(x for x in definitions.map.data['generators'] if x['generator_id']==gid)
    rules=profile['generators'][definition['kind']]
    x,z=definition['position']['x'],definition['position']['z'];half=profile['generators']['accumulation_half_width']
    min_y,max_y=profile['generators']['accumulation_min_y'],profile['generators']['accumulation_max_y']
    count=sum(e['quantity'] for e in state['entities'].values() if e['item_key']=='iron' and
              x-half <= e['spatial']['x'] < x+half and z-half <= e['spatial']['z'] < z+half and
              min_y <= e['spatial']['y'] < max_y)
    amount=min(rules['quantity'],max(0,rules['capacity']-count))
    updated=deepcopy(gen);updated['next_spawn_at']=tick+rules['period_ticks'];plan.generators[gid]=updated
    plan.add_tasks.append(ScheduledTask.create(task_id=plan.allocate(),kind='generator_spawn',
        created_at=tick,execute_at=updated['next_spawn_at'],phase=25,source_order=task.source_order,
        payload={'generator_id':gid,'schedule_id':gen['schedule_id']},
        caused_by={'category':'task','id':task.task_id}))
    if amount:
        ids=create_ground(plan,state,definitions,tick=tick,item='iron',quantity=amount,x=x,z=z,
                          delay=profile['ground_items']['generator_pickup_delay_ticks'],
                          source={'kind':'generator','source_id':gid})
        plan.emit(kind='resource_generated',tick=tick,phase=25,
                  payload={'generator_id':gid,'item':'iron','quantity':amount,'entity_ids':ids},
                  caused_by={'category':'task','id':task.task_id})
    return plan


def expire_ground(state,task):
    plan=ChangeSet.from_state(state);plan.consume_tasks.append(task.task_id)
    payload=task.payload
    if set(payload)!={'entity_id'}:
        raise ValueError('Invalid ground expiry task')
    item=state['entities'].get(payload['entity_id'])
    if item is None or item['expires_at']!=task.execute_at:
        plan.diagnostics.append({'tick':task.execute_at,'phase':0,'task_id':task.task_id,'reason':'stale_instance'})
        return plan
    plan.entities[item['entity_id']]=None
    plan.emit(kind='ground_item_expired',tick=task.execute_at,phase=0,
              payload={'entity_id':item['entity_id'],'item':item['item_key'],'quantity':item['quantity']},
              caused_by={'category':'task','id':task.task_id})
    return plan


def pickup(state,definitions,tick,pid,eid):
    player=state['players'][pid];entity=state['entities'].get(eid)
    if player['life']['kind']!='alive' or entity is None:
        return None
    if any(i['kind']=='void_death_candidate' and i['payload']['player_id']==pid and
           i['payload']['life_index']==player['life_index'] for i in state['execution']['pending_intents']):
        return None
    if any(d['player_id']==pid and d['life_index']==player['life_index'] for d in state['execution']['pending_deaths']):
        return None
    if not entity['pickup_ready_at']<=tick<entity['expires_at']:
        return None
    profile=definitions.profile.data;physics=profile['physics'];ground=profile['ground_items']
    spatial=player['life']['spatial'];p=Vec2(spatial['x'],spatial['z'])
    box=AABB.centered(p,physics['player_width'],physics['player_depth']).expanded(
        ground['pickup_horizontal_expansion'],ground['pickup_horizontal_expansion'])
    itempos=entity['spatial']
    if not box.contains_closed(Vec2(itempos['x'],itempos['z'])) or not -ground['pickup_vertical_expansion'] <= itempos['y'] <= physics['player_height']+ground['pickup_vertical_expansion']:
        return None
    count=min(entity['quantity'],capacity_for(player['life']['inventory'],entity['item_key'],profile))
    if count<=0:
        return None
    plan=ChangeSet.from_state(state)
    updated=deepcopy(player);inventory=updated['life']['inventory'];key=entity['item_key']
    inventory[key]=inventory.get(key,0)+count;plan.players[pid]=updated
    remaining=entity['quantity']-count
    if remaining:
        updated_entity=deepcopy(entity);updated_entity['quantity']=remaining;plan.entities[eid]=updated_entity
    else:
        plan.entities[eid]=None
    plan.emit(kind='item_picked_up',tick=tick,phase=32,
              payload={'player_id':pid,'entity_id':eid,'item':key,'quantity':count})
    return plan


def _request_finish(plan,state,item,tick,reason,*,action_id=None):
    execution=state['execution'];records=deepcopy(execution['request_records'])
    entry=records[item['player_id']][item['request_id']]['result']
    entry.update(status='applied' if reason in ('OK','NO_CHANGE') else 'failed',reason=reason,
                 processed_tick=tick,action_id=action_id)
    plan.execution_updates['request_records']=records
    plan.execution_updates['pending_requests']=[r for r in execution['pending_requests']
        if (r['player_id'],r['request_id'])!=(item['player_id'],item['request_id'])]


def _valid_player(state,item):
    player=state['players'][item['player_id']]
    if player['life']['kind']!='alive' or player['life_index']!=item['life_index']:
        return None
    if any(d['player_id']==player['player_id'] and d['life_index']==player['life_index']
           for d in state['execution']['pending_deaths']):
        return None
    if any(i['kind']=='void_death_candidate' and i['payload']['player_id']==player['player_id'] and
           i['payload']['life_index']==player['life_index'] for i in state['execution']['pending_intents']):
        return None
    return player


def buy(state,definitions,tick,item):
    profile=definitions.profile.data;pid=item['player_id'];player=_valid_player(state,item)
    plan=ChangeSet.from_state(state)
    if player is None:
        _request_finish(plan,state,item,tick,'WRONG_LIFE');return plan
    shop=next(t['shop'] for t in definitions.map.data['teams'] if t['team_id']==player['team_id'])
    spatial=player['life']['spatial']
    if distance(Vec2(spatial['x'],spatial['z']),Vec2(shop['x'],shop['z']))>profile['shop']['range_blocks']:
        _request_finish(plan,state,item,tick,'OUT_OF_RANGE');return plan
    product=item['payload']['product'];quote=profile['shop']['products'][product]
    life=player['life'];inv=life['inventory'];cost=quote['cost']
    if product=='iron_sword' and inv.get('iron_sword',0) or product=='armor_1' and player['progression']['armor_tier']>=1:
        _request_finish(plan,state,item,tick,'ALREADY_OWNED');return plan
    if inv.get('iron',0)<cost:
        _request_finish(plan,state,item,tick,'INSUFFICIENT_RESOURCE');return plan
    updated=deepcopy(player);inventory=updated['life']['inventory']
    inventory['iron']-=cost
    if inventory['iron']==0:
        del inventory['iron']
    if product=='iron_sword':
        inventory.pop('wooden_sword',None)
        inventory['iron_sword']=1
    elif product=='armor_1':
        updated['progression']['armor_tier']=1
    else:
        inventory['wool']=inventory.get('wool',0)+quote['quantity']
    limits=profile['inventory']['stack_limits']
    if sum((n+limits[k]-1)//limits[k] for k,n in inventory.items())>profile['inventory']['stack_capacity']:
        _request_finish(plan,state,item,tick,'INVENTORY_FULL');return plan
    outcomes=deepcopy(state['execution']['action_outcomes'])
    oldheld=updated['life']['held_item']
    if oldheld is not None and oldheld not in inventory:
        updated['life']['held_item']=None
        work={'request_records':state['execution']['request_records'],'action_outcomes':outcomes}
        _outcome(work,pid,updated['life']['interaction'],tick,'HELD_ITEM_CHANGED')
        updated['life']['interaction']=None
        plan.execution_updates['action_outcomes']=outcomes
    plan.players[pid]=updated
    _request_finish(plan,state,item,tick,'OK')
    plan.emit(kind='item_purchased',tick=tick,phase=40,
              payload={'player_id':pid,'product':product,'cost':cost,'quantity':quote['quantity']})
    return plan


def drop(state,definitions,tick,item):
    profile=definitions.profile.data;pid=item['player_id'];player=_valid_player(state,item)
    plan=ChangeSet.from_state(state)
    if player is None:
        _request_finish(plan,state,item,tick,'WRONG_LIFE');return plan
    quantity=item['payload']['quantity'];inventory=player['life']['inventory']
    if inventory.get('iron',0)<quantity:
        _request_finish(plan,state,item,tick,'INSUFFICIENT_QUANTITY');return plan
    pos=player['life']['spatial'];terrain=Terrain.from_world(state,definitions.map.data)
    gp=profile['ground_items']
    if not terrain.safe_drop(Vec2(pos['x'],pos['z']),gp['width'],gp['depth']):
        _request_finish(plan,state,item,tick,'INVALID_TARGET');return plan
    updated=deepcopy(player);newinv=updated['life']['inventory'];newinv['iron']-=quantity
    if not newinv['iron']:
        del newinv['iron']
        if updated['life']['held_item']=='iron':
            updated['life']['held_item']=None
            outcomes=deepcopy(state['execution']['action_outcomes'])
            work={'request_records':state['execution']['request_records'],'action_outcomes':outcomes}
            _outcome(work,pid,updated['life']['interaction'],tick,'HELD_ITEM_CHANGED')
            updated['life']['interaction']=None;plan.execution_updates['action_outcomes']=outcomes
    plan.players[pid]=updated
    ids=create_ground(plan,state,definitions,tick=tick,item='iron',quantity=quantity,x=pos['x'],z=pos['z'],
                      delay=gp['drop_pickup_delay_ticks'],source={'kind':'player_drop','source_id':pid})
    _request_finish(plan,state,item,tick,'OK')
    plan.emit(kind='resource_dropped',tick=tick,phase=45,
              payload={'player_id':pid,'item':'iron','quantity':quantity,'entity_ids':ids})
    return plan
