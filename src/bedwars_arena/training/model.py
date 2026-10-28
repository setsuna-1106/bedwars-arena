"""CPU NumPy implementation of clipped PPO with a shared linear actor/critic."""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import numpy as np

from .encoding import ACTIONS, FEATURE_SIZE

MODEL_VERSION='l1-shared-linear-ppo-v1'


@dataclass(frozen=True)
class PPOConfig:
    learning_rate: float = 0.0003
    clip_ratio: float = 0.2
    value_coefficient: float = 0.5
    entropy_coefficient: float = 0.001
    max_gradient_norm: float = 0.5
    epochs: int = 4
    minibatch_size: int = 64
    gamma_per_tick: float = 0.995
    gae_lambda_per_tick: float = 0.95

    def __post_init__(self):
        numeric=(self.learning_rate,self.clip_ratio,self.value_coefficient,self.entropy_coefficient,
                 self.max_gradient_norm,self.gamma_per_tick,self.gae_lambda_per_tick)
        if any(type(x) not in (float,int) or not np.isfinite(x) for x in numeric):raise ValueError('PPO values must be finite')
        if not (0<self.learning_rate<=1 and 0<self.clip_ratio<1 and self.value_coefficient>=0 and
                self.entropy_coefficient>=0 and self.max_gradient_norm>0 and 0<self.gamma_per_tick<=1 and
                0<self.gae_lambda_per_tick<=1):raise ValueError('PPO values are out of range')
        if type(self.epochs) is not int or not 1<=self.epochs<=100 or type(self.minibatch_size) is not int or not 1<=self.minibatch_size<=65536:
            raise ValueError('Invalid PPO epochs/minibatch')


def parameter_shapes():
    return {'actor_w':(FEATURE_SIZE,len(ACTIONS)),'actor_b':(len(ACTIONS),),
            'value_w':(FEATURE_SIZE,), 'value_b':(1,)}


def initial_parameters(rng):
    values={'actor_w':rng.normal(0,0.002,parameter_shapes()['actor_w']),
            'actor_b':np.zeros(parameter_shapes()['actor_b'],dtype=np.float64),
            'value_w':rng.normal(0,0.002,parameter_shapes()['value_w']),
            'value_b':np.zeros(parameter_shapes()['value_b'],dtype=np.float64)}
    # Explicit experimental initialization makes nearby combat sampleable in a small budget.
    values['actor_b'][ACTIONS.index('attack_nearest')]=4.0
    return values


def checked_parameters(values, *, readonly=False):
    if not isinstance(values,dict) or set(values)!=set(parameter_shapes()):raise ValueError('Invalid model parameter names')
    result={}
    for name,shape in parameter_shapes().items():
        array=np.asarray(values[name])
        if array.shape!=shape or array.dtype!=np.float64 or not np.isfinite(array).all():
            raise ValueError(f'Invalid model parameter {name}')
        array=np.array(array,dtype=np.float64,copy=True)
        if readonly:array.flags.writeable=False
        result[name]=array
    return result


def parameter_hash(values):
    checked=checked_parameters(values)
    h=sha256()
    for name in sorted(checked):
        a=checked[name];h.update(name.encode('ascii')+b'\0');h.update(a.astype('<f8',copy=False).tobytes(order='C'))
    return h.hexdigest()


def distribution(values,features,mask):
    x=np.asarray(features,dtype=np.float64);legal=np.asarray(mask,dtype=np.bool_)
    if x.shape!=(FEATURE_SIZE,) or legal.shape!=(len(ACTIONS),) or not legal.any() or not np.isfinite(x).all():
        raise ValueError('Invalid PPO features or mask')
    logits=x@values['actor_w']+values['actor_b']
    logits=np.where(legal,logits,-np.inf);shift=logits-np.max(logits);exps=np.exp(shift)
    probs=exps/exps.sum();value=float(x@values['value_w']+values['value_b'][0])
    if not np.isfinite(probs).all() or not np.isfinite(value):raise ValueError('Non-finite PPO output')
    return probs,value


def empty_adam():
    return {'step':0,'m':{name:np.zeros(shape,dtype=np.float64) for name,shape in parameter_shapes().items()},
            'v':{name:np.zeros(shape,dtype=np.float64) for name,shape in parameter_shapes().items()}}


def checked_adam(adam):
    if not isinstance(adam,dict) or set(adam)!={'step','m','v'} or type(adam['step']) is not int or adam['step']<0:
        raise ValueError('Invalid Adam state')
    result={'step':adam['step'],'m':checked_parameters(adam['m']),'v':checked_parameters(adam['v'])}
    if any((array<0).any() for array in result['v'].values()):raise ValueError('Negative Adam second moment')
    return result


def update_ppo(values,adam,samples,config,rng):
    """Clipped PPO loss and Adam updates; return new state without mutating inputs."""
    if not isinstance(config,PPOConfig) or not samples:raise ValueError('PPO needs a nonempty rollout')
    if any(not isinstance(s,dict) or type(s.get('action')) is not int for s in samples):
        raise ValueError('Invalid PPO rollout action type')
    x=np.asarray([s['features'] for s in samples],dtype=np.float64)
    masks=np.asarray([s['mask'] for s in samples],dtype=np.bool_)
    actions=np.asarray([s['action'] for s in samples],dtype=np.int64)
    old_logp=np.asarray([s['old_logp'] for s in samples],dtype=np.float64)
    advantages=np.asarray([s['advantage'] for s in samples],dtype=np.float64)
    targets=np.asarray([s['return'] for s in samples],dtype=np.float64)
    n=len(samples)
    if (x.shape!=(n,FEATURE_SIZE) or masks.shape!=(n,len(ACTIONS)) or actions.shape!=(n,) or
            np.any(actions<0) or np.any(actions>=len(ACTIONS)) or not masks[np.arange(n),actions].all() or
            np.any(old_logp>0) or not all(np.isfinite(a).all() for a in (x,old_logp,advantages,targets))):
        raise ValueError('Invalid PPO rollout')
    mean=float(advantages.mean());std=float(advantages.std())
    if std>1e-8:advantages=(advantages-mean)/std
    params=checked_parameters(values);optim=checked_adam(adam);rng_state=deepcopy(rng.bit_generator.state)
    initial=parameter_hash(params);losses=[];clip_fractions=[];kls=[]
    try:
        for _ in range(config.epochs):
            order=rng.permutation(n)
            for begin in range(0,n,config.minibatch_size):
                idx=order[begin:begin+config.minibatch_size];batch=x[idx];legal=masks[idx];act=actions[idx]
                advantage=advantages[idx];old=old_logp[idx];target=targets[idx];size=len(idx)
                logits=batch@params['actor_w']+params['actor_b'];logits=np.where(legal,logits,-np.inf)
                exps=np.exp(logits-np.max(logits,axis=1,keepdims=True));probs=exps/exps.sum(axis=1,keepdims=True)
                selected=np.maximum(probs[np.arange(size),act],np.finfo(np.float64).tiny)
                logp=np.log(selected);ratio=np.exp(np.clip(logp-old,-60,60))
                clipped=np.clip(ratio,1-config.clip_ratio,1+config.clip_ratio)
                policy_loss=-np.minimum(ratio*advantage,clipped*advantage).mean()
                active=np.where(advantage>=0,ratio<=1+config.clip_ratio,ratio>=1-config.clip_ratio)
                onehot=np.zeros_like(probs);onehot[np.arange(size),act]=1.0
                grad_logits=-(active*advantage*ratio)[:,None]*(onehot-probs)/size
                log_probs=np.log(np.maximum(probs,np.finfo(np.float64).tiny))
                entropy=-np.sum(np.where(legal,probs*log_probs,0.0),axis=1)
                grad_logits+=config.entropy_coefficient*probs*(log_probs+entropy[:,None])/size
                value=batch@params['value_w']+params['value_b'][0];error=value-target
                gradients={'actor_w':batch.T@grad_logits,'actor_b':grad_logits.sum(axis=0),
                           'value_w':config.value_coefficient*(batch.T@error)/size,
                           'value_b':np.array([config.value_coefficient*error.mean()],dtype=np.float64)}
                norm=float(np.sqrt(sum(float(np.sum(g*g)) for g in gradients.values())))
                if not np.isfinite(norm):raise ValueError('Non-finite PPO gradient')
                if norm>config.max_gradient_norm:
                    factor=config.max_gradient_norm/norm;gradients={k:g*factor for k,g in gradients.items()}
                optim['step']+=1;t=optim['step']
                for name,g in gradients.items():
                    optim['m'][name]=0.9*optim['m'][name]+0.1*g
                    optim['v'][name]=0.999*optim['v'][name]+0.001*g*g
                    m=optim['m'][name]/(1-0.9**t);v=optim['v'][name]/(1-0.999**t)
                    params[name]-=config.learning_rate*m/(np.sqrt(v)+1e-8)
                if not all(np.isfinite(a).all() for a in params.values()):raise ValueError('Non-finite PPO parameters')
                losses.append(float(policy_loss+config.value_coefficient*0.5*np.mean(error*error)-config.entropy_coefficient*entropy.mean()))
                clip_fractions.append(float(np.mean(np.abs(ratio-1)>config.clip_ratio)))
                kls.append(float(np.mean(old-logp)))
    except Exception:
        rng.bit_generator.state=rng_state
        raise
    return params,optim,{'samples':n,'loss':float(np.mean(losses)),'clip_fraction':float(np.mean(clip_fractions)),
                         'approx_kl':float(np.mean(kls)),'advantage_mean':mean,'advantage_std':std,
                         'before_sha256':initial,'after_sha256':parameter_hash(params)}
