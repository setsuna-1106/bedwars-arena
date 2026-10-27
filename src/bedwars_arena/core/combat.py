"""L1 phase-60 attack and simultaneous death batch (platform rules BW-COMBAT-01/BW-LIFE-04)."""
from copy import deepcopy

from .controls import _outcome
from .entities import capacity_for, create_ground
from .geometry import Vec2
from .legality import interaction_error
from .messages import ScheduledTask
from .physics import add_knockback
from .terrain import Terrain
from .transactions import ChangeSet


def _enemy(state,attacker,victim):
    return attacker in state['players'] and state['players'][attacker]['team_id'] != state['players'][victim]['team_id']


def _nearby_killer(state,player,tick,window):
    last=player['life']['last_attacker']
    if last is None or not 0 <= tick-last['attacked_at'] <= window:
        return None
    return last['player_id'] if _enemy(state,last['player_id'],player['player_id']) else None


def _safe(state,definitions,x,z):
    terrain=Terrain.from_world(state,definitions.map.data)
    gp=definitions.profile.data['ground_items']
    return terrain.safe_drop(Vec2(x,z),gp['width'],gp['depth'])


def resolve_damage_and_deaths(state,definitions,tick):
    """Freeze qualified attacks; apply hits in order and commit all deaths together."""
    profile=definitions.profile.data;combat=profile['combat']
    roster=[p['player_id'] for p in definitions.scenario.data['players']]
    active_intents=[i for i in state['execution']['pending_intents']
                    if i['target_phase']==60 and i['kind']=='void_death_candidate']
    voids={(i['payload']['player_id'],i['payload']['life_index']):i for i in active_intents}
    for record in state['execution']['pending_deaths']:
        voids[(record['player_id'],record['life_index'])]=record
    eligible=[]
    for pid in roster:
        player=state['players'][pid]
        if player['life']['kind']!='alive' or (pid,player['life_index']) in voids:
            continue
        action=player['life']['interaction']
        if action is None or action['kind']!='attack' or tick<player['cooldowns'].get('attack',0):
            continue
        if interaction_error(state,definitions,pid,'attack',action['params']) is None:
            eligible.append((pid,deepcopy(action['params'])))
    if not eligible and not voids:
        return None
    plan=ChangeSet.from_state(state)
    plan.consume_intents.extend(i['id'] for i in active_intents)
    if state['execution']['pending_deaths']:
        plan.execution_updates['pending_deaths']=[]
    players=deepcopy(state['players'])
    lethal={}
    for attacker_id,target_ref in eligible:
        attacker=players[attacker_id];target_id=target_ref['player_id'];target=players[target_id]
        attacker['cooldowns']['attack']=tick+combat['attack_interval_ticks']
        protected=any(e['effect_type']=='spawn_protection' and tick<e['expires_at'] for e in target['life']['effects'])
        if protected or tick<target['cooldowns'].get('hurt',0) or target['life']['vitality']['health']<=0:
            plan.emit(kind='attack_blocked',tick=tick,phase=60,
                      payload={'player_id':attacker_id,'target_player_id':target_id,
                               'reason':'protection' if protected else 'hurt_interval'})
            continue
        held=attacker['life']['held_item']
        base=combat['iron_sword_damage'] if held=='iron_sword' else combat['wooden_sword_damage']
        reduction=combat['armor_1_reduction'] if target['progression']['armor_tier']==1 else combat['base_armor_reduction']
        hp=target['life']['vitality']['health'];damage=min(hp,base*(1-reduction))
        if damage <= 0:
            continue
        target['life']['vitality']['health']=hp-damage
        target['cooldowns']['hurt']=tick+combat['hurt_interval_ticks']
        target['life']['last_attacker']={'player_id':attacker_id,'attacked_at':tick}
        a=attacker['life']['spatial'];b=target['life']['spatial']
        impulse=Vec2(b['x']-a['x'],b['z']-a['z'])
        if impulse.length()==0:
            impulse=Vec2(a['facing_x'],a['facing_z'])
        impulse=impulse.normalized()*profile['physics']['knockback_per_hit']
        knock=add_knockback(Vec2(b['knockback_x'],b['knockback_z']),impulse,profile['physics'])
        b['knockback_x']=knock.x;b['knockback_z']=knock.z
        if target['life']['vitality']['health']<=0:
            lethal[target_id]=attacker_id
        plan.emit(kind='melee_hit',tick=tick,phase=60,
                  payload={'player_id':attacker_id,'target_player_id':target_id,'damage':damage})
    dead=[]
    for pid in roster:
        player=state['players'][pid]
        if player['life']['kind']!='alive':
            continue
        void=(pid,player['life_index']) in voids
        if not void and pid not in lethal:
            continue
        killer=_nearby_killer(state,player,tick,combat['attribution_window_ticks']) if void else lethal[pid]
        bed_present=state['teams'][player['team_id']]['bed_state']['status']=='present'
        pos=player['life']['spatial']
        dead.append({'player_id':pid,'life_index':player['life_index'],'team_id':player['team_id'],
                     'killer':killer,'reason':'void' if void else 'melee','final':not bed_present,
                     'iron':player['life']['inventory'].get('iron',0),'x':pos['x'],'z':pos['z']})
    dying={entry['player_id'] for entry in dead}
    outcomes=deepcopy(state['execution']['action_outcomes'])
    execution={'request_records':state['execution']['request_records'],'action_outcomes':outcomes}
    for entry in dead:
        pid=entry['player_id'];player=players[pid]
        for channel in ('movement','interaction'):
            _outcome(execution,pid,player['life'][channel],tick,'LIFE_ENDED')
        player['cooldowns']={}
        if entry['final']:
            player['life']={'kind':'eliminated','eliminated_at':tick,'reason':'final_death'}
            player['stats']['final_deaths']+=1
        else:
            respawn_at=tick+profile['life']['respawn_delay_ticks']
            player['life']={'kind':'respawning','died_at':tick,'respawn_at':respawn_at}
            player['stats']['deaths']+=1
            plan.add_tasks.append(ScheduledTask.create(task_id=plan.allocate(),kind='respawn',created_at=tick,
                execute_at=respawn_at,phase=10,source_order=roster.index(pid),
                payload={'player_id':pid,'life_index':entry['life_index'],'respawn_at':respawn_at}))
        if entry['killer'] is not None:
            category='final_kills' if entry['final'] else 'kills'
            players[entry['killer']]['stats'][category]+=1
    for entry in dead:
        pid=entry['player_id'];killer=entry['killer'];amount=entry['iron']
        tally={'received':0,'dropped':0,'destroyed':0};ids=[]
        if amount:
            if killer is not None and killer not in dying and players[killer]['life']['kind']=='alive':
                receiver=players[killer];inv=receiver['life']['inventory']
                accepted=min(amount,capacity_for(inv,'iron',profile))
                if accepted:
                    inv['iron']=inv.get('iron',0)+accepted
                tally['received']=accepted;left=amount-accepted
                dest=receiver['life']['spatial']
                if left and _safe(state,definitions,dest['x'],dest['z']):
                    ids=create_ground(plan,state,definitions,tick=tick,item='iron',quantity=left,
                        x=dest['x'],z=dest['z'],delay=profile['ground_items']['death_pickup_delay_ticks'],
                        source={'kind':'death','source_id':pid})
                    tally['dropped']=left
                else:
                    tally['destroyed']=left
            elif killer is None and _safe(state,definitions,entry['x'],entry['z']):
                ids=create_ground(plan,state,definitions,tick=tick,item='iron',quantity=amount,
                    x=entry['x'],z=entry['z'],delay=profile['ground_items']['death_pickup_delay_ticks'],
                    source={'kind':'death','source_id':pid})
                tally['dropped']=amount
            else:
                tally['destroyed']=amount
        if sum(tally.values())!=amount:
            raise ValueError('Death resource conservation failed')
        plan.emit(kind='player_died',tick=tick,phase=60,
                  payload={'player_id':pid,'life_index':entry['life_index'],'reason':entry['reason'],
                           'killer_id':killer,'final':entry['final'],'iron':tally,'entity_ids':ids})
    plan.execution_updates['action_outcomes']=outcomes
    for pid in roster:
        if players[pid]!=state['players'][pid]:
            plan.players[pid]=players[pid]
    return plan


def respawn(state,definitions,task):
    tick=task.execute_at;payload=task.payload
    if set(payload)!={'player_id','life_index','respawn_at'}:
        raise ValueError('Invalid respawn task')
    plan=ChangeSet.from_state(state);plan.consume_tasks.append(task.task_id)
    player=state['players'].get(payload['player_id'])
    if (player is None or player['life']['kind']!='respawning' or player['life_index']!=payload['life_index'] or
            player['life']['respawn_at']!=tick or payload['respawn_at']!=tick):
        plan.diagnostics.append({'tick':tick,'phase':10,'task_id':task.task_id,'reason':'stale_life'})
        return plan
    profile=definitions.profile.data;pid=player['player_id']
    team=next(t for t in definitions.map.data['teams'] if t['team_id']==player['team_id'])
    updated=deepcopy(player);updated['life_index']+=1;updated['cooldowns']={}
    effect_id=plan.allocate();expires=tick+profile['life']['protection_duration_ticks']
    effect={'effect_id':effect_id,'effect_type':'spawn_protection','source':{'kind':'system','source_id':'spawn'},
            'level':None,'expires_at':expires,'next_trigger_at':None}
    updated['life']={'kind':'alive','spatial':{'x':team['spawn']['x'],'z':team['spawn']['z'],
        'facing_x':team['facing']['x'],'facing_z':team['facing']['z'],'velocity_x':0.0,'velocity_z':0.0,
        'knockback_x':0.0,'knockback_z':0.0},'vitality':{'health':profile['combat']['max_hp'],'absorption':0},
        'inventory':deepcopy(profile['inventory']['initial_items']),
        'held_item':profile['inventory']['initial_held_item'],'effects':[effect],
        'movement':None,'interaction':None,'last_attacker':None}
    roster=[p['player_id'] for p in definitions.scenario.data['players']]
    plan.add_tasks.append(ScheduledTask.create(task_id=plan.allocate(),kind='expire_protection',created_at=tick,
        execute_at=expires,phase=0,source_order=roster.index(pid),
        payload={'player_id':pid,'life_index':updated['life_index'],'effect_id':effect_id},
        caused_by={'category':'task','id':task.task_id}))
    plan.players[pid]=updated
    plan.emit(kind='player_respawned',tick=tick,phase=10,
              payload={'player_id':pid,'life_index':updated['life_index']},
              caused_by={'category':'task','id':task.task_id})
    return plan
