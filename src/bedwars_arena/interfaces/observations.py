"""L1 full-information observations, detached from engine and other players."""
from copy import deepcopy


def _public_action(action):
    if action is None:
        return None
    return {'kind':action['kind'],'target':deepcopy(action['target']),'progress':action['progress']}


def feedback(state,player_id):
    if player_id not in state['players']:
        raise ValueError('Unknown player')
    execution=state['execution']
    return {'protocol_version':1,'match_id':state['match_id'],'player_id':player_id,
            'published_tick':state['tick'],
            'request_results':[deepcopy(x['result']) for _,x in sorted(execution['request_records'].get(player_id,{}).items())],
            'packet_errors':deepcopy(execution['packet_errors'].get(player_id,[])),
            'action_outcomes':deepcopy(execution['action_outcomes'].get(player_id,[]))}


def observe(state,definitions,player_id):
    if player_id not in state['players']:
        raise ValueError('Unknown player')
    current=state['execution']['round']
    if current is None or current['observed_tick']!=state['tick']:
        raise ValueError('Open a decision round for this boundary first')
    profile=definitions.profile.data
    map_data=definitions.map.data
    terrain=[]
    for key,block in sorted(state['terrain'].items()):
        x,y,z=map(int,key.split(','))
        item={'x':x,'z':z,'layer':'bridge' if y==-1 else 'wall','kind':block['kind']}
        if block['kind'] != 'original':
            item['instance_id']=block['instance_id']
        terrain.append(item)
    players=[]
    for entry in definitions.scenario.data['players']:
        player=state['players'][entry['player_id']]
        value={'player_id':player['player_id'],'team_id':player['team_id'],
               'life_index':player['life_index'],'life':player['life']['kind'],
               'stats':deepcopy(player['stats'])}
        life=player['life']
        if life['kind']=='alive':
            spatial=life['spatial']
            value.update(position={'x':spatial['x'],'z':spatial['z']},
                         facing={'x':spatial['facing_x'],'z':spatial['facing_z']},
                         velocity={'x':spatial['velocity_x'],'z':spatial['velocity_z']},
                         knockback={'x':spatial['knockback_x'],'z':spatial['knockback_z']},
                         health=life['vitality']['health'],max_health=profile['combat']['max_hp'],
                         armor_tier=player['progression']['armor_tier'],held_item=life['held_item'],
                         inventory=deepcopy(life['inventory']),
                         movement=_public_action(life['movement']),interaction=_public_action(life['interaction']),
                         cooldowns={name:max(0,at-state['tick']) for name,at in player['cooldowns'].items()},
                         protection_remaining=max([0]+[e['expires_at']-state['tick'] for e in life['effects']
                                                       if e['effect_type']=='spawn_protection']))
        elif life['kind']=='respawning':
            value['respawn_remaining']=max(0,life['respawn_at']-state['tick'])
        else:
            value.update(eliminated_at=life['eliminated_at'],reason=life['reason'])
        players.append(value)
    teams=[]
    for team in map_data['teams']:
        team_id=team['team_id']
        members=[p['player_id'] for p in players if p['team_id']==team_id]
        teams.append({'team_id':team_id,'members':members,'bed':deepcopy(state['teams'][team_id]['bed_state']),
                      'active':any(p['life']!='eliminated' for p in players if p['team_id']==team_id),
                      'attributed_enemy_beds':state['execution']['attributed_beds'][team_id]})
    return {'protocol_version':1,'match_id':state['match_id'],'decision_round_id':current['id'],
            'observed_tick':state['tick'],'self_player_id':player_id,
            'definitions':deepcopy(state['definition_ref']),
            'terrain':{'bounds':deepcopy(map_data['bounds']),'blocks':terrain,
                       'beds':[{'team_id':t['team_id'],'x':t['bed']['x'],'z':t['bed']['z']} for t in map_data['teams']]},
            'teams':teams,'players':players,'ground_items':deepcopy(list(state['entities'].values())),
            'generators':[{'generator_id':g['generator_id'],'next_spawn_at':g['next_spawn_at']}
                          for g in state['generators'].values()],
            'schedule':deepcopy(profile['schedule']),'feedback':feedback(state,player_id)}
