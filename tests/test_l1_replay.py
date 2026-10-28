"""P7 input replay, complete-boundary recovery and recorded viewer data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bedwars_arena.core.definitions import load_l1_definitions, validate_l1_definitions
from bedwars_arena.core.world import WorldEngine, WorldFault
from bedwars_arena.replay.record import apply_changes, changes, decode_packet, first_difference, state_hash
from bedwars_arena.replay.snapshot import restore_snapshot
from bedwars_arena.replay.verify import ReplayMismatch, verify_run
from bedwars_arena.replay.viewer import export_viewer
from bedwars_arena.runner.match import MatchRunner


class Script:
    name='replay-test';version='1'
    def __init__(self,fn=lambda obs:[]):self.fn=fn
    def act(self,obs):return self.fn(obs)


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        defaults=load_l1_definitions()
        profile=deepcopy(defaults.profile.data);profile['budget']['snapshot_interval_ticks']=2
        cls.defs=validate_l1_definitions(profile,defaults.map.data,defaults.scenario.data)
        cls.ids=('red_1','red_2','blue_1','blue_2')
    def policies(self):return {p:Script() for p in self.ids}
    def world(self,preset=None):return WorldEngine.create(self.defs,seed=101,match_id='p7-test',preset=preset)
    def run_record(self,root,*,world=None,policies=None,k=1,limit=6):
        runner=MatchRunner(world or self.world(),policies or self.policies(),decision_interval=k,episode_limit_ticks=limit)
        runner.run();return runner,runner.write_artifacts(Path(root)/'record')
    @staticmethod
    def req(rid,kind,payload):return {'request_id':rid,'kind':kind,'payload':payload}

    def test_delta_and_first_difference_preserve_float_bits_and_paths(self):
        before={'a':{'x':-0.0,'gone':1},'items':[1,-0.0,{'v':1}]}
        after={'a':{'x':0.0,'new':3},'items':[1,0.0,{'v':1.0}]}
        clone=deepcopy(before);apply_changes(clone,changes(before,after))
        self.assertEqual(state_hash(clone),state_hash(after))
        self.assertNotEqual(state_hash(before),state_hash(after))
        self.assertEqual(first_difference(-0.0,0.0)[0],'$')
        self.assertEqual(first_difference({'x':[1]},{'x':[2]})[0],'$["x"][0]')
        with self.assertRaises(ValueError):apply_changes({},[{'op':'delete','path':['missing']}])

    def test_replay_from_initial_and_periodic_checkpoints_keeps_original_limit(self):
        with tempfile.TemporaryDirectory() as root:
            runner,path=self.run_record(root,k=3,limit=7)
            for tick in (0,2,4,6):
                report=verify_run(path,from_tick=tick)
                self.assertTrue(report['valid']);self.assertEqual(report['ticks_compared'],7-tick)
                self.assertTrue(report['truncated']);self.assertFalse(report['terminated'])
            self.assertEqual(verify_run(path,from_tick=6)['inputs_consumed'],4)
            with self.assertRaisesRegex(ValueError,'No complete indexed snapshot'):
                verify_run(path,from_tick=3)
            index=json.loads((path/'index.json').read_text())
            self.assertEqual([x['tick'] for x in index['snapshots']],[0,2,4,6,7])

    def test_sealed_snapshot_purchase_is_not_submitted_twice(self):
        world=self.world({'players':{'red_1':{'x':-25,'z':3,
                    'inventory':{'wooden_sword':1,'shears':1,'iron':4}}}})
        world.open_round('sealed')
        packets=[]
        for p in self.ids:
            packets.append({'protocol_version':1,'match_id':'p7-test','player_id':p,'decision_round_id':'sealed',
                'observed_tick':0,'life_index':1,'requests':[self.req('buy','buy',{'product':'wool'})] if p=='red_1' else []})
        world.receive_actions_batch(packets);world.seal_round()
        restored=restore_snapshot(world.snapshot(),self.defs)
        with tempfile.TemporaryDirectory() as root:
            runner,path=self.run_record(root,world=restored,k=3,limit=3)
            self.assertEqual(runner.inputs,[])
            self.assertEqual(sum(f['kind']=='item_purchased' for f in runner.events),1)
            self.assertEqual(verify_run(path)['inputs_consumed'],0)
            self.assertTrue(verify_run(path,from_tick=2)['valid'])

    def test_recorded_malformed_and_fallback_packets_replay_without_policy(self):
        policies=self.policies()
        policies['red_1']=Script(lambda obs:[object()])
        policies['red_2']=Script(lambda obs:[self.req('nan','move',{'x':float('nan'),'z':0})])
        def fail(_):raise RuntimeError('script failed')
        policies['blue_1']=Script(fail)
        policies['blue_2']=Script(lambda obs:[self.req('unicode','move',{'x':0,'z':0,'\ud800':1})]
                                  if obs['observed_tick']==0 else
                                  [self.req('unicode2','select_item',{'item':'\ud800'})])
        with tempfile.TemporaryDirectory() as root:
            runner,path=self.run_record(root,policies=policies,limit=2)
            records={x['player_id']:x for x in runner.inputs[:4]}
            self.assertEqual(records['red_1']['fallback'],'malformed_packet')
            self.assertEqual(records['blue_1']['fallback'],'policy_exception')
            self.assertEqual(records['blue_2']['fallback'],'malformed_packet')
            self.assertEqual(records['red_2']['initial_receipt']['request_results'][0]['reason'],'MALFORMED')
            self.assertTrue(verify_run(path)['valid'])

    def test_waiting_for_respawn_and_continuous_break_survive_snapshots(self):
        preset={'players':{'red_1':{'x':-17.2,'z':0.5,'held_item':'wool',
                    'inventory':{'wooden_sword':1,'shears':1,'wool':1},'protection_ticks':0},
                    'red_2':{'x':-25,'z':2,'health':4,'protection_ticks':0},
                    'blue_1':{'x':-23,'z':2,'protection_ticks':0}}}
        policies=self.policies()
        def build(obs):
            t=obs['observed_tick']
            if t==0:return [self.req('place','place_block',{'x':-16,'z':0,'layer':'bridge'})]
            if t==5:return [self.req('select','select_item',{'item':'shears'})]
            if t==6:
                block=next(x for x in obs['terrain']['blocks'] if x['x']==-16 and x['z']==0 and x['layer']=='bridge')
                return [self.req('break','break_block',{'x':-16,'z':0,'layer':'bridge','instance_id':block['instance_id']})]
            return []
        policies['red_1']=Script(build)
        policies['blue_1']=Script(lambda obs:[self.req('attack','attack',{'player_id':'red_2','life_index':1})]
                                  if obs['observed_tick']==0 else [])
        with tempfile.TemporaryDirectory() as root:
            runner,path=self.run_record(root,world=self.world(preset),policies=policies,limit=30)
            self.assertTrue(any(e['kind']=='player_died' and not e['payload']['final'] for e in runner.events))
            broken=next(e for e in runner.events if e['kind']=='block_broken')
            self.assertEqual(broken['payload']['recovery']['received'],1)
            for tick in (2,8,14):self.assertTrue(verify_run(path,from_tick=tick)['valid'])

    def test_full_inventory_recovery_and_duplicate_request_survive_replay(self):
        preset={'players':{'red_1':{'x':-17.2,'z':0.5,'held_item':'shears',
                    'inventory':{'wooden_sword':1,'shears':1,'iron':384}},
                    'red_2':{'x':-17.2,'z':0.5,'held_item':'wool',
                    'inventory':{'wooden_sword':1,'shears':1,'wool':1}}}}
        policies=self.policies()
        policies['red_2']=Script(lambda obs:[self.req('place','place_block',{'x':-16,'z':0,'layer':'bridge'})]
                                  if obs['observed_tick']==0 else [])
        def recover(obs):
            if obs['observed_tick']==5:
                block=next(x for x in obs['terrain']['blocks'] if x['x']==-16 and x['z']==0 and x['layer']=='bridge')
                return [self.req('break','break_block',{'x':-16,'z':0,'layer':'bridge','instance_id':block['instance_id']})]
            return []
        policies['red_1']=Script(recover)
        # Reusing an ID in a later round is a conflict and must not create another action.
        policies['blue_1']=Script(lambda obs:[self.req('same','move',{'x':1,'z':0})])
        with tempfile.TemporaryDirectory() as root:
            runner,path=self.run_record(root,world=self.world(preset),policies=policies,limit=30)
            broken=next(e for e in runner.events if e['kind']=='block_broken')
            self.assertEqual(broken['payload']['recovery'],{'received':0,'dropped':1,'destroyed':0})
            self.assertTrue(any(x['initial_receipt']['request_results'] and
                                x['initial_receipt']['request_results'][0]['reason']=='DUPLICATE_ID_CONFLICT'
                                for x in runner.inputs if x['player_id']=='blue_1'))
            for tick in (0,8,20):self.assertTrue(verify_run(path,from_tick=tick)['valid'])

    def test_late_and_retry_packets_are_recorded_at_their_boundary(self):
        policies=self.policies()
        policies['red_1']=Script(lambda obs:[self.req('move-once','move',{'x':1,'z':0})]
                                 if obs['observed_tick']==0 else [])
        runner=MatchRunner(self.world(),policies,episode_limit_ticks=4)
        runner.decision_step();runner.decision_step()
        retry=decode_packet(runner.rounds[0]['batch'][0])
        receipt=runner.receive_recorded(retry)
        self.assertEqual(receipt['request_results'][0]['status'],'applied')
        late=deepcopy(retry);late['requests'][0]['request_id']='new-late'
        receipt=runner.receive_recorded(late)
        self.assertEqual(receipt['request_results'][0]['reason'],'ROUND_CLOSED')
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'unfinished'):
                runner.write_artifacts(Path(root)/'premature')
            runner.run();path=runner.write_artifacts(Path(root)/'record')
            self.assertEqual(len((path/'external-inputs.jsonl').read_text().splitlines()),2)
            self.assertEqual(verify_run(path,from_tick=0)['external_inputs_consumed'],2)
            self.assertEqual(verify_run(path,from_tick=2)['external_inputs_consumed'],2)
            self.assertEqual(verify_run(path,from_tick=4)['external_inputs_consumed'],0)
            with self.assertRaisesRegex(ValueError,'finished'):runner.receive_recorded(retry)

    def test_fault_record_keeps_last_complete_and_sealed_boundaries_distinct(self):
        world=self.world();runner=MatchRunner(world,self.policies(),episode_limit_ticks=5)
        runner.decision_step();runner.decision_step()
        step=world.step
        def fail():raise RuntimeError('injected advance failure')
        world.step=fail
        with self.assertRaisesRegex(RuntimeError,'injected'):
            runner.decision_step()
        world.step=step
        with tempfile.TemporaryDirectory() as root:
            path=runner.write_artifacts(Path(root)/'fault')
            self.assertTrue((path/'fault-boundary-snapshot.json').exists())
            clean=json.loads((path/'final-snapshot.json').read_text())
            sealed=json.loads((path/'fault-boundary-snapshot.json').read_text())
            self.assertFalse(clean['state']['execution']['round']['observed_tick']==2)
            self.assertTrue(sealed['state']['execution']['round']['sealed'])
            restored=restore_snapshot(sealed,self.defs);restored.step()
            self.assertEqual(restored.state['tick'],3)
            report=verify_run(path)
            self.assertEqual(report['to_tick'],2)
            self.assertEqual(report['failure']['type'],'RuntimeError')

    def test_first_state_and_event_differences_are_reported(self):
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            lines=(path/'frames.jsonl').read_text().splitlines()
            frame=json.loads(lines[1]);frame['changes'].append({'op':'set','path':['players','red_1','life_index'],'value':99})
            lines[1]=json.dumps(frame,separators=(',',':'))
            (path/'frames.jsonl').write_text('\n'.join(lines)+'\n')
            with self.assertRaises(ReplayMismatch) as cm:verify_run(path)
            self.assertEqual(cm.exception.tick,1)
            self.assertIn('life_index',cm.exception.path)
        with tempfile.TemporaryDirectory() as root:
            preset={'players':{'red_1':{'x':-22.5,'z':0.5,'protection_ticks':0}}}
            policies=self.policies()
            policies['red_1']=Script(lambda obs:[self.req('move','move',{'x':1,'z':0})] if obs['observed_tick']==0 else [])
            runner,path=self.run_record(root,world=self.world(preset),policies=policies,limit=2)
            self.assertTrue(any(e['kind']=='movement_collision' for e in runner.events))
            events=[json.loads(x) for x in (path/'events.jsonl').read_text().splitlines()]
            event=next(x for x in events if x['kind']=='movement_collision');event['payload']['player_id']='blue_1'
            (path/'events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n')
            with self.assertRaises(ReplayMismatch) as cm:verify_run(path)
            self.assertIn('events',cm.exception.path)
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            rows=[json.loads(x) for x in (path/'inputs.jsonl').read_text().splitlines()]
            rows[0]['packet']['requests']=[self.req('altered','move',{'x':1,'z':0})]
            (path/'inputs.jsonl').write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
            with self.assertRaises(ReplayMismatch) as cm:verify_run(path)
            self.assertIn('inputs.sha256',cm.exception.path)
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            events=[json.loads(x) for x in (path/'events.jsonl').read_text().splitlines()]
            events[0]['payload']['player_id']='blue_1'
            (path/'events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n')
            with self.assertRaises(ReplayMismatch) as cm:verify_run(path)
            self.assertEqual(cm.exception.tick,0)
            self.assertIn('events[0]',cm.exception.path)

    def test_engine_fault_during_replay_reports_the_first_tick(self):
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            with patch.object(WorldEngine,'step',side_effect=WorldFault('injected fault')):
                with self.assertRaises(ReplayMismatch) as cm:verify_run(path)
            self.assertEqual((cm.exception.tick,cm.exception.path),(1,'$.engine'))

    def test_missing_logs_incompatible_runtime_or_definitions_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            definitions=json.loads((path/'definitions.json').read_text());definitions['profile']['life']['protection_duration_ticks']+=1
            (path/'definitions.json').write_text(json.dumps(definitions))
            with self.assertRaisesRegex(ValueError,'definition hash'):verify_run(path)
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            manifest=json.loads((path/'manifest.json').read_text());manifest['definitions']['map']['sha256']='0'*64
            (path/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'definition hash'):verify_run(path)
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            manifest=json.loads((path/'manifest.json').read_text());manifest['runtime']['python']='0.0.0'
            (path/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'runtime'):verify_run(path)
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            (path/'rounds.jsonl').write_text('')
            with self.assertRaisesRegex(ValueError,'incomplete'):verify_run(path)

    def test_same_tick_natural_result_and_limit_survive_replay(self):
        players={pid:{'x':-25 if pid.startswith('red') else -23,'z':2,
                      'health':20 if pid.startswith('red') else 4,'protection_ticks':0} for pid in self.ids}
        policies=self.policies()
        for pid in ('red_1','red_2'):
            target='blue_'+pid[-1]
            policies[pid]=Script(lambda obs,target=target:[self.req('attack','attack',{'player_id':target,'life_index':1})])
        with tempfile.TemporaryDirectory() as root:
            runner,path=self.run_record(root,world=self.world({'players':players,'beds':{'blue':False}}),
                                        policies=policies,k=5,limit=1)
            result=verify_run(path)
            self.assertTrue(result['terminated']);self.assertTrue(result['truncated'])
            self.assertEqual(runner.summary()['result']['winner_team_id'],'red')

    def test_viewer_is_self_contained_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as root:
            _,path=self.run_record(root,limit=2)
            output=export_viewer(path,Path(root)/'replay.html')
            content=output.read_text()
            self.assertIn('p7-test',content)
            self.assertIn('单步',content)
            self.assertIn('movement_collision',content)
            self.assertNotIn('/*__REPLAY_DATA__*/',content)
            self.assertNotIn('<script src=',content)
            with self.assertRaises(FileExistsError):export_viewer(path,output)

if __name__=='__main__':unittest.main()
