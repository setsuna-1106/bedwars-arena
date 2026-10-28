"""Per-seat PPO sessions using a frozen shared model and public observations."""
from copy import deepcopy
import numpy as np

from .encoding import action_mask, decode_action, encode_observation
from .model import checked_parameters, distribution, parameter_hash


class PPOPolicy:
    name='l1-shared-ppo'

    def __init__(self,parameters,*,version,seed,deterministic=False,collect=True):
        self.parameters=checked_parameters(parameters,readonly=True)
        self.version=version
        self.model_sha256=parameter_hash(self.parameters)
        self.rng=np.random.Generator(np.random.PCG64(seed))
        self.deterministic=bool(deterministic);self.collect=bool(collect)
        self.decisions=[];self.decision_count=0;self.end=None;self.context=None

    def on_start(self,context):self.context=deepcopy(context)

    def act(self,observation):
        features=encode_observation(observation);mask=action_mask(observation)
        probs,value=distribution(self.parameters,features,mask)
        action=int(np.argmax(probs)) if self.deterministic else int(self.rng.choice(len(probs),p=probs))
        self.decision_count+=1
        if self.collect:
            self.decisions.append({'tick':observation['observed_tick'],'features':features,
                                   'mask':mask,'action':action,'old_logp':float(np.log(probs[action])),
                                   'value':value})
        return decode_action(observation,action)

    def on_end(self,result):self.end=deepcopy(result)
