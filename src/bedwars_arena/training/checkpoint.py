"""Atomic, versioned PPO checkpoints at completed episode/update boundaries."""
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
import numpy as np

from bedwars_arena.core.definitions import _bad_constant, _unique_object
from bedwars_arena.core.world_state import definition_ref, runtime_info
from bedwars_arena.agents.scripts import DefensiveCounterattacker, EconomicAttacker
from bedwars_arena.replay.record import canonical
from .encoding import ACTIONS, ACTION_VERSION, ENCODING_VERSION, FEATURE_SIZE
from .environment import training_environment
from .model import MODEL_VERSION, PPOConfig, checked_adam, checked_parameters, parameter_hash, parameter_shapes
from .trainer import PPOTrainer

CHECKPOINT_VERSION=1
MANIFEST_FIELDS={'kind','schema_version','runtime','training_environment','definitions',
                 'encoding_version','action_version','model_version','feature_size','actions','config',
                 'seed_hex','episode_limit_ticks','decision_interval','opponent','preset','preset_sha256',
                 'opponent_version','episodes','updates','optimizer_step','sampler_rng_state',
                 'model_sha256','policy_version','last_update','files'}


def _sha(path):return sha256(path.read_bytes()).hexdigest()


def _rng_to_json(state):
    return {'bit_generator':'PCG64','state_hex':f"{state['state']['state']:032x}",
            'increment_hex':f"{state['state']['inc']:032x}",
            'has_uint32':state['has_uint32'],'uinteger':state['uinteger']}


def _rng_from_json(value):
    if (not isinstance(value,dict) or set(value)!={'bit_generator','state_hex','increment_hex','has_uint32','uinteger'} or
            value['bit_generator']!='PCG64'):
        raise ValueError('Invalid sampler RNG state')
    for key in ('state_hex','increment_hex'):
        if not isinstance(value[key],str) or len(value[key])!=32 or any(c not in '0123456789abcdef' for c in value[key]):
            raise ValueError('Invalid sampler RNG integer')
    if int(value['increment_hex'],16)%2!=1:raise ValueError('Invalid sampler RNG increment')
    if type(value['has_uint32']) is not int or value['has_uint32'] not in (0,1) or type(value['uinteger']) is not int or not 0<=value['uinteger']<2**32:
        raise ValueError('Invalid sampler RNG buffer')
    return {'bit_generator':'PCG64','state':{'state':int(value['state_hex'],16),'inc':int(value['increment_hex'],16)},
            'has_uint32':value['has_uint32'],'uinteger':value['uinteger']}


def save_checkpoint(trainer,directory):
    if not isinstance(trainer,PPOTrainer) or trainer._in_episode or trainer.pending:
        raise ValueError('Checkpoint requires an episode boundary after updating the rollout')
    target=Path(directory);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise FileExistsError(f'Checkpoint already exists: {target}')
    staging=Path(tempfile.mkdtemp(prefix=f'.{target.name}-',dir=target.parent))
    try:
        params=checked_parameters(trainer.parameters);adam=checked_adam(trainer.adam)
        np.savez(staging/'parameters.npz',**params)
        np.savez(staging/'optimizer.npz',**{f'{kind}_{name}':array for kind in ('m','v') for name,array in adam[kind].items()})
        metadata={'kind':'l1-ppo-checkpoint','schema_version':CHECKPOINT_VERSION,'runtime':runtime_info(),
                  'training_environment':training_environment(),'definitions':definition_ref(trainer.definitions),
                  'encoding_version':ENCODING_VERSION,'action_version':ACTION_VERSION,'model_version':MODEL_VERSION,
                  'feature_size':FEATURE_SIZE,'actions':list(ACTIONS),'config':asdict(trainer.config),
                  'seed_hex':f'{trainer.seed:016x}','episode_limit_ticks':trainer.episode_limit_ticks,
                  'decision_interval':trainer.decision_interval,'opponent':trainer.opponent,'preset':trainer.preset,
                  'preset_sha256':sha256(canonical(trainer.preset)).hexdigest(),
                  'opponent_version':(EconomicAttacker if trainer.opponent=='attack' else DefensiveCounterattacker).version,
                  'episodes':trainer.episodes,'updates':trainer.updates,'optimizer_step':adam['step'],
                  'sampler_rng_state':_rng_to_json(trainer.rng.bit_generator.state),'model_sha256':parameter_hash(params),
                  'policy_version':trainer.policy_version,'last_update':trainer.last_update,
                  'files':{'parameters.npz':_sha(staging/'parameters.npz'),'optimizer.npz':_sha(staging/'optimizer.npz')}}
        (staging/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        if target.exists():raise FileExistsError(f'Checkpoint already exists: {target}')
        os.rename(staging,target)
    except Exception:
        shutil.rmtree(staging,ignore_errors=True)
        raise
    return target


def load_checkpoint(directory,definitions):
    root=Path(directory)
    try:
        metadata=json.loads((root/'manifest.json').read_text(encoding='utf-8'),
                            object_pairs_hook=_unique_object,parse_constant=_bad_constant)
    except (OSError,UnicodeError,ValueError) as error:raise ValueError('Invalid checkpoint manifest') from error
    if not isinstance(metadata,dict) or set(metadata)!=MANIFEST_FIELDS:
        raise ValueError('Invalid checkpoint manifest fields')
    if metadata.get('kind')!='l1-ppo-checkpoint' or type(metadata.get('schema_version')) is not int or metadata['schema_version']!=CHECKPOINT_VERSION:
        raise ValueError('Unsupported checkpoint version')
    if metadata.get('runtime')!=runtime_info() or metadata.get('training_environment')!=training_environment():
        raise ValueError('Checkpoint runtime or training environment mismatch')
    if metadata.get('definitions')!=definition_ref(definitions):raise ValueError('Checkpoint definition mismatch')
    if metadata.get('preset_sha256')!=sha256(canonical(metadata.get('preset'))).hexdigest():
        raise ValueError('Checkpoint preset hash mismatch')
    if (metadata.get('encoding_version')!=ENCODING_VERSION or metadata.get('action_version')!=ACTION_VERSION or
        metadata.get('model_version')!=MODEL_VERSION or metadata.get('feature_size')!=FEATURE_SIZE or
        metadata.get('actions')!=list(ACTIONS)):
        raise ValueError('Checkpoint encoding/model mismatch')
    if metadata.get('opponent') not in ('attack','defend') or metadata.get('opponent_version')!=(
            EconomicAttacker if metadata['opponent']=='attack' else DefensiveCounterattacker).version:
        raise ValueError('Checkpoint opponent version mismatch')
    files=metadata.get('files')
    if not isinstance(files,dict) or set(files)!={'parameters.npz','optimizer.npz'}:
        raise ValueError('Invalid checkpoint files')
    try:
        for name,digest in files.items():
            if _sha(root/name)!=digest:raise ValueError(f'Checkpoint file hash mismatch: {name}')
        with np.load(root/'parameters.npz',allow_pickle=False) as data:
            if set(data.files)!=set(parameter_shapes()):raise ValueError('Invalid parameter archive')
            params=checked_parameters({name:data[name] for name in data.files})
        with np.load(root/'optimizer.npz',allow_pickle=False) as data:
            names={f'{kind}_{name}' for kind in ('m','v') for name in parameter_shapes()}
            if set(data.files)!=names:raise ValueError('Invalid optimizer archive')
            adam=checked_adam({'step':metadata['optimizer_step'],
                  **{kind:{name:data[f'{kind}_{name}'] for name in parameter_shapes()} for kind in ('m','v')}})
        if parameter_hash(params)!=metadata.get('model_sha256'):raise ValueError('Checkpoint model hash mismatch')
        config=PPOConfig(**metadata['config'])
        seed_hex=metadata['seed_hex']
        if not isinstance(seed_hex,str) or len(seed_hex)!=16 or any(c not in '0123456789abcdef' for c in seed_hex):
            raise ValueError('Invalid checkpoint seed')
        trainer=PPOTrainer(definitions,seed=int(seed_hex,16),episode_limit_ticks=metadata['episode_limit_ticks'],
                           decision_interval=metadata['decision_interval'],opponent=metadata['opponent'],
                           preset=metadata['preset'],config=config)
        for key in ('episodes','updates'):
            if type(metadata[key]) is not int or metadata[key]<0:raise ValueError('Invalid training counter')
        if (metadata['episodes']<metadata['updates'] or adam['step']<metadata['updates'] or
                (metadata['updates']==0 and adam['step']!=0)):
            raise ValueError('Inconsistent training counters')
        trainer.parameters=params;trainer.adam=adam;trainer.episodes=metadata['episodes'];trainer.updates=metadata['updates']
        trainer.last_update=metadata['last_update'];trainer.rng.bit_generator.state=_rng_from_json(metadata['sampler_rng_state'])
        if trainer.policy_version!=metadata['policy_version']:raise ValueError('Checkpoint policy version mismatch')
        return trainer
    except (OSError,KeyError,TypeError,OverflowError) as error:raise ValueError(f'Invalid PPO checkpoint: {error}') from error
