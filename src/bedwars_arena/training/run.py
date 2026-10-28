"""Reproducible CLI training runs and paired frozen evaluation."""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from bedwars_arena.core.definitions import _read_json
from bedwars_arena.core.world_state import definition_ref, runtime_info
from bedwars_arena.agents.scripts import DefensiveCounterattacker, EconomicAttacker
from bedwars_arena.replay.record import canonical
from .checkpoint import load_checkpoint, save_checkpoint
from .encoding import ACTIONS, ACTION_VERSION, ENCODING_VERSION, FEATURE_SIZE
from .environment import training_environment
from .model import checked_parameters, parameter_hash
from .rollout import save_rollout
from .trainer import PPOTrainer


def run_training(definitions,*,output,seed=None,episode_limit_ticks=None,decision_interval=None,opponent=None,
                 preset_path=None,resume=None,episodes_per_update=2,updates=1,eval_games=2,eval_seed=1001):
    for name,value,maximum in (('episodes_per_update',episodes_per_update,100),('updates',updates,100),('eval_games',eval_games,100)):
        minimum=0 if name=='eval_games' else 1
        if type(value) is not int or not minimum<=value<=maximum:raise ValueError(f'Invalid {name}')
    if eval_games and (eval_games<2 or eval_games%2):raise ValueError('Evaluation needs an even number of games to swap teams')
    if type(eval_seed) is not int or not 0<=eval_seed<2**64 or eval_seed+eval_games>2**64:
        raise ValueError('Evaluation seeds must fit in uint64')
    requested_preset=None if preset_path is None else _read_json(Path(preset_path))
    if resume is not None:
        trainer=load_checkpoint(resume,definitions)
        requested={'seed':seed,'episode_limit_ticks':episode_limit_ticks,'decision_interval':decision_interval,'opponent':opponent}
        for name,value in requested.items():
            if value is not None and getattr(trainer,name)!=value:raise ValueError(f'Resume {name} differs from checkpoint')
        if preset_path is not None and requested_preset!=trainer.preset:raise ValueError('Resume preset differs from checkpoint')
    else:
        trainer=PPOTrainer(definitions,seed=2026 if seed is None else seed,
                           episode_limit_ticks=definitions.profile.data['schedule']['episode_limit_ticks'] if episode_limit_ticks is None else episode_limit_ticks,
                           decision_interval=1 if decision_interval is None else decision_interval,
                           opponent='defend' if opponent is None else opponent,preset=requested_preset)
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    before=checked_parameters(trainer.parameters,readonly=True);before_hash=parameter_hash(before)
    initial_checkpoint=save_checkpoint(trainer,root/'checkpoints'/f'initial-{trainer.updates:06d}')
    update_reports=[];episode_reports=[];checkpoints=[];rollouts=[]
    for _ in range(updates):
        for _ in range(episodes_per_update):
            index=trainer.episodes+1
            episode_reports.append(trainer.collect_episode(output=root/'episodes'/f'episode-{index:06d}'))
        rollouts.append(save_rollout(trainer.pending,root/'rollouts'/f'update-{trainer.updates+1:06d}.npz'))
        result=trainer.update()
        if result['before_sha256']==result['after_sha256']:raise ValueError('PPO update did not change the model')
        update_reports.append(result)
        checkpoint=save_checkpoint(trainer,root/'checkpoints'/f'update-{trainer.updates:06d}')
        checkpoints.append(str(checkpoint.resolve()))
    evaluations=[]
    if eval_games:
        seeds=[eval_seed+i for i in range(eval_games)]
        evaluations.append(trainer.evaluate(seeds=seeds,output_root=root/'evaluation',parameters=before,label='initial'))
        evaluations.append(trainer.evaluate(seeds=seeds,output_root=root/'evaluation',label='trained'))
    report={'schema_version':1,'kind':'l1-ppo-training-run','runtime':runtime_info(),
            'definitions':definition_ref(definitions),'algorithm':'shared-linear-ppo-clip-v1',
            'training_environment':training_environment(),'device':'cpu','seed_hex':f'{trainer.seed:016x}',
            'ppo_config':asdict(trainer.config),'encoding_version':ENCODING_VERSION,
            'action_version':ACTION_VERSION,'feature_size':FEATURE_SIZE,'actions':list(ACTIONS),
            'episode_limit_ticks':trainer.episode_limit_ticks,'decision_interval':trainer.decision_interval,
            'opponent':trainer.opponent,
            'opponent_version':(EconomicAttacker if trainer.opponent=='attack' else DefensiveCounterattacker).version,
            'preset':deepcopy(trainer.preset),'preset_sha256':sha256(canonical(trainer.preset)).hexdigest(),
            'episodes_per_update':episodes_per_update,'updates_this_run':updates,'resume_from':str(Path(resume).resolve()) if resume else None,
            'initial_model_sha256':before_hash,'final_model_sha256':trainer.model_sha256,
            'total_episodes':trainer.episodes,'total_updates':trainer.updates,'optimizer_step':trainer.adam['step'],
            'episode_reports':episode_reports,'update_reports':update_reports,'evaluation':evaluations,
            'initial_checkpoint':str(initial_checkpoint.resolve()),'checkpoints':checkpoints,'rollouts':rollouts}
    (root/'training-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report
