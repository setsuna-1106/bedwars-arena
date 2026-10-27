"""L1 global bed schedule, team elimination and natural result."""
from copy import deepcopy

from .transactions import ChangeSet


def global_beds(state,task):
    plan=ChangeSet.from_state(state);plan.consume_tasks.append(task.task_id)
    if task.payload:
        raise ValueError('Invalid global bed destruction task')
    for team_id,team in state['teams'].items():
        if team['bed_state']['status']=='present':
            updated=deepcopy(team);updated['bed_state']={'status':'destroyed','destroyed_at':task.execute_at}
            plan.teams[team_id]=updated
            plan.emit(kind='bed_destroyed_globally',tick=task.execute_at,phase=50,
                      payload={'team_id':team_id},caused_by={'category':'task','id':task.task_id})
    return plan


def team_eliminations(state,definitions,tick):
    plan=ChangeSet.from_state(state)
    for team in definitions.map.data['teams']:
        tid=team['team_id'];members=[p for p in state['players'].values() if p['team_id']==tid]
        if (members and all(p['life']['kind']=='eliminated' for p in members) and
                max(p['life']['eliminated_at'] for p in members)==tick):
            plan.emit(kind='team_eliminated',tick=tick,phase=70,payload={'team_id':tid})
    return plan if plan.facts else None


def _active(state,definitions):
    return [team['team_id'] for team in definitions.map.data['teams']
            if any(p['team_id']==team['team_id'] and p['life']['kind']!='eliminated'
                   for p in state['players'].values())]


def _result(plan,*,tick,kind,winner,reason,caused_by=None):
    plan.result={'kind':kind,'winner_team_id':winner,'reason':reason,'tick':tick}
    plan.emit(kind='match_finished',tick=tick,phase=90,payload=deepcopy(plan.result),caused_by=caused_by)


def natural_outcome(state,definitions,tick):
    if state['result'] is not None:
        return None
    active=_active(state,definitions)
    if len(active)>=2:
        return None
    plan=ChangeSet.from_state(state)
    if active:
        _result(plan,tick=tick,kind='win',winner=active[0],reason='elimination')
    else:
        _result(plan,tick=tick,kind='draw',winner=None,reason='mutual_elimination')
    return plan


def game_end(state,definitions,task):
    plan=ChangeSet.from_state(state);plan.consume_tasks.append(task.task_id)
    if task.payload:
        raise ValueError('Invalid game-end task')
    tick=task.execute_at
    if state['result'] is not None:
        plan.diagnostics.append({'tick':tick,'phase':90,'task_id':task.task_id,'reason':'already_decided'})
        return plan
    active=_active(state,definitions)
    if len(active)<2:
        raise ValueError('Natural outcome should settle before Game End')
    scores={team_id:(sum(p['team_id']==team_id and p['life']['kind']!='eliminated' for p in state['players'].values()),
                     state['execution']['attributed_beds'][team_id]) for team_id in active}
    best=max(scores.values());winners=[team_id for team_id in active if scores[team_id]==best]
    _result(plan,tick=tick,kind='win' if len(winners)==1 else 'draw',
            winner=winners[0] if len(winners)==1 else None,reason='game_end',
            caused_by={'category':'task','id':task.task_id})
    return plan
