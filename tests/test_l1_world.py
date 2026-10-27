"""P1 world creation, transactional scheduling, snapshots and fault boundaries."""
from copy import deepcopy
import json
import random
import unittest

from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.messages import ScheduledTask
from bedwars_arena.core.transactions import ChangeSet, apply_plan, schedule
from bedwars_arena.core.world import WorldEngine, WorldFault
from bedwars_arena.core.world_state import validate_state
from bedwars_arena.replay.snapshot import dumps_snapshot, restore_snapshot


class WorldFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions = load_l1_definitions()
        cls.profile = cls.definitions.profile.data

    def make(self, **kwargs):
        return WorldEngine.create(self.definitions, seed=2**64-1, match_id='test-match', **kwargs)

    def test_standard_world_and_isolation(self):
        a, b = self.make(), self.make()
        state = a.state
        self.assertEqual(state['tick'], 0)
        self.assertEqual(len(state['terrain']), 388)
        self.assertEqual(list(state['players']), ['red_1','red_2','blue_1','blue_2'])
        self.assertEqual(len(state['execution']['pending_tasks']), 9)
        self.assertEqual([state['generators'][g]['next_spawn_at'] for g in ('red_base','center','blue_base')], [20,10,20])
        for player in state['players'].values():
            self.assertEqual(player['life_index'], 1)
            self.assertEqual(player['life']['inventory'], {'wooden_sword':1,'shears':1})
            self.assertEqual(player['life']['held_item'], 'wooden_sword')
            self.assertEqual(player['life']['effects'][0]['expires_at'], 40)
        with self.assertRaises(AttributeError):
            a.definitions = self.definitions
        self.assertEqual(len(a.initial_facts), 4)
        self.assertEqual(len({fact['commit_id'] for fact in a.initial_facts}), 1)
        state['players']['red_1']['life']['inventory'].clear()
        self.assertEqual(a.state, b.state)
        self.assertEqual(a.step()['tick'], 1)
        self.assertEqual(a.state['execution']['cursor'], {'tick':1,'phase':90})
        self.assertEqual(b.state['tick'], 0)

    def test_training_preset_and_float_rng_snapshot_round_trip(self):
        world = self.make(preset={'source':'test-case-17', 'players':{'red_1':{
            'x':-24.812345678901234,'z':-0.12345678901234567,'health':7.25,
            'inventory':{'wooden_sword':1,'shears':1,'iron':12}, 'armor_tier':1,
            'protection_ticks':2}}, 'beds':{'blue':False},
            'generator_first_ticks':{'center':50}})
        snap = world.snapshot()
        restored = restore_snapshot(dumps_snapshot(snap), self.definitions)
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(restored.state['players']['red_1']['life']['spatial']['x'], -24.812345678901234)
        self.assertEqual(restored.state['teams']['blue']['bed_state']['destroyed_at'], 0)
        for name, value in restored.state['execution']['rng_states'].items():
            one, two = random.Random(), random.Random()
            original = world.state['execution']['rng_states'][name]
            one.setstate((original[0],tuple(original[1]),original[2]))
            two.setstate((value[0],tuple(value[1]),value[2]))
            self.assertEqual([one.random() for _ in range(3)], [two.random() for _ in range(3)])
        self.assertEqual(world.step(), restored.step())
        self.assertEqual(world.step(), restored.step())
        self.assertEqual(world.last_facts, restored.last_facts)
        self.assertEqual(world.last_facts[0]['kind'], 'protection_expired')

    def test_invalid_presets_rejected_before_publishing(self):
        bad = [
            {'players':{'nobody':{}}},
            {'players':{'red_1':{'x':-10,'z':0}}},  # gap, no support
            {'players':{'red_1':{'x':-21.5,'z':0.5}}},  # inside a bed
            {'players':{'red_1':{'health':float('nan')}}},
            {'players':{'red_1':{'inventory':{'wooden_sword':1,'shears':1,'iron':449}}}},
            {'players':{'red_1':{'held_item':'iron_sword'}}},
            {'players':{'red_1':{'facing_x':0,'facing_z':0}}},
            {'players':{'red_1':{'protection_ticks':True}}},
            {'beds':{'red':1}}, {'generator_first_ticks':{'center':0}},
        ]
        for preset in bad:
            with self.subTest(preset=preset), self.assertRaises(ValueError):
                self.make(preset=preset)

    def test_snapshot_rejects_corruption_and_legacy_queue(self):
        snap = self.make().snapshot()
        mutations = []
        x=deepcopy(snap); x['definition_ref']['map']['sha256']='0'*64; mutations.append(x)
        x=deepcopy(snap); x['runtime']['python']='0.0.0'; mutations.append(x)
        x=deepcopy(snap); del x['runtime']['world_engine_revision']; mutations.append(x)
        x=deepcopy(snap); x['schema_version']=True; mutations.append(x)
        x=deepcopy(snap); x['state']['execution']['cursor']['phase']=20; mutations.append(x)
        x=deepcopy(snap); x['state']['players']['red_1']['life']['spatial']['x']=float('inf'); mutations.append(x)
        x=deepcopy(snap); del x['state']['terrain']['-28,-1,-6']; mutations.append(x)
        x=deepcopy(snap); x['state']['terrain']['-0,-1,0']=x['state']['terrain'].pop('0,-1,0'); mutations.append(x)
        x=deepcopy(snap); x['state']['execution']['pending_tasks'][0]['id']='other'; mutations.append(x)
        mutations.append({'schema_version':1,'pending':[],'seen':{},'cursor':None})
        for bad in mutations:
            with self.subTest(bad=bad.get('kind','legacy')), self.assertRaises(ValueError):
                restore_snapshot(bad, self.definitions)
        with self.assertRaises(ValueError):
            restore_snapshot('{"kind":"a","kind":"b"}', self.definitions)

    def test_failed_plan_is_atomic_for_state_queue_id_and_facts(self):
        state = self.make().state
        state['execution']['cursor'] = {'tick':1,'phase':20}
        original = deepcopy(state)
        plan = ChangeSet.from_state(state)
        changed = deepcopy(state['players']['red_1'])
        changed['life']['inventory']['iron'] = 449  # exceeds eight total stacks
        plan.players['red_1'] = changed
        task = ScheduledTask.create(task_id=plan.allocate(), kind='probe', created_at=1,
                                    execute_at=1,phase=30,source_order=0,payload={})
        plan.add_tasks.append(task)
        plan.emit(kind='probe_fact', tick=1, phase=20, payload={'n':1})
        with self.assertRaisesRegex(ValueError,'capacity'):
            apply_plan(state,plan,budget=self.profile['budget'],validate=lambda x:validate_state(x,self.definitions))
        self.assertEqual(state,original)
        changed['life']['inventory']['iron']=1
        result,facts = apply_plan(state,plan,budget=self.profile['budget'],validate=lambda x:validate_state(x,self.definitions))
        self.assertEqual(result['players']['red_1']['life']['inventory']['iron'],1)
        self.assertEqual(len(facts),1)
        self.assertEqual(result['execution']['next_id'],plan.next_id)
        self.assertIn(task.task_id,result['execution']['seen_messages'])
        self.assertEqual(state,original)
        with self.assertRaisesRegex(ValueError,'Stale'):
            apply_plan(result,plan,budget=self.profile['budget'],validate=lambda x:validate_state(x,self.definitions))

    def test_dedup_after_consumption_and_restore_and_closed_empty_stage(self):
        world = self.make(preset={'players':{'red_1':{'protection_ticks':1}}})
        task = next(ScheduledTask.from_dict(t) for t in world.state['execution']['pending_tasks']
                    if t['kind']=='expire_protection' and t['payload']['player_id']=='red_1')
        world.step()
        self.assertEqual(len(world.last_facts),1)
        state = restore_snapshot(world.snapshot(),self.definitions).state
        self.assertFalse(schedule(state,task,self.profile['budget']))
        conflict = ScheduledTask.create(task_id=task.task_id,kind=task.kind,created_at=task.created_at,
                                       execute_at=task.execute_at,phase=task.phase,source_order=task.source_order,
                                       payload={'player_id':'red_2','life_index':1,'effect_id':'other'})
        with self.assertRaisesRegex(ValueError,'different content'):
            schedule(state,conflict,self.profile['budget'])
        late = ScheduledTask.create(task_id='new-id',kind='probe',created_at=1,execute_at=1,
                                    phase=35,source_order=0,payload={})
        with self.assertRaisesRegex(ValueError,'completed phase'):
            schedule(state,late,self.profile['budget'])

    def test_stale_life_skips_without_success_fact(self):
        class StaleLifeEngine(WorldEngine):
            def _phase_plan(self,tick,phase):
                if tick==1 and phase==0:
                    plan=ChangeSet.from_state(self._state)
                    player=deepcopy(self._state['players']['red_1'])
                    player['life_index']=2
                    player['life']['effects']=[]
                    plan.players['red_1']=player
                    return plan
                return None
        base = self.make(preset={'players':{'red_1':{'protection_ticks':1}}})
        world = StaleLifeEngine(self.definitions,base.state)
        world.step()
        self.assertEqual(world.last_facts,())
        self.assertEqual(world.state['execution']['diagnostics'][-1]['reason'],'stale_life')
        self.assertEqual(restore_snapshot(world.snapshot(),self.definitions).state,world.state)

    def test_replaced_effect_invalidates_old_task_without_expiring_new_effect(self):
        class ReplaceEngine(WorldEngine):
            def _phase_plan(self,tick,phase):
                if tick == 1 and phase == 0:
                    plan=ChangeSet.from_state(self._state)
                    player=deepcopy(self._state['players']['red_1'])
                    effect=deepcopy(player['life']['effects'][0])
                    effect['effect_id']=plan.allocate()
                    effect['expires_at']=2
                    player['life']['effects']=[effect]
                    plan.players['red_1']=player
                    plan.add_tasks.append(ScheduledTask.create(task_id=plan.allocate(),
                        kind='expire_protection',created_at=1,execute_at=2,phase=0,source_order=0,
                        payload={'player_id':'red_1','life_index':1,'effect_id':effect['effect_id']}))
                    return plan
                return super()._phase_plan(tick,phase)
        base=self.make(preset={'players':{'red_1':{'protection_ticks':1}}})
        world=ReplaceEngine(self.definitions,base.state)
        world.step()
        self.assertEqual(world.last_facts,())
        self.assertEqual(world.state['execution']['diagnostics'][-1]['reason'],'stale_instance')
        self.assertEqual(world.state['players']['red_1']['life']['effects'][0]['expires_at'],2)
        restored=restore_snapshot(world.snapshot(),self.definitions)
        world.step()
        restored.step()
        self.assertEqual(world.state,restored.state)
        self.assertEqual(world.last_facts[0]['kind'],'protection_expired')
        self.assertEqual(world.state['players']['red_1']['life']['effects'],[])

    def test_cancelled_task_is_skipped_without_fact_and_survives_snapshot(self):
        class CancelEngine(WorldEngine):
            def _phase_plan(self,tick,phase):
                if tick == 1 and phase == 0:
                    plan = ChangeSet.from_state(self._state)
                    task = next(t for t in self._state['execution']['pending_tasks']
                                if t['kind']=='expire_protection' and t['payload']['player_id']=='red_1')
                    player = deepcopy(self._state['players']['red_1'])
                    player['life']['effects'] = []
                    plan.players['red_1'] = player
                    plan.cancel_tasks.append(task['id'])
                    return plan
                return None
        initial = self.make(preset={'players':{'red_1':{'protection_ticks':1}}})
        world = CancelEngine(self.definitions,initial.state)
        world.step()
        self.assertEqual(world.last_facts,())
        self.assertEqual(world.state['execution']['diagnostics'][-1]['reason'],'cancelled')
        self.assertEqual(restore_snapshot(world.snapshot(),self.definitions).state,world.state)
        self.assertEqual(len(world.state['execution']['cancelled']),1)

    def test_fault_does_not_publish_partial_tick_or_auto_retry(self):
        class BrokenEngine(WorldEngine):
            def _phase_plan(self,tick,phase):
                if phase == 20:
                    plan=ChangeSet.from_state(self._state)
                    p=deepcopy(self._state['players']['red_1'])
                    p['life']['inventory']['iron']=449
                    plan.players['red_1']=p
                    plan.emit(kind='must_not_publish',tick=tick,phase=phase,payload={})
                    return plan
                return None
        base = self.make()
        world = BrokenEngine(self.definitions,base.state)
        before = world.snapshot()
        with self.assertRaises(WorldFault):
            world.step()
        self.assertEqual(world.snapshot(),before)
        self.assertEqual(world.last_facts,())
        self.assertEqual(world.state['tick'],0)
        # Phase 20 was only attempted; its cursor and failed plan did not commit.
        self.assertEqual(world._state['execution']['cursor'], {'tick':1,'phase':10})
        self.assertEqual(world._state['players']['red_1'],before['state']['players']['red_1'])
        self.assertEqual(world._state['execution']['next_id'],before['state']['execution']['next_id'])
        self.assertEqual(world._state['execution']['pending_tasks'],before['state']['execution']['pending_tasks'])
        self.assertIsNotNone(world.fault)
        with self.assertRaises(WorldFault):
            world.step()
        recovered=restore_snapshot(before,self.definitions)
        self.assertEqual(recovered.step()['tick'],1)

    def test_unimplemented_due_task_faults_without_false_event(self):
        world = self.make(preset={'generator_first_ticks':{'center':1}})
        before=world.snapshot()
        with self.assertRaisesRegex(WorldFault,'generator_spawn'):
            world.step()
        self.assertEqual(world.snapshot(),before)
        self.assertEqual(world.last_facts,())
        self.assertIsNone(world.state['result'])


if __name__ == '__main__':
    unittest.main()
