"""Episode-boundary trajectories and tick-aware GAE, including passive seats."""
from copy import deepcopy
from collections import Counter
from hashlib import sha256
from math import sqrt
import os
from pathlib import Path
import tempfile

from bedwars_arena.interfaces.observations import observe
from .encoding import encode_observation
from .model import distribution


def final_observation(world,player_id):
    """Build a detached public final view, without opening an actual new round."""
    state=world.state
    state['execution']['round']={'id':'ppo-final-observation','observed_tick':state['tick'],
                                 'sealed':True,'submitted':[]}
    return observe(state,world.definitions,player_id)


def trajectory(policy,world,summary,config):
    """Assign final team reward to the seat's last decision, even after elimination."""
    decisions=policy.decisions
    if not decisions:return []
    if not (summary['terminated'] or summary['truncated']):raise ValueError('Unfinished rollout')
    reward=summary['rewards'][policy.context['player_id']]
    if summary['terminated']:
        bootstrap=0.0
    else:
        features=encode_observation(final_observation(world,policy.context['player_id']))
        # A value estimate does not require the player to be able to submit an action.
        from .encoding import ACTIONS
        import numpy as np
        _,bootstrap=distribution(policy.parameters,features,np.ones(len(ACTIONS),dtype=np.bool_))
    advantage=0.0;out=[]
    for i in range(len(decisions)-1,-1,-1):
        item=decisions[i];last=i==len(decisions)-1
        next_tick=summary['tick'] if last else decisions[i+1]['tick']
        dt=next_tick-item['tick']
        if type(dt) is not int or dt<1:raise ValueError('Non-increasing decision times')
        next_value=bootstrap if last else decisions[i+1]['value']
        final_reward=reward if last and summary['terminated'] else 0
        discounted_reward=(config.gamma_per_tick**(dt-1))*final_reward
        discount=config.gamma_per_tick**dt
        delta=discounted_reward+discount*next_value-item['value']
        advantage=delta+discount*(config.gae_lambda_per_tick**dt)*advantage
        out.append({'features':item['features'],'mask':item['mask'],'action':item['action'],
                    'old_logp':item['old_logp'],'advantage':advantage,
                    'return':advantage+item['value'],'old_value':item['value'],
                    'next_value':next_value,'tick':item['tick'],'next_tick':next_tick,
                    'reward':final_reward,'terminated':bool(summary['terminated'] and last),
                    'truncated':bool(summary['truncated'] and last),
                    'match_id':policy.context['match_id'],'player_id':policy.context['player_id'],
                    'policy_version':policy.version})
    out.reverse();return out


def save_rollout(samples,path):
    """Persist the public features and PPO targets without pickle or hidden world state."""
    import numpy as np
    if not samples:raise ValueError('Cannot save an empty rollout')
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise FileExistsError(f'Rollout already exists: {target}')
    fields=('features','mask','action','old_logp','old_value','next_value','advantage','return',
            'tick','next_tick','reward','terminated','truncated','match_id','player_id','policy_version')
    arrays={key:np.asarray([s[key] for s in samples]) for key in fields}
    if any(a.dtype.hasobject for a in arrays.values()):raise ValueError('Rollout contains an object array')
    handle=tempfile.NamedTemporaryFile(prefix=f'.{target.name}-',suffix='.npz',dir=target.parent,delete=False)
    temp=Path(handle.name)
    try:
        with handle:
            np.savez_compressed(handle,**arrays)
        if target.exists():raise FileExistsError(f'Rollout already exists: {target}')
        os.rename(temp,target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return {'path':str(target.resolve()),'sha256':sha256(target.read_bytes()).hexdigest(),'samples':len(samples)}


def episode_metrics(runner,learner_team):
    state=runner.world.state;summary=runner.summary()
    roster=[p for p in state['players'].values() if p['team_id']==learner_team]
    ids={p['player_id'] for p in roster};records=state['execution']['request_records']
    statuses=Counter(e['result']['status'] for pid in ids for e in records.get(pid,{}).values())
    invalid=statuses['rejected']+statuses['failed'];total=sum(statuses.values())
    facts=runner.events
    gained=sum(e['payload']['quantity'] for e in facts if e['kind']=='item_picked_up' and
               e['payload'].get('player_id') in ids and e['payload'].get('item')=='iron')
    spent=sum(e['payload']['cost'] for e in facts if e['kind']=='item_purchased' and e['payload'].get('player_id') in ids)
    beds=sum(1 for e in facts if e['kind']=='bed_destroyed' and e['payload'].get('attacker_team_id')==learner_team)
    result=summary['result']
    outcome='truncated' if result is None else 'draw' if result['kind']=='draw' else 'win' if result['winner_team_id']==learner_team else 'loss'
    return {'match_id':summary['match_id'],'team':learner_team,'tick':summary['tick'],
            'terminated':summary['terminated'],'truncated':summary['truncated'],'outcome':outcome,
            'requests':total,'invalid_requests':invalid,'invalid_request_rate':invalid/total if total else 0.0,
            'beds_broken':beds,'final_kills':sum(p['stats']['final_kills'] for p in roster),
            'iron_picked_up':gained,'iron_spent':spent,'rewards':deepcopy(summary['rewards'])}


def wilson_interval(successes,total,z=1.959963984540054):
    if type(successes) is not int or type(total) is not int or not 0<=successes<=total:
        raise ValueError('Invalid interval count')
    if not total:return None
    p=successes/total;den=1+z*z/total;center=(p+z*z/(2*total))/den
    radius=z*sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [max(0.0,center-radius),min(1.0,center+radius)]


def evaluation_report(episodes):
    counts=Counter(x['outcome'] for x in episodes);total=len(episodes);decided=counts['win']+counts['loss']+counts['draw']
    requests=sum(x['requests'] for x in episodes);invalid=sum(x['invalid_requests'] for x in episodes)
    return {'episodes':total,'wins':counts['win'],'losses':counts['loss'],'draws':counts['draw'],
            'truncated':counts['truncated'],'decided':decided,
            'win_rate_decided':counts['win']/decided if decided else None,
            'win_rate_wilson_95':wilson_interval(counts['win'],decided),
            'confidence_note':'Wilson interval assumes independent trials; deterministic repetitions are not independent evidence.',
            'invalid_requests':invalid,'requests':requests,'invalid_request_rate':invalid/requests if requests else 0.0,
            'beds_broken':sum(x['beds_broken'] for x in episodes),
            'final_kills':sum(x['final_kills'] for x in episodes),
            'iron_picked_up':sum(x['iron_picked_up'] for x in episodes),
            'iron_spent':sum(x['iron_spent'] for x in episodes),
            'mean_length_ticks':sum(x['tick'] for x in episodes)/total if total else None,
            'matches':deepcopy(episodes)}
