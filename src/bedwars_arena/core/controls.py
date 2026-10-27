"""P3 phase-20 processing, with deterministic per-group/player ordering."""
from copy import deepcopy

from .geometry import Vec2
from .legality import interaction_error
from .transactions import ChangeSet


def _outcome(execution, player_id, action, tick, reason):
    if action is None:
        return
    for rid,entry in execution['request_records'].get(player_id,{}).items():
        if entry['result']['action_id'] == action['action_id']:
            execution['action_outcomes'].setdefault(player_id,[]).append(
                {'request_id':rid,'action_id':action['action_id'],'at_tick':tick,
                 'status':'interrupted','reason':reason})
            return


def _remove_protection(plan, player, state, tick):
    effects=player['life']['effects']
    removed=[effect for effect in effects if effect['effect_type']=='spawn_protection']
    if not removed:
        return
    ids={effect['effect_id'] for effect in removed}
    player['life']['effects']=[effect for effect in effects if effect['effect_id'] not in ids]
    for task in state['execution']['pending_tasks']:
        if task['kind']=='expire_protection' and task['payload'].get('effect_id') in ids:
            plan.cancel_tasks.append(task['id'])
    for effect in removed:
        plan.emit(kind='protection_removed',tick=tick,phase=20,
                  payload={'player_id':player['player_id'],'life_index':player['life_index'],
                           'effect_id':effect['effect_id']})


def process_controls(state,definitions,tick):
    due=[item for item in state['execution']['pending_requests'] if item['tick']==tick and item['phase']==20]
    if not due:
        return None
    plan=ChangeSet.from_state(state)
    work=deepcopy(state)
    execution=work['execution']
    order={item['player_id']:index for index,item in enumerate(definitions.scenario.data['players'])}
    priority={'turn':0,'select_item':1,'movement':2,'interaction':3}
    due.sort(key=lambda item:(priority[item['group']],order[item['player_id']],item['request_id']))
    for item in due:
        pid=item['player_id'];rid=item['request_id'];kind=item['kind'];payload=item['payload']
        player=work['players'][pid]
        entry=execution['request_records'][pid][rid]['result']
        reason='OK';action_id=None
        if (player['life']['kind']!='alive' or player['life_index']!=item['life_index'] or
                any(d['player_id']==pid and d['life_index']==item['life_index'] for d in execution['pending_deaths'])):
            reason='WRONG_LIFE'
        else:
            life=player['life']
            if kind=='turn':
                facing=Vec2(payload['x'],payload['z']).normalized()
                if (life['spatial']['facing_x'],life['spatial']['facing_z'])==(facing.x,facing.z):
                    reason='NO_CHANGE'
                else:
                    life['spatial']['facing_x']=facing.x;life['spatial']['facing_z']=facing.z
            elif kind=='select_item':
                target=payload['item']
                if target not in life['inventory']:
                    reason='ITEM_NOT_HELD'
                elif life['held_item']==target:
                    reason='NO_CHANGE'
                else:
                    _outcome(execution,pid,life['interaction'],tick,'HELD_ITEM_CHANGED')
                    life['interaction']=None
                    life['held_item']=target
            elif kind=='cancel':
                channel=payload['channel']
                old=life[channel]
                if old is None:
                    reason='NO_CHANGE'
                else:
                    _outcome(execution,pid,old,tick,'CANCELLED')
                    life[channel]=None
            elif kind=='move':
                direction=Vec2(payload['x'],payload['z']).normalized()
                params={'x':direction.x,'z':direction.z}
                old=life['movement']
                if old is not None and old['kind']=='move' and old['params']==params:
                    reason='NO_CHANGE'
                else:
                    _outcome(execution,pid,old,tick,'REPLACED')
                    action_id=plan.allocate()
                    life['movement']={'action_id':action_id,'kind':'move','target':None,'params':params,
                                      'started_at':tick,'progress':0,'phase':'active'}
            else:
                reason=interaction_error(work,definitions,pid,kind,payload) or 'OK'
                if reason=='OK':
                    old=life['interaction']
                    if old is not None and old['kind']==kind and old['params']==payload:
                        reason='NO_CHANGE'
                    else:
                        _outcome(execution,pid,old,tick,'REPLACED')
                        action_id=plan.allocate()
                        life['interaction']={'action_id':action_id,'kind':kind,'target':deepcopy(payload),
                                             'params':deepcopy(payload),'started_at':tick,'progress':0,'phase':'active'}
                        if kind in ('attack','break_bed'):
                            _remove_protection(plan,player,state,tick)
        status='applied' if reason in ('OK','NO_CHANGE') else 'failed'
        entry.update(status=status,reason=reason,processed_tick=tick,action_id=action_id)
        plan.players[pid]=player
    consumed={(item['player_id'],item['request_id']) for item in due}
    execution['pending_requests']=[item for item in execution['pending_requests']
                                   if (item['player_id'],item['request_id']) not in consumed]
    for key in ('request_records','pending_requests','action_outcomes'):
        plan.execution_updates[key]=execution[key]
    return plan


def interrupt_invalid_interactions(state,definitions,tick):
    """Recheck continued actions after motion; no automatic resume."""
    plan=ChangeSet.from_state(state)
    outcomes=deepcopy(state['execution']['action_outcomes'])
    work={'request_records':state['execution']['request_records'],'action_outcomes':outcomes}
    for entry in definitions.scenario.data['players']:
        pid=entry['player_id']
        player=state['players'][pid]
        if player['life']['kind'] != 'alive':
            continue
        action=player['life']['interaction']
        if action is None:
            continue
        reason=interaction_error(state,definitions,pid,action['kind'],action['params'])
        if reason is not None:
            updated=deepcopy(player)
            updated['life']['interaction']=None
            _outcome(work,pid,action,tick,'TARGET_INVALIDATED')
            plan.players[pid]=updated
    if not plan.players:
        return None
    plan.execution_updates['action_outcomes']=outcomes
    return plan
