"""P3 action intake, round sealing, feedback and isolated observations."""
from copy import deepcopy
import math
import unittest

from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.transactions import ChangeSet
from bedwars_arena.core.world import WorldEngine, WorldFault
from bedwars_arena.replay.snapshot import restore_snapshot


class ActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions=load_l1_definitions()
        cls.players=('red_1','red_2','blue_1','blue_2')

    def world(self,preset=None):
        return WorldEngine.create(self.definitions,seed=42,match_id='actions',preset=preset)

    def packet(self,world,pid,requests,*,round_id=None,tick=None,life=None):
        state=world.state
        return {'protocol_version':1,'match_id':state['match_id'],'player_id':pid,
                'decision_round_id':round_id or state['execution']['round']['id'],
                'observed_tick':state['tick'] if tick is None else tick,
                'life_index':state['players'][pid]['life_index'] if life is None else life,
                'requests':requests}

    def submit(self,world,*,requests=None,order=None):
        requests=requests or {}
        for pid in order or self.players:
            world.receive_actions(self.packet(world,pid,requests.get(pid,[])))
        world.seal_round()

    def test_common_boundary_isolation_and_no_internal_state_leak(self):
        world=self.world();world.open_round('r1')
        first=world.observe('red_1');second=world.observe('blue_1')
        self.assertEqual(first['observed_tick'],0)
        self.assertEqual(second['observed_tick'],0)
        self.assertNotIn('execution',first)
        self.assertNotIn('schedule_id',first['generators'][0])
        self.assertNotIn('instance_id',next(b for b in first['terrain']['blocks'] if b['kind']=='original'))
        first['players'][0]['inventory'].clear()
        first['terrain']['blocks'].clear()
        self.assertTrue(second['terrain']['blocks'])
        self.assertTrue(world.state['players']['red_1']['life']['inventory'])
        self.assertEqual(world.observe('red_1')['players'][0]['inventory'],{'wooden_sword':1,'shears':1})

    def test_group_conflicts_do_not_prevent_other_groups(self):
        world=self.world();world.open_round('r1')
        req=[{'request_id':'m1','kind':'move','payload':{'x':1,'z':0}},
             {'request_id':'m2','kind':'move','payload':{'x':0,'z':1}},
             {'request_id':'t1','kind':'turn','payload':{'x':0,'z':1}},
             {'request_id':'s1','kind':'select_item','payload':{'item':'shears'}}]
        receipt=world.receive_actions(self.packet(world,'red_1',req))
        by_id={x['request_id']:x for x in receipt['request_results']}
        self.assertEqual((by_id['m1']['reason'],by_id['m2']['reason']),('CHANNEL_CONFLICT','CHANNEL_CONFLICT'))
        self.assertEqual(by_id['t1']['status'],'accepted')
        for pid in self.players[1:]: world.receive_actions(self.packet(world,pid,[]))
        world.seal_round();world.step()
        player=world.state['players']['red_1']['life']
        self.assertEqual((player['spatial']['facing_x'],player['spatial']['facing_z']),(0,1))
        self.assertEqual(player['held_item'],'shears')
        self.assertIsNone(player['movement'])
        results={x['request_id']:x for x in world.feedback('red_1')['request_results']}
        self.assertEqual(results['t1']['status'],'applied')
        self.assertEqual(results['s1']['status'],'applied')

    def test_partial_bad_payload_is_rejected_without_losing_valid_request(self):
        world=self.world();world.open_round('r1')
        receipt=world.receive_actions(self.packet(world,'red_1',[
            {'request_id':'bad','kind':'move','payload':{'x':float('nan'),'z':0}},
            {'request_id':'good','kind':'turn','payload':{'x':0,'z':1}}]))
        by_id={x['request_id']:x for x in receipt['request_results']}
        self.assertEqual(by_id['bad']['reason'],'MALFORMED')
        self.assertEqual(by_id['good']['status'],'accepted')
        for pid in self.players[1:]: world.receive_actions(self.packet(world,pid,[]))
        world.seal_round();world.step()
        self.assertEqual(world.state['players']['red_1']['life']['spatial']['facing_z'],1)
        self.assertEqual(restore_snapshot(world.snapshot(),self.definitions).state,world.state)

    def test_retry_dedup_closed_round_and_snapshot(self):
        world=self.world();world.open_round('r1')
        req={'request_id':'move-a','kind':'move','payload':{'x':1,'z':0}}
        packet=self.packet(world,'red_1',[req])
        first=world.receive_actions(packet)
        for pid in self.players[1:]: world.receive_actions(self.packet(world,pid,[]))
        world.seal_round();before=world.snapshot()
        self.assertEqual(world.receive_actions(packet),first)
        self.assertEqual(world.snapshot(),before)
        restored=restore_snapshot(before,self.definitions)
        self.assertEqual(restored.step(),world.step())
        after=world.snapshot()
        repeat=world.receive_actions(packet)
        self.assertEqual(repeat['request_results'][0]['status'],'applied')
        self.assertEqual(world.snapshot(),after)
        conflict=deepcopy(packet);conflict['requests'][0]['payload']['x']=-1
        self.assertEqual(world.receive_actions(conflict)['request_results'][0]['reason'],'DUPLICATE_ID_CONFLICT')
        late=deepcopy(packet);late['requests'][0]['request_id']='new-late'
        rejected=world.receive_actions(late)
        self.assertEqual(rejected['request_results'][0]['reason'],'ROUND_CLOSED')
        self.assertEqual(world.receive_actions(late)['request_results'][0]['reason'],'ROUND_CLOSED')

    def test_duplicate_id_conflict_is_order_independent(self):
        a,b=self.world(),self.world()
        for w in (a,b): w.open_round('r1')
        x={'request_id':'same','kind':'move','payload':{'x':1,'z':0}}
        y={'request_id':'same','kind':'move','payload':{'x':0,'z':1}}
        ra=a.receive_actions(self.packet(a,'red_1',[x,y]))
        rb=b.receive_actions(self.packet(b,'red_1',[y,x]))
        self.assertEqual(ra,rb)
        self.assertEqual(ra['request_results'][0]['reason'],'DUPLICATE_ID_CONFLICT')
        self.assertEqual(a.state,b.state)

    def test_collection_order_and_motion_no_change_cancel(self):
        a,b=self.world(),self.world()
        for world in (a,b): world.open_round('r1')
        req={'red_1':[{'request_id':'m','kind':'move','payload':{'x':2,'z':0}}],
             'blue_1':[{'request_id':'t','kind':'turn','payload':{'x':0,'z':-1}}]}
        self.submit(a,requests=req,order=self.players)
        self.submit(b,requests=req,order=tuple(reversed(self.players)))
        self.assertEqual(a.step(),b.step())
        action=a.state['players']['red_1']['life']['movement']
        self.assertAlmostEqual(a.state['players']['red_1']['life']['spatial']['x'],-24.8)
        self.assertAlmostEqual(a.state['players']['red_1']['life']['spatial']['velocity_x'],0.2)
        a.open_round('r2')
        self.submit(a,requests={'red_1':[{'request_id':'m2','kind':'move','payload':{'x':1,'z':0}}]})
        a.step()
        self.assertEqual(a.state['players']['red_1']['life']['movement']['action_id'],action['action_id'])
        self.assertEqual(next(x for x in a.feedback('red_1')['request_results'] if x['request_id']=='m2')['reason'],'NO_CHANGE')
        a.open_round('r3')
        self.submit(a,requests={'red_1':[{'request_id':'c','kind':'cancel','payload':{'channel':'movement'}}]})
        a.step()
        self.assertIsNone(a.state['players']['red_1']['life']['movement'])
        self.assertEqual(a.feedback('red_1')['action_outcomes'][-1]['reason'],'CANCELLED')

    def test_missing_packet_or_unsealed_round_cannot_advance(self):
        world=self.world();world.open_round('r1')
        before=world.state
        with self.assertRaisesRegex(ValueError,'missing'): world.seal_round()
        with self.assertRaisesRegex(ValueError,'Seal'): world.step()
        self.assertEqual(world.state,before)

    def test_old_life_request_is_rechecked_in_controls(self):
        class NewLife(WorldEngine):
            def _phase_plan(self,tick,phase):
                if tick==1 and phase==0:
                    plan=ChangeSet.from_state(self._state)
                    player=deepcopy(self._state['players']['red_1'])
                    player['life_index']=2;player['life']['effects']=[]
                    plan.players['red_1']=player
                    return plan
                return super()._phase_plan(tick,phase)
        base=self.world();world=NewLife(self.definitions,base.state);world.open_round('r1')
        self.submit(world,requests={'red_1':[{'request_id':'m','kind':'move','payload':{'x':1,'z':0}}]})
        world.step()
        self.assertIsNone(world.state['players']['red_1']['life']['movement'])
        self.assertEqual(world.feedback('red_1')['request_results'][0]['reason'],'WRONG_LIFE')

    def test_only_legal_attack_start_removes_protection_and_select_interrupts(self):
        world=self.world(preset={'players':{'blue_1':{'x':-23,'z':0}}})
        world.open_round('r1')
        attack={'request_id':'a','kind':'attack','payload':{'player_id':'blue_1','life_index':1}}
        self.submit(world,requests={'red_1':[attack]});world.step()
        red=world.state['players']['red_1']['life']
        self.assertEqual(red['effects'],[])
        self.assertEqual(red['interaction']['kind'],'attack')
        self.assertEqual(world.last_facts[0]['kind'],'protection_removed')
        world.open_round('r2')
        self.submit(world,requests={'red_1':[{'request_id':'s','kind':'select_item','payload':{'item':'shears'}}]})
        world.step()
        self.assertIsNone(world.state['players']['red_1']['life']['interaction'])
        self.assertEqual(world.feedback('red_1')['action_outcomes'][-1]['reason'],'HELD_ITEM_CHANGED')
        far=self.world();far.open_round('far')
        self.submit(far,requests={'red_1':[attack]});far.step()
        self.assertEqual(far.feedback('red_1')['request_results'][0]['reason'],'OUT_OF_RANGE')
        self.assertEqual(len(far.state['players']['red_1']['life']['effects']),1)

    def test_continuous_interaction_interrupts_when_facing_is_lost(self):
        world=self.world(preset={'players':{'blue_1':{'x':-23,'z':0}}})
        world.open_round('r1')
        attack={'request_id':'a','kind':'attack','payload':{'player_id':'blue_1','life_index':1}}
        self.submit(world,requests={'red_1':[attack]});world.step()
        self.assertIsNotNone(world.state['players']['red_1']['life']['interaction'])
        world.open_round('r2')
        self.submit(world,requests={'red_1':[{'request_id':'turn','kind':'turn','payload':{'x':-1,'z':0}}]})
        world.step()
        self.assertIsNone(world.state['players']['red_1']['life']['interaction'])
        self.assertEqual(world.feedback('red_1')['action_outcomes'][-1]['reason'],'TARGET_INVALIDATED')

    def test_purchase_receipt_does_not_deduct_and_rechecks_distance(self):
        world=self.world();world.open_round('r1')
        self.submit(world,requests={'red_1':[{'request_id':'b','kind':'buy','payload':{'product':'wool'}}]})
        self.assertEqual(world.feedback('red_1')['request_results'][0]['status'],'accepted')
        world.step()
        self.assertEqual(world.feedback('red_1')['request_results'][0]['reason'],'OUT_OF_RANGE')
        self.assertNotIn('wool',world.state['players']['red_1']['life']['inventory'])


if __name__=='__main__': unittest.main()
