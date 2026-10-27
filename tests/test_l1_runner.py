"""P6 Runner boundaries, policy failure handling, lifecycle and artifacts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import subprocess
import sys
import json
import unittest

from bedwars_arena.core.definitions import load_l1_definitions, validate_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.replay.snapshot import restore_snapshot
from bedwars_arena.runner.match import MatchRunner


class Policy:
    name='test-policy';version='1'
    def __init__(self,script=None):
        self.script=script or (lambda obs:[]);self.starts=[];self.ends=[];self.calls=[]
    def on_start(self,context):self.starts.append(context)
    def act(self,observation):self.calls.append(observation['observed_tick']);return self.script(observation)
    def on_end(self,result):self.ends.append(result)


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defs=load_l1_definitions();cls.ids=('red_1','red_2','blue_1','blue_2')
    def world(self,preset=None,definitions=None):
        return WorldEngine.create(definitions or self.defs,seed=6,match_id='runner',preset=preset)
    def policies(self):return {pid:Policy() for pid in self.ids}
    def req(self,rid,kind,payload):return {'request_id':rid,'kind':kind,'payload':payload}

    def test_decision_interval_does_not_repeat_one_time_purchase(self):
        world=self.world({'players':{'red_1':{'x':-25,'z':3,'inventory':{'wooden_sword':1,'shears':1,'iron':4}}}})
        policies=self.policies()
        policies['red_1']=Policy(lambda obs:[self.req('buy-once','buy',{'product':'wool'})])
        runner=MatchRunner(world,policies,decision_interval=3,episode_limit_ticks=3)
        result=runner.run()
        self.assertEqual(result['tick'],3)
        self.assertFalse(result['terminated']);self.assertTrue(result['truncated'])
        self.assertIsNone(result['result']);self.assertTrue(all(v==0 for v in result['rewards'].values()))
        self.assertEqual(world.state['players']['red_1']['life']['inventory']['wool'],16)
        self.assertEqual(sum(f['kind']=='item_purchased' for f in runner.events),1)
        self.assertEqual(len(runner.inputs),4)
        self.assertEqual(len(policies['red_1'].calls),1)
        self.assertEqual(len(policies['red_1'].ends),1)

    def test_natural_terminal_and_limit_same_tick_sets_both_flags_and_rewards(self):
        players={}
        for pid in self.ids:
            red=pid.startswith('red')
            players[pid]={'x':-25 if red else -23,'z':2,'health':20 if red else 4,'protection_ticks':0}
        world=self.world({'players':players,'beds':{'blue':False}})
        policies=self.policies()
        for pid in ('red_1','red_2'):
            target='blue_'+pid[-1]
            policies[pid]=Policy(lambda obs,target=target:[self.req('attack','attack',{'player_id':target,'life_index':1})])
        runner=MatchRunner(world,policies,decision_interval=5,episode_limit_ticks=1)
        result=runner.run()
        self.assertEqual(result['tick'],1)
        self.assertTrue(result['terminated']);self.assertTrue(result['truncated'])
        self.assertEqual(result['result']['winner_team_id'],'red')
        self.assertEqual(result['rewards'],{'red_1':1,'red_2':1,'blue_1':-1,'blue_2':-1})
        self.assertEqual(len(policies['blue_1'].ends),1)

    def test_sealed_boundary_resumes_without_reissuing_pending_action(self):
        world=self.world({'players':{'red_1':{'x':-25,'z':3,
                      'inventory':{'wooden_sword':1,'shears':1,'iron':4}}}})
        world.open_round('prior')
        for pid in self.ids:
            requests=[self.req('buy','buy',{'product':'wool'})] if pid=='red_1' else []
            world.receive_actions({'protocol_version':1,'match_id':'runner','player_id':pid,'decision_round_id':'prior',
                'observed_tick':0,'life_index':1,'requests':requests})
        world.seal_round()
        restored=restore_snapshot(world.snapshot(),self.defs)
        policies=self.policies()
        runner=MatchRunner(restored,policies,decision_interval=2,episode_limit_ticks=2)
        runner.run()
        self.assertEqual(restored.state['players']['red_1']['life']['inventory']['wool'],16)
        self.assertEqual(sum(f['kind']=='item_purchased' for f in runner.events),1)
        self.assertTrue(all(not policy.calls for policy in policies.values()))
        self.assertEqual(runner.inputs,[])

    def test_natural_terminal_stops_before_finishing_decision_interval(self):
        players={pid:{'x':-25 if pid.startswith('red') else -23,'z':2,
                      'health':20 if pid.startswith('red') else 4,'protection_ticks':0} for pid in self.ids}
        world=self.world({'players':players,'beds':{'blue':False}})
        policies=self.policies()
        for pid in ('red_1','red_2'):
            target='blue_'+pid[-1]
            policies[pid]=Policy(lambda obs,target=target:[self.req('attack','attack',{'player_id':target,'life_index':1})])
        runner=MatchRunner(world,policies,decision_interval=5,episode_limit_ticks=10)
        result=runner.run()
        self.assertEqual(result['tick'],1)
        self.assertTrue(result['terminated']);self.assertFalse(result['truncated'])

    def test_policy_exception_and_soft_timeout_emit_recorded_cancellations(self):
        world=self.world()
        world.open_round('pre')
        for pid in self.ids:
            req=[self.req('move','move',{'x':1,'z':0})] if pid=='red_1' else []
            world.receive_actions({'protocol_version':1,'match_id':'runner','player_id':pid,'decision_round_id':'pre',
                                   'observed_tick':0,'life_index':1,'requests':req})
        world.seal_round();world.step()
        def fail(_):raise RuntimeError('policy exploded')
        def slow(_):time.sleep(0.005);return []
        policies=self.policies();policies['red_1']=Policy(fail);policies['blue_1']=Policy(slow)
        runner=MatchRunner(world,policies,episode_limit_ticks=1,soft_timeout_ms=1)
        runner.run()
        self.assertIsNone(world.state['players']['red_1']['life']['movement'])
        logged={x['player_id']:x for x in runner.inputs}
        self.assertEqual(logged['red_1']['fallback'],'policy_exception')
        self.assertEqual(logged['blue_1']['fallback'],'soft_timeout')
        for pid in ('red_1','blue_1'):
            self.assertEqual([r['payload']['channel'] for r in logged[pid]['packet']['requests']],['movement','interaction'])

    def test_missing_packet_fallback_and_resume_in_new_episode(self):
        world=self.world();policies=self.policies();policies['red_1']=Policy(lambda obs:None)
        first=MatchRunner(world,policies,episode_limit_ticks=1)
        self.assertTrue(first.run()['truncated'])
        self.assertEqual(next(i for i in first.inputs if i['player_id']=='red_1')['fallback'],'missing_or_malformed_packet')
        restored=restore_snapshot(world.snapshot(),self.defs)
        second=MatchRunner(restored,self.policies(),episode_limit_ticks=2)
        self.assertEqual(second.run()['tick'],3)
        self.assertEqual(second.manifest()['episode_source'],{'match_id':'runner','tick':1,'kind':'resumed_boundary'})

    def test_waiting_life_keeps_policy_session_and_no_action_until_respawn(self):
        profile=deepcopy(self.defs.profile.data);profile['life']['respawn_delay_ticks']=2
        defs=validate_l1_definitions(profile,self.defs.map.data,self.defs.scenario.data)
        world=self.world({'players':{'red_1':{'x':-25,'z':2,'health':4,'protection_ticks':0},
                                     'blue_1':{'x':-23,'z':2,'protection_ticks':0}}},defs)
        policies=self.policies()
        policies['blue_1']=Policy(lambda obs:[self.req('attack','attack',{'player_id':'red_1','life_index':1})]
                                  if obs['observed_tick']==0 else [])
        runner=MatchRunner(world,policies,episode_limit_ticks=4)
        runner.run()
        self.assertEqual(len(policies['red_1'].starts),1)
        self.assertEqual(policies['red_1'].calls,[0,3])
        self.assertEqual(world.state['players']['red_1']['life_index'],2)

    def test_exception_fallback_cancels_movement_but_preserves_knockback(self):
        world=self.world({'players':{'red_1':{'knockback_x':0.3}}})
        policies=self.policies()
        def fail(_): raise ValueError('failure')
        policies['red_1']=Policy(fail)
        runner=MatchRunner(world,policies,episode_limit_ticks=1)
        runner.run()
        pos=world.state['players']['red_1']['life']['spatial']
        self.assertAlmostEqual(pos['x'],-24.7)
        self.assertAlmostEqual(pos['knockback_x'],0.225)
        self.assertEqual(next(x for x in runner.inputs if x['player_id']=='red_1')['fallback'],'policy_exception')

    def test_policy_version_change_is_a_runner_fault_without_result(self):
        policies=self.policies()
        runner=MatchRunner(self.world(),policies,episode_limit_ticks=3)
        runner.decision_step()
        policies['red_1'].version='2'
        with self.assertRaisesRegex(ValueError,'version changed'):
            runner.decision_step()
        self.assertIsNotNone(runner.failure)
        self.assertIsNone(runner.world.state['result'])
        self.assertFalse(runner.terminated)

    def test_cli_single_and_batch_write_usable_records_outside_checkout(self):
        with tempfile.TemporaryDirectory() as root:
            single=Path(root)/'single';batch=Path(root)/'batch'
            command=[sys.executable,'-m','bedwars_arena','run-l1','--episode-limit','2','--output',str(single),'--json']
            run=subprocess.run(command,cwd=root,capture_output=True,text=True,check=True)
            result=json.loads(run.stdout)
            self.assertEqual(result['tick'],2)
            self.assertTrue(result['truncated'])
            self.assertTrue((single/'initial-snapshot.json').exists())
            command=[sys.executable,'-m','bedwars_arena','batch-l1','--games','2','--episode-limit','1',
                     '--output',str(batch),'--json']
            run=subprocess.run(command,cwd=root,capture_output=True,text=True,check=True)
            result=json.loads(run.stdout)
            self.assertEqual((len(result['games']),result['truncated']),(2,2))
            self.assertTrue((batch/'game-0001'/'events.jsonl').exists())
            self.assertTrue((batch/'summary.json').exists())

    def test_recording_contains_versions_inputs_facts_and_snapshots(self):
        runner=MatchRunner(self.world(),self.policies(),episode_limit_ticks=2)
        runner.run()
        with tempfile.TemporaryDirectory() as directory:
            output=runner.write_artifacts(Path(directory)/'run')
            self.assertTrue((output/'manifest.json').is_file())
            definitions=json.loads((output/'definitions.json').read_text())
            self.assertEqual(validate_l1_definitions(definitions['profile'],definitions['map'],definitions['scenario']).hashes,
                             runner.world.definitions.hashes)
            self.assertTrue((output/'initial-snapshot.json').is_file())
            self.assertTrue((output/'final-snapshot.json').is_file())
            self.assertEqual(len((output/'inputs.jsonl').read_text().splitlines()),8)
            self.assertGreaterEqual(len((output/'events.jsonl').read_text().splitlines()),4)
            self.assertEqual(runner.manifest()['roster']['red_1'],{'name':'test-policy','version':'1'})
            self.assertEqual(len(runner.manifest()['runtime']['code_sha256']),64)
            with self.assertRaises(FileExistsError):runner.write_artifacts(output)


if __name__=='__main__': unittest.main()
