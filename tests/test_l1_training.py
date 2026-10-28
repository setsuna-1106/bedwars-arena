"""P8 PPO math, public adapters, trajectory semantics and resumable training."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HAS_NUMPY=importlib.util.find_spec('numpy') is not None
if HAS_NUMPY:
    import numpy as np
    from bedwars_arena.core.definitions import load_l1_definitions
    from bedwars_arena.core.world import WorldEngine
    from bedwars_arena.interfaces.actions import request_error
    from bedwars_arena.training.checkpoint import load_checkpoint, save_checkpoint
    from bedwars_arena.training.encoding import ACTIONS, FEATURE_SIZE, action_mask, decode_action, encode_observation
    from bedwars_arena.training.model import PPOConfig, distribution, empty_adam, initial_parameters, parameter_hash, update_ppo
    from bedwars_arena.training.policy import PPOPolicy
    from bedwars_arena.training.rollout import trajectory
    from bedwars_arena.training.trainer import PPOTrainer


@unittest.skipUnless(HAS_NUMPY,'NumPy is an optional training dependency')
class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defs=load_l1_definitions()
        cls.preset={'source':'test-ppo-2v2','beds':{'blue':False},'players':{
            'red_1':{'x':-25,'z':2,'armor_tier':1,'protection_ticks':0},
            'red_2':{'x':-25,'z':2,'armor_tier':1,'protection_ticks':0},
            'blue_1':{'x':-23,'z':2,'health':4,'protection_ticks':0},
            'blue_2':{'x':-23,'z':2,'health':4,'protection_ticks':0}}}
    def trainer(self):return PPOTrainer(self.defs,seed=2026,episode_limit_ticks=80,preset=self.preset)
    def observation(self):
        w=WorldEngine.create(self.defs,seed=1,match_id='ppo-test',preset=self.preset)
        w.open_round('round-0');return w.observe('red_1')

    def test_public_encoding_and_discrete_actions_are_well_formed(self):
        obs=self.observation();original=deepcopy(obs)
        x=encode_observation(obs);mask=action_mask(obs)
        self.assertEqual(x.shape,(FEATURE_SIZE,));self.assertTrue(np.isfinite(x).all())
        self.assertEqual(mask.shape,(len(ACTIONS),));self.assertTrue(mask[ACTIONS.index('hold')])
        self.assertTrue(mask[ACTIONS.index('attack_nearest')])
        changed=deepcopy(obs);changed['feedback']={'arbitrary':'private diagnostic not used'}
        np.testing.assert_array_equal(x,encode_observation(changed))
        for i in np.flatnonzero(mask):
            for req in decode_action(obs,int(i)):self.assertIsNone(request_error(req))
        self.assertEqual(obs,original)
        with self.assertRaises(ValueError):decode_action(obs,len(ACTIONS))
        self.assertEqual(decode_action(obs,ACTIONS.index('attack_nearest'))[0]['payload']['player_id'],'blue_1')

    def test_ppo_clips_the_surrogate_and_updates_within_clip(self):
        rng=np.random.default_rng(9);params=initial_parameters(rng)
        for a in params.values():a.fill(0)
        features=np.zeros(FEATURE_SIZE);features[0]=1
        mask=np.zeros(len(ACTIONS),dtype=np.bool_);mask[:2]=True
        config=PPOConfig(epochs=1,minibatch_size=1,value_coefficient=0,entropy_coefficient=0)
        row={'features':features,'mask':mask,'action':0,'old_logp':float(np.log(0.25)),
             'advantage':1.0,'return':0.0}
        before=parameter_hash(params);new,adam,metrics=update_ppo(params,empty_adam(),[row],config,rng)
        self.assertEqual(parameter_hash(new),before)
        self.assertAlmostEqual(metrics['loss'],-1.2)
        row['old_logp']=float(np.log(0.8));row['advantage']=-1.0
        new,_,metrics=update_ppo(params,empty_adam(),[row],config,rng)
        self.assertEqual(parameter_hash(new),before)
        self.assertAlmostEqual(metrics['loss'],0.8)
        row['advantage']=1.0
        row['old_logp']=float(np.log(0.5))
        new,adam,metrics=update_ppo(params,empty_adam(),[row],config,rng)
        self.assertGreater(distribution(new,features,mask)[0][0],0.5)
        self.assertEqual(adam['step'],1)
        self.assertNotEqual(metrics['before_sha256'],metrics['after_sha256'])

    def test_invalid_rollout_does_not_mutate_model_optimizer_or_rng(self):
        rng=np.random.default_rng(3);params=initial_parameters(rng);adam=empty_adam()
        before=parameter_hash(params);state=deepcopy(rng.bit_generator.state)
        row={'features':np.zeros(FEATURE_SIZE),'mask':np.ones(len(ACTIONS),dtype=np.bool_),
             'action':0,'old_logp':-1.0,'advantage':float('nan'),'return':0.0}
        with self.assertRaisesRegex(ValueError,'Invalid PPO rollout'):
            update_ppo(params,adam,[row],PPOConfig(),rng)
        self.assertEqual(parameter_hash(params),before);self.assertEqual(adam['step'],0)
        self.assertEqual(rng.bit_generator.state,state)

    def test_tick_aware_passive_reward_and_truncation_bootstrap(self):
        class Session:pass
        session=Session();session.context={'player_id':'red_1','match_id':'m'};session.version='v1';session.parameters={}
        sample={'features':np.zeros(FEATURE_SIZE),'mask':np.ones(len(ACTIONS),dtype=np.bool_),
                'action':0,'old_logp':-1.0}
        session.decisions=[{**sample,'tick':0,'value':0.2},{**sample,'tick':2,'value':0.3}]
        config=PPOConfig(gamma_per_tick=0.9,gae_lambda_per_tick=1.0)
        summary={'tick':3,'terminated':True,'truncated':False,'rewards':{'red_1':1}}
        rows=trajectory(session,None,summary,config)
        self.assertAlmostEqual(rows[0]['return'],0.9**2)
        self.assertAlmostEqual(rows[1]['return'],1.0)
        self.assertEqual(rows[-1]['reward'],1)
        session.decisions=[{**sample,'tick':0,'value':0.5}]
        summary={'tick':2,'terminated':False,'truncated':True,'rewards':{'red_1':0}}
        with patch('bedwars_arena.training.rollout.final_observation',return_value={}), \
             patch('bedwars_arena.training.rollout.encode_observation',return_value=np.zeros(FEATURE_SIZE)), \
             patch('bedwars_arena.training.rollout.distribution',return_value=(None,2.0)):
            rows=trajectory(session,None,summary,config)
        self.assertAlmostEqual(rows[0]['return'],0.9**2*2)
        summary.update(terminated=True,rewards={'red_1':1})
        self.assertAlmostEqual(trajectory(session,None,summary,config)[0]['return'],0.9)

    def test_rollout_checkpoint_restore_and_frozen_evaluation(self):
        trainer=self.trainer();start=trainer.model_sha256
        first=trainer.collect_episode();second=trainer.collect_episode()
        self.assertTrue(first['terminated']);self.assertTrue(second['terminated'])
        self.assertEqual(trainer.episodes,2);self.assertGreater(len(trainer.pending),0)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'boundary'):
                save_checkpoint(trainer,Path(root)/'too-early')
            update=trainer.update();self.assertNotEqual(update['before_sha256'],update['after_sha256'])
            self.assertNotEqual(start,trainer.model_sha256);self.assertGreater(trainer.adam['step'],0)
            rng=deepcopy(trainer.rng.bit_generator.state);frozen=trainer.model_sha256
            report=trainer.evaluate(seeds=[1001,1002])
            self.assertEqual(trainer.model_sha256,frozen);self.assertEqual(trainer.rng.bit_generator.state,rng)
            self.assertEqual([m['team'] for m in report['matches']],['red','blue'])
            self.assertTrue(all(sum(m['seat_decisions'].values())>0 for m in report['matches']))
            self.assertEqual(report['episodes'],2);self.assertEqual(len(report['win_rate_wilson_95']),2)
            path=save_checkpoint(trainer,Path(root)/'checkpoint')
            resumed=load_checkpoint(path,self.defs)
            self.assertEqual(resumed.model_sha256,trainer.model_sha256)
            self.assertEqual(resumed.adam['step'],trainer.adam['step'])
            self.assertEqual(resumed.rng.bit_generator.state,trainer.rng.bit_generator.state)
            for key in trainer.parameters:
                np.testing.assert_array_equal(resumed.parameters[key],trainer.parameters[key])
                np.testing.assert_array_equal(resumed.adam['m'][key],trainer.adam['m'][key])
                np.testing.assert_array_equal(resumed.adam['v'][key],trainer.adam['v'][key])
            with self.assertRaises(FileExistsError):save_checkpoint(trainer,path)
            left=trainer.collect_episode();right=resumed.collect_episode()
            self.assertEqual((left['tick'],left['outcome']),(right['tick'],right['outcome']))
            trainer.update();resumed.update()
            self.assertEqual(trainer.model_sha256,resumed.model_sha256)
            self.assertEqual(trainer.adam['step'],resumed.adam['step'])

    def test_fallback_seat_is_excluded_from_policy_samples(self):
        trainer=self.trainer();original=PPOPolicy.act
        def fail_one(policy,obs):
            if obs['self_player_id']=='red_1':raise RuntimeError('policy failure')
            return original(policy,obs)
        with patch.object(PPOPolicy,'act',fail_one):
            report=trainer.collect_episode()
        self.assertIn('red_1',report['excluded_fallback_seats'])
        self.assertGreater(report['policy_fallbacks'],0)
        self.assertTrue(trainer.pending)
        self.assertEqual({row['player_id'] for row in trainer.pending},{'red_2'})
        self.assertIn('red_1',report['seat_final_rewards'])

    def test_corrupt_checkpoint_and_new_process_resume(self):
        trainer=self.trainer();trainer.collect_episode();trainer.collect_episode();trainer.update()
        with tempfile.TemporaryDirectory() as root:
            path=save_checkpoint(trainer,Path(root)/'checkpoint');out=Path(root)/'resumed'
            command=[sys.executable,'-m','bedwars_arena','train-l1','--resume',str(path),
                     '--episodes-per-update','1','--eval-games','0','--output',str(out),'--json']
            env=dict(os.environ,OPENBLAS_NUM_THREADS='1')
            result=subprocess.run(command,cwd=root,env=env,text=True,capture_output=True,check=True,timeout=120)
            report=json.loads(result.stdout)
            self.assertEqual(report['initial_model_sha256'],trainer.model_sha256)
            self.assertEqual((report['total_episodes'],report['total_updates']),(3,2))
            self.assertGreater(report['optimizer_step'],trainer.adam['step'])
            self.assertNotEqual(report['initial_model_sha256'],report['final_model_sha256'])
            rollout=Path(report['rollouts'][0]['path'])
            with np.load(rollout,allow_pickle=False) as data:
                self.assertEqual(len(data['action']),report['rollouts'][0]['samples'])
                self.assertIn('old_logp',data.files);self.assertIn('player_id',data.files)
            manifest_path=path/'manifest.json';original=manifest_path.read_text()
            manifest=json.loads(original);manifest['unexpected']='ignored data is not allowed'
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'manifest fields'):load_checkpoint(path,self.defs)
            manifest=json.loads(original);manifest['preset']['beds']['blue']=True
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'preset hash'):load_checkpoint(path,self.defs)
            manifest=json.loads(original);manifest['sampler_rng_state']['increment_hex']='0'*32
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'RNG increment'):load_checkpoint(path,self.defs)
            manifest_path.write_text(original)
            with (path/'parameters.npz').open('ab') as output:output.write(b'corruption')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):load_checkpoint(path,self.defs)


if __name__=='__main__':unittest.main()
