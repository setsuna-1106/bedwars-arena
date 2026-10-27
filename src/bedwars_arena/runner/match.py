"""Synchronous L1 episode runner with recorded fallback inputs and boundaries."""
from copy import deepcopy
import json
import math
from pathlib import Path
import os
import shutil
import tempfile
import time

from bedwars_arena.core.time import identifier, integer
from bedwars_arena.core.world_state import runtime_info


def _json_safe(value):
    if value is None or type(value) in (bool,str,int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {'invalid_float':repr(value)}
    if isinstance(value,list):
        return [_json_safe(x) for x in value]
    if isinstance(value,dict) and all(isinstance(k,str) for k in value):
        return {k:_json_safe(v) for k,v in value.items()}
    return {'invalid_type':type(value).__name__,'representation':repr(value)}


class MatchRunner:
    """Owns one episode, but never owns or resets cross-match learning state."""
    def __init__(self,world,policies: dict,*,decision_interval: int = 1,
                 episode_limit_ticks: int | None = None,soft_timeout_ms: int | None = None,
                 episode_source: dict | None = None):
        self.world=world
        state=world.state
        if world.fault is not None or state['result'] is not None:
            raise ValueError('An episode needs a healthy unfinished world')
        self.roster=[p['player_id'] for p in world.definitions.scenario.data['players']]
        if not isinstance(policies,dict) or set(policies)!=set(self.roster):
            raise ValueError('Exactly one policy per fixed player is required')
        if len({id(policies[pid]) for pid in self.roster}) != len(self.roster):
            raise ValueError('Each player needs an independent policy session')
        self.policies=dict(policies)
        self.decision_interval=integer(decision_interval,'decision_interval',1)
        profile=world.definitions.profile.data
        self.limit=integer(episode_limit_ticks if episode_limit_ticks is not None else
                           profile['schedule']['episode_limit_ticks'],'episode_limit_ticks',1)
        self.timeout_ms=integer(soft_timeout_ms if soft_timeout_ms is not None else
                                profile['protocol']['policy_soft_timeout_ms'],'soft_timeout_ms',1)
        self.start_tick=state['tick']
        if episode_source is None and self.start_tick:
            episode_source={'match_id':state['match_id'],'tick':self.start_tick,'kind':'resumed_boundary'}
        self.episode_source=deepcopy(episode_source)
        self.identities={}
        for pid,policy in self.policies.items():
            name=getattr(policy,'name',None);version=getattr(policy,'version',None)
            identifier(name,'policy name');identifier(version,'policy version')
            if not callable(getattr(policy,'act',None)):
                raise ValueError('Each policy must implement act')
            self.identities[pid]={'name':name,'version':version}
        self.inputs=[];self.events=list(world.initial_facts) if state['tick']==0 else []
        self.definition_data={name:getattr(world.definitions,name).data for name in ('profile','map','scenario')}
        self.initial_snapshot=world.snapshot();self.snapshots=[]
        self.terminated=False;self.truncated=False;self.failure=None;self._closed=False
        self._startup_errors={}
        self._end_errors=[]
        for pid in self.roster:
            callback=getattr(self.policies[pid],'on_start',None)
            if callable(callback):
                try:
                    callback({'match_id':state['match_id'],'player_id':pid,
                              'team_id':state['players'][pid]['team_id'],
                              'definitions':deepcopy(state['definition_ref'])})
                except Exception as error:
                    self._startup_errors[pid]=f'{type(error).__name__}: {error}'

    def _fallback(self,pid,round_id,reason):
        return [{'request_id':f'{round_id}-{pid}-fallback-m','kind':'cancel','payload':{'channel':'movement'}},
                {'request_id':f'{round_id}-{pid}-fallback-i','kind':'cancel','payload':{'channel':'interaction'}}]

    def _close(self):
        if self._closed: return
        self._closed=True
        rewards=self.rewards()
        for pid in self.roster:
            callback=getattr(self.policies[pid],'on_end',None)
            if callable(callback):
                try:
                    callback({'player_id':pid,'reward':rewards[pid],
                              'terminated':self.terminated,'truncated':self.truncated,
                              'result':deepcopy(self.world.state['result'])})
                except Exception as error:
                    self._end_errors.append({'player_id':pid,'error':f'{type(error).__name__}: {error}'})

    def rewards(self):
        state=self.world.state;result=state['result'];values={}
        for pid in self.roster:
            if result is None or result['kind']=='draw': values[pid]=0
            else: values[pid]=1 if state['players'][pid]['team_id']==result['winner_team_id'] else -1
        return values

    def decision_step(self):
        if self.terminated or self.truncated or self.failure is not None:
            raise ValueError('Episode is already finished')
        try:
            state=self.world.state
            current=state['execution']['round']
            resumed_sealed=(current is not None and current['observed_tick']==state['tick'] and current['sealed'])
            if current is not None and current['observed_tick']==state['tick'] and not current['sealed']:
                raise ValueError('Cannot resume an unsealed decision round')
            if not resumed_sealed:
                round_id=f"round-{state['tick']}"
                self.world.open_round(round_id)
                observations={pid:self.world.observe(pid) for pid in self.roster
                              if state['players'][pid]['life']['kind']=='alive'}
                decisions={}
                for pid,observation in observations.items():
                    policy=self.policies[pid]
                    if getattr(policy,'version',None)!=self.identities[pid]['version']:
                        raise ValueError(f'Policy version changed during episode: {pid}')
                    reason=None;detail=None;raw=None
                    if pid in self._startup_errors:
                        reason='startup_error';detail=self._startup_errors[pid]
                    else:
                        start=time.perf_counter()
                        try:
                            raw=policy.act(deepcopy(observation))
                            elapsed=(time.perf_counter()-start)*1000
                            if elapsed>self.timeout_ms:
                                reason='soft_timeout';detail=f'{elapsed:.3f} ms'
                            elif not isinstance(raw,list):
                                reason='missing_or_malformed_packet';detail=type(raw).__name__
                        except Exception as error:
                            reason='policy_exception';detail=f'{type(error).__name__}: {error}'
                    requests=self._fallback(pid,round_id,reason) if reason else raw
                    decisions[pid]={'requests':requests,'raw':raw,'fallback':reason,'detail':detail}
                packets=[]
                for pid in self.roster:
                    if pid not in decisions: continue
                    player=state['players'][pid];decision=decisions[pid]
                    packets.append({'protocol_version':1,'match_id':state['match_id'],'player_id':pid,
                                    'decision_round_id':round_id,'observed_tick':state['tick'],
                                    'life_index':player['life_index'],'requests':decision['requests']})
                receipts=self.world.receive_actions_batch(packets)
                submitted=set(self.world.state['execution']['round']['submitted'])
                for packet,receipt in zip(packets,receipts):
                    pid=packet['player_id'];decision=decisions[pid]
                    original_requests=_json_safe(decision['raw']);initial_receipt=deepcopy(receipt)
                    if receipt['packet_errors'] and pid not in submitted:
                        decision['fallback']='malformed_packet'
                        decision['detail']=str(receipt['packet_errors'])
                        packet['requests']=self._fallback(pid,round_id,'malformed_packet')
                        receipt=self.world.receive_actions(packet)
                    self.inputs.append({'observed_tick':state['tick'],'player_id':pid,'round_id':round_id,
                                        'original_requests':original_requests,'initial_receipt':_json_safe(initial_receipt),
                                        'packet':_json_safe(packet),'receipt':_json_safe(receipt),
                                        'fallback':decision['fallback'],'detail':decision['detail']})
                self.world.seal_round()
            for _ in range(self.decision_interval):
                self.world.step()
                self.events.extend(self.world.last_facts)
                state=self.world.state
                interval=self.world.definitions.profile.data['budget']['snapshot_interval_ticks']
                if state['tick']%interval==0:
                    self.snapshots.append(self.world.snapshot())
                self.terminated=state['result'] is not None
                self.truncated=state['tick']-self.start_tick>=self.limit
                if self.terminated or self.truncated:
                    self._close();break
        except Exception as error:
            self.failure={'type':type(error).__name__,'message':str(error),'tick':self.world.state['tick']}
            self._close()
            raise
        return self.summary()

    def run(self):
        while not (self.terminated or self.truncated):
            self.decision_step()
        return self.summary()

    def summary(self):
        state=self.world.state
        return {'match_id':state['match_id'],'start_tick':self.start_tick,'tick':state['tick'],
                'terminated':self.terminated,'truncated':self.truncated,'result':deepcopy(state['result']),
                'rewards':self.rewards(),'failure':deepcopy(self.failure)}

    def manifest(self):
        return {'schema_version':1,'kind':'l1-run-manifest','runtime':runtime_info(),
                'definitions':deepcopy(self.initial_snapshot['definition_ref']),
                'match_id':self.world.state['match_id'],'seed_hex':self.initial_snapshot['state']['execution']['rng_seed_hex'],
                'roster':deepcopy(self.identities),'decision_interval':self.decision_interval,
                'episode_start_tick':self.start_tick,'episode_limit_ticks':self.limit,
                'episode_source':deepcopy(self.episode_source),'soft_timeout_ms':self.timeout_ms,
                'summary':self.summary(),'policy_start_errors':deepcopy(self._startup_errors),
                'policy_end_errors':deepcopy(self._end_errors),
                'input_count':len(self.inputs),'fact_count':len(self.events),
                'snapshot_ticks':[s['state']['tick'] for s in self.snapshots]}

    def write_artifacts(self,directory):
        """Publish the complete record directory only after every file is written."""
        target=Path(directory)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            raise FileExistsError(f'Run directory already exists: {target}')
        staging=Path(tempfile.mkdtemp(prefix=f'.{target.name}-',dir=target.parent))
        try:
            def write(name,value):
                (staging/name).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            write('manifest.json',self.manifest())
            write('definitions.json',self.definition_data)
            write('initial-snapshot.json',self.initial_snapshot)
            write('final-snapshot.json',self.world.snapshot())
            for name,items in (('inputs.jsonl',self.inputs),('events.jsonl',self.events)):
                with (staging/name).open('w',encoding='utf-8') as out:
                    for item in items:
                        out.write(json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
            if self.snapshots:
                (staging/'snapshots').mkdir()
                for snapshot in self.snapshots:
                    name=f"{snapshot['state']['tick']:08d}.json"
                    (staging/'snapshots'/name).write_text(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,
                        separators=(',',':'),allow_nan=False)+'\n',encoding='utf-8')
            if target.exists():
                raise FileExistsError(f'Run directory already exists: {target}')
            os.rename(staging,target)
        except Exception:
            shutil.rmtree(staging,ignore_errors=True)
            raise
        return target
