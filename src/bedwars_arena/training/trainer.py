"""Episode-level shared PPO trainer; policy sessions are frozen within each match."""
from copy import deepcopy
import time
import numpy as np

from bedwars_arena.agents.scripts import DefensiveCounterattacker, EconomicAttacker
from bedwars_arena.core.time import integer
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.runner.match import MatchRunner
from .model import PPOConfig, checked_parameters, empty_adam, initial_parameters, parameter_hash, update_ppo
from .environment import require_training_dependency
from .policy import PPOPolicy
from .rollout import episode_metrics, evaluation_report, trajectory


class PPOTrainer:
    def __init__(self,definitions,*,seed,episode_limit_ticks,decision_interval=1,opponent='defend',
                 preset=None,config=None):
        require_training_dependency()
        if type(seed) is not int or not 0<=seed<2**64:raise ValueError('Training seed must be uint64')
        if opponent not in ('attack','defend'):raise ValueError('Unknown fixed opponent')
        if preset is not None:
            WorldEngine.create(definitions,seed=0,match_id='ppo-preset-validation',preset=preset)
        self.definitions=definitions;self.seed=seed
        self.episode_limit_ticks=integer(episode_limit_ticks,'episode_limit_ticks',1)
        self.decision_interval=integer(decision_interval,'decision_interval',1)
        self.opponent=opponent;self.preset=deepcopy(preset);self.config=config or PPOConfig()
        if not isinstance(self.config,PPOConfig):raise ValueError('Invalid PPO configuration')
        self.rng=np.random.Generator(np.random.PCG64(seed));self.parameters=initial_parameters(self.rng)
        self.adam=empty_adam();self.updates=0;self.episodes=0;self.pending=[];self._in_episode=False
        self.last_update=None

    @property
    def model_sha256(self):return parameter_hash(self.parameters)

    @property
    def policy_version(self):return f'ppo-{self.updates:06d}-{self.model_sha256[:12]}'

    def _play(self,*,parameters,version,seed,learner_team,deterministic,collect,output=None):
        teams=[t['team_id'] for t in self.definitions.map.data['teams']]
        if learner_team not in teams:raise ValueError('Unknown learner team')
        frozen=checked_parameters(parameters,readonly=True);frozen_hash=parameter_hash(frozen)
        rng=np.random.Generator(np.random.PCG64(seed));world_seed=int(rng.bit_generator.random_raw())
        world=WorldEngine.create(self.definitions,seed=world_seed,preset=self.preset)
        opponent_class=EconomicAttacker if self.opponent=='attack' else DefensiveCounterattacker
        sessions={};policies={};seat_seeds={}
        for entry in self.definitions.scenario.data['players']:
            pid=entry['player_id']
            if entry['team_id']==learner_team:
                seat_seed=int(rng.bit_generator.random_raw());seat_seeds[pid]=seat_seed
                session=PPOPolicy(frozen,version=version,seed=seat_seed,
                                  deterministic=deterministic,collect=collect)
                sessions[pid]=session;policies[pid]=session
            else:policies[pid]=opponent_class()
        if len(sessions)!=2:raise ValueError('L1 PPO requires exactly two learner seats')
        runner=MatchRunner(world,policies,decision_interval=self.decision_interval,
                           episode_limit_ticks=self.episode_limit_ticks)
        start=time.perf_counter()
        try:runner.run()
        except Exception:
            if output is not None:runner.write_artifacts(output)
            raise
        elapsed=time.perf_counter()-start
        summary=runner.summary()
        if output is not None:runner.write_artifacts(output)
        if parameter_hash(frozen)!=frozen_hash or any(parameter_hash(s.parameters)!=frozen_hash for s in sessions.values()):
            raise ValueError('Frozen policy changed within an episode')
        metrics=episode_metrics(runner,learner_team)
        fallback_seats={item['player_id'] for item in runner.inputs
                        if item['fallback'] is not None and item['player_id'] in sessions}
        metrics.update({'seed_hex':f'{seed:016x}','world_seed_hex':f'{world_seed:016x}',
                        'model_sha256':frozen_hash,'policy_version':version,
                        'opponent':self.opponent,'opponent_version':opponent_class.version,
                        'wall_seconds':elapsed,'decision_interval':self.decision_interval,
                        'seat_policy_seed_hex':{pid:f'{value:016x}' for pid,value in seat_seeds.items()},
                        'policy_fallbacks':sum(1 for item in runner.inputs if item['fallback'] is not None),
                        'excluded_fallback_seats':sorted(fallback_seats),
                        'seat_decisions':{pid:s.decision_count for pid,s in sessions.items()},
                        'seat_final_rewards':{pid:summary['rewards'][pid] for pid in sessions}})
        samples=[]
        if collect:
            for pid,policy in sessions.items():
                if policy.end is None or policy.end['reward']!=summary['rewards'][pid]:
                    raise ValueError('Missing passive-seat final reward')
                # A fallback is not drawn from the PPO distribution. Do not train
                # on that seat's episode as if the policy had chosen it.
                if pid not in fallback_seats:
                    samples.extend(trajectory(policy,world,summary,self.config))
        return metrics,samples

    def collect_episode(self,*,learner_team=None,output=None):
        if self._in_episode:raise ValueError('A training episode is already active')
        team=learner_team or self.definitions.map.data['teams'][0]['team_id']
        old_rng=deepcopy(self.rng.bit_generator.state);seed=int(self.rng.bit_generator.random_raw())
        self._in_episode=True
        try:
            metrics,samples=self._play(parameters=self.parameters,version=self.policy_version,seed=seed,
                                       learner_team=team,deterministic=False,collect=True,output=output)
        except Exception:
            self.rng.bit_generator.state=old_rng
            raise
        finally:self._in_episode=False
        self.episodes+=1;self.pending.extend(samples)
        metrics['episode_index']=self.episodes;metrics['samples']=len(samples)
        return metrics

    def update(self):
        if self._in_episode:raise ValueError('Cannot update a model within an episode')
        if not self.pending:raise ValueError('No completed rollout samples')
        parameters,adam,metrics=update_ppo(self.parameters,self.adam,self.pending,self.config,self.rng)
        self.parameters=parameters;self.adam=adam;self.pending=[];self.updates+=1
        metrics.update({'update':self.updates,'episodes':self.episodes,'optimizer_step':self.adam['step']})
        self.last_update=deepcopy(metrics);return metrics

    def evaluate(self,*,seeds,output_root=None,parameters=None,label='trained'):
        if self._in_episode:raise ValueError('Cannot evaluate during an active episode')
        if not isinstance(seeds,list) or not seeds or any(type(s) is not int or not 0<=s<2**64 for s in seeds):
            raise ValueError('Evaluation seeds must be a nonempty uint64 list')
        before=self.model_sha256;rng_state=deepcopy(self.rng.bit_generator.state)
        frozen=checked_parameters(self.parameters if parameters is None else parameters,readonly=True)
        version=f'{label}-{parameter_hash(frozen)[:12]}'
        teams=[t['team_id'] for t in self.definitions.map.data['teams']];metrics=[]
        for i,seed in enumerate(seeds):
            output=None if output_root is None else output_root/f'{label}-{i+1:04d}'
            result,_=self._play(parameters=frozen,version=version,seed=seed,learner_team=teams[i%2],
                                deterministic=True,collect=False,output=output)
            metrics.append(result)
        if self.model_sha256!=before or self.rng.bit_generator.state!=rng_state:
            raise ValueError('Frozen evaluation changed training state')
        report=evaluation_report(metrics);report.update({'label':label,'model_sha256':parameter_hash(frozen)})
        return report
