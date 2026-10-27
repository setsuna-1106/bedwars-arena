"""P4 generation, pickup, shopping, building and resource conservation."""
from copy import deepcopy
import unittest

from bedwars_arena.core.definitions import load_l1_definitions, validate_l1_definitions
from bedwars_arena.core.legality import interaction_error
from bedwars_arena.core.world import WorldEngine


class EconomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions=load_l1_definitions()
        cls.roster=('red_1','red_2','blue_1','blue_2')

    def world(self,preset=None):
        return WorldEngine.create(self.definitions,seed=16,match_id='economy',preset=preset)

    def round(self,w,round_id,requests):
        w.open_round(round_id)
        for pid in self.roster:
            packet={'protocol_version':1,'match_id':'economy','player_id':pid,'decision_round_id':round_id,
                    'observed_tick':w.state['tick'],'life_index':w.state['players'][pid]['life_index'],
                    'requests':requests.get(pid,[])}
            w.receive_actions(packet)
        w.seal_round();w.step()

    def req(self,request_id,kind,payload):
        return {'request_id':request_id,'kind':kind,'payload':payload}

    def result(self,w,pid,rid):
        return next(r for r in w.feedback(pid)['request_results'] if r['request_id']==rid)

    def test_pickup_before_buy_same_tick(self):
        w=self.world({'players':{'red_1':{'x':-25,'z':3,'inventory':{'wooden_sword':1,'shears':1,'iron':3}}},
                      'ground_items':[{'item_key':'iron','quantity':1,'x':-25,'z':3}]})
        buy=self.req('buy','buy',{'product':'wool'})
        self.round(w,'r1',{'red_1':[buy]})
        inv=w.state['players']['red_1']['life']['inventory']
        self.assertEqual(inv,{'wooden_sword':1,'shears':1,'wool':16})
        self.assertEqual(self.result(w,'red_1','buy')['status'],'applied')
        self.assertEqual([f['kind'] for f in w.last_facts],['item_picked_up','item_purchased'])
        self.assertEqual(w.state['entities'],{})

    def test_partial_pickup_and_full_pack_buy_is_atomic(self):
        w=self.world({'players':{'red_1':{'x':-25,'z':3,
                    'inventory':{'wooden_sword':1,'shears':1,'iron':383}}},
                      'ground_items':[{'item_key':'iron','quantity':10,'x':-25,'z':3}]})
        self.round(w,'r1',{'red_1':[self.req('buy','buy',{'product':'wool'})]})
        inv=w.state['players']['red_1']['life']['inventory']
        self.assertEqual(inv['iron'],384)
        self.assertNotIn('wool',inv)
        self.assertEqual(self.result(w,'red_1','buy')['reason'],'INVENTORY_FULL')
        self.assertEqual(next(iter(w.state['entities'].values()))['quantity'],9)
        self.assertEqual([f['kind'] for f in w.last_facts],['item_picked_up'])

    def test_pickup_competition_uses_player_order_then_capacity(self):
        w=self.world({'players':{'red_1':{'inventory':{'wooden_sword':1,'shears':1,'iron':382}}},
                      'ground_items':[{'item_key':'iron','quantity':5,'x':-25,'z':0}]})
        w.step()
        self.assertEqual(w.state['players']['red_1']['life']['inventory']['iron'],384)
        self.assertEqual(w.state['players']['red_2']['life']['inventory']['iron'],3)
        self.assertEqual(w.state['entities'],{})
        pickups=[f['payload']['quantity'] for f in w.last_facts if f['kind']=='item_picked_up']
        self.assertEqual(pickups,[2,3])

    def test_full_generator_continues_without_backlog(self):
        w=self.world({'players':{'red_1':{'x':0,'z':1,
                    'inventory':{'wooden_sword':1,'shears':1,'iron':382}}},
                      'ground_items':[{'item_key':'iron','quantity':64,'x':0,'z':0,'pickup_ready_at':15}]})
        for _ in range(10): w.step()
        self.assertEqual(w.state['generators']['center']['next_spawn_at'],20)
        self.assertEqual(len(w.state['entities']),1)
        self.assertFalse(any(f['kind']=='resource_generated' for f in w.last_facts))
        for _ in range(5): w.step()
        self.assertEqual(w.state['players']['red_1']['life']['inventory']['iron'],384)
        self.assertEqual(next(e for e in w.state['entities'].values() if e['source']['kind']=='preset')['quantity'],62)
        for _ in range(5): w.step()
        central=[e for e in w.state['entities'].values() if abs(e['spatial']['x'])<1 and abs(e['spatial']['z'])<1]
        self.assertEqual(sum(e['quantity'] for e in central),63)
        self.assertEqual(w.state['generators']['center']['next_spawn_at'],30)

    def test_new_sword_cannot_be_selected_before_purchase_and_does_not_repeat(self):
        w=self.world({'players':{'red_1':{'x':-25,'z':3,
                    'inventory':{'wooden_sword':1,'shears':1,'iron':12}}}})
        self.round(w,'r1',{'red_1':[self.req('select','select_item',{'item':'iron_sword'}),
                                    self.req('buy','buy',{'product':'iron_sword'})]})
        life=w.state['players']['red_1']['life']
        self.assertEqual(self.result(w,'red_1','select')['reason'],'ITEM_NOT_HELD')
        self.assertEqual(self.result(w,'red_1','buy')['status'],'applied')
        self.assertEqual(life['inventory'],{'shears':1,'iron_sword':1})
        self.assertIsNone(life['held_item'])
        w.step()
        self.assertEqual(w.state['players']['red_1']['life']['inventory'],life['inventory'])
        self.round(w,'r2',{'red_1':[self.req('select2','select_item',{'item':'iron_sword'})]})
        self.assertEqual(w.state['players']['red_1']['life']['held_item'],'iron_sword')

    def test_drop_is_split_delayed_and_not_repeated(self):
        w=self.world({'players':{'red_1':{'inventory':{'wooden_sword':1,'shears':1,'iron':70}}}})
        self.round(w,'r1',{'red_1':[self.req('drop','drop_resource',{'resource':'iron','quantity':70})]})
        entities=list(w.state['entities'].values())
        self.assertEqual(sorted(e['quantity'] for e in entities),[6,64])
        self.assertTrue(all(e['pickup_ready_at']==21 for e in entities))
        w.step()
        self.assertEqual(sum(e['quantity'] for e in w.state['entities'].values()),70)
        self.assertNotIn('iron',w.state['players']['red_1']['life']['inventory'])

    def test_place_then_recover_with_correct_tool(self):
        w=self.world({'players':{'red_1':{'x':-17.2,'z':0.5,'held_item':'wool',
                         'inventory':{'wooden_sword':1,'shears':1,'wool':1}}}})
        place=self.req('p','place_block',{'x':-16,'z':0,'layer':'bridge'})
        self.round(w,'r1',{'red_1':[place]})
        for _ in range(4): w.step()
        key='-16,-1,0';block=w.state['terrain'][key]
        self.assertEqual(w.state['players']['red_1']['life']['inventory'],{'wooden_sword':1,'shears':1})
        self.round(w,'r2',{'red_1':[self.req('select','select_item',{'item':'shears'})]})
        breaking=self.req('b','break_block',{'x':-16,'z':0,'layer':'bridge','instance_id':block['instance_id']})
        self.round(w,'r3',{'red_1':[breaking]})
        for _ in range(20): w.step()
        self.assertNotIn(key,w.state['terrain'])
        self.assertEqual(w.state['players']['red_1']['life']['inventory']['wool'],1)
        fact=next(f for f in w.last_facts if f['kind']=='block_broken')
        self.assertEqual(fact['payload']['recovery'],{'received':1,'dropped':0,'destroyed':0})
        self.assertEqual(w.feedback('red_1')['action_outcomes'][-1]['status'],'completed')

    def test_competing_placements_only_one_consumes_item(self):
        overrides={pid:{'x':-17.2,'z':0.5,'held_item':'wool',
                        'inventory':{'wooden_sword':1,'shears':1,'wool':1}} for pid in ('red_1','red_2')}
        w=self.world({'players':overrides})
        req=self.req('place','place_block',{'x':-16,'z':0,'layer':'bridge'})
        self.round(w,'r1',{'red_1':[req],'red_2':[req]})
        for _ in range(4): w.step()
        self.assertIn('-16,-1,0',w.state['terrain'])
        self.assertNotIn('wool',w.state['players']['red_1']['life']['inventory'])
        self.assertEqual(w.state['players']['red_2']['life']['inventory']['wool'],1)
        self.assertEqual(w.feedback('red_2')['action_outcomes'][-1]['reason'],'TARGET_INVALIDATED')

    def test_full_pack_recovery_drops_exactly_one_wool(self):
        w=self.world({'players':{
            'red_1':{'x':-17.2,'z':0.5,'held_item':'shears',
                     'inventory':{'wooden_sword':1,'shears':1,'iron':384}},
            'red_2':{'x':-17.2,'z':0.5,'held_item':'wool',
                     'inventory':{'wooden_sword':1,'shears':1,'wool':1}}}})
        self.round(w,'r1',{'red_2':[self.req('p','place_block',{'x':-16,'z':0,'layer':'bridge'})]})
        for _ in range(4): w.step()
        block=w.state['terrain']['-16,-1,0']
        self.round(w,'r2',{'red_1':[self.req('b','break_block',{'x':-16,'z':0,'layer':'bridge',
                                                               'instance_id':block['instance_id']})]})
        for _ in range(20): w.step()
        fact=next(f for f in w.last_facts if f['kind']=='block_broken')
        self.assertEqual(fact['payload']['recovery'],{'received':0,'dropped':1,'destroyed':0})
        wool=[e for e in w.state['entities'].values() if e['item_key']=='wool']
        self.assertEqual(len(wool),1)
        self.assertEqual(wool[0]['quantity'],1)
        self.assertNotIn('wool',w.state['players']['red_1']['life']['inventory'])

    def test_wrong_tool_and_old_instance_do_not_return_wool(self):
        w=self.world({'players':{'red_1':{'x':-17.2,'z':0.5,'held_item':'wool',
                         'inventory':{'wooden_sword':1,'shears':1,'wool':1}}}})
        self.round(w,'r1',{'red_1':[self.req('p','place_block',{'x':-16,'z':0,'layer':'bridge'})]})
        for _ in range(4): w.step()
        block=w.state['terrain']['-16,-1,0']
        payload={'x':-16,'z':0,'layer':'bridge','instance_id':'obsolete'}
        self.assertEqual(interaction_error(w.state,self.definitions,'red_1','break_block',payload),'TARGET_CHANGED')
        self.round(w,'r2',{'red_1':[self.req('select','select_item',{'item':'wooden_sword'})]})
        payload['instance_id']=block['instance_id']
        self.round(w,'r3',{'red_1':[self.req('b','break_block',payload)]})
        for _ in range(20): w.step()
        fact=next(f for f in w.last_facts if f['kind']=='block_broken')
        self.assertEqual(fact['payload']['recovery'],{'received':0,'dropped':0,'destroyed':0})
        self.assertNotIn('wool',w.state['players']['red_1']['life']['inventory'])


    def test_bed_breaking_and_attribution(self):
        w=self.world({'players':{'red_1':{'x':19.5,'z':0.5,'facing_x':1,'facing_z':0}}})
        self.round(w,'r1',{'red_1':[self.req('bed','break_bed',{'team_id':'blue'})]})
        for _ in range(40): w.step()
        self.assertEqual(w.state['teams']['blue']['bed_state'],{'status':'destroyed','destroyed_at':41})
        self.assertEqual(w.state['execution']['attributed_beds']['red'],1)
        self.assertTrue(any(f['kind']=='bed_destroyed' for f in w.last_facts))
        self.assertEqual(w.feedback('red_1')['action_outcomes'][-1]['status'],'completed')

    def test_bridge_under_wall_is_rejected_until_wall_removed(self):
        w=self.world({'players':{'red_1':{'x':-17.2,'z':0.5,'held_item':'wool',
                    'inventory':{'wooden_sword':1,'shears':1,'wool':2}}}})
        self.round(w,'r1',{'red_1':[self.req('p1','place_block',{'x':-16,'z':0,'layer':'bridge'})]})
        for _ in range(4): w.step()
        bridge=w.state['terrain']['-16,-1,0']
        self.round(w,'r2',{'red_1':[self.req('p2','place_block',{'x':-16,'z':0,'layer':'wall'})]})
        for _ in range(4): w.step()
        self.assertIn('-16,0,0',w.state['terrain'])
        req=self.req('b','break_block',{'x':-16,'z':0,'layer':'bridge','instance_id':bridge['instance_id']})
        self.round(w,'r3',{'red_1':[self.req('s','select_item',{'item':'shears'}),req]})
        self.assertEqual(self.result(w,'red_1','b')['reason'],'WALL_ABOVE_BRIDGE')
        self.assertIn('-16,-1,0',w.state['terrain'])

    def test_removing_own_support_settles_void_death_same_tick(self):
        w=self.world({'players':{'red_1':{'x':-17.2,'z':0.5,'held_item':'wool',
                    'inventory':{'wooden_sword':1,'shears':1,'wool':1}}}})
        self.round(w,'r1',{'red_1':[self.req('p','place_block',{'x':-16,'z':0,'layer':'bridge'})]})
        for _ in range(4): w.step()
        bridge=w.state['terrain']['-16,-1,0']
        self.round(w,'r2',{'red_1':[self.req('s','select_item',{'item':'shears'}),
                                     self.req('m','move',{'x':1,'z':0})]})
        for _ in range(7): w.step()
        self.assertGreater(w.state['players']['red_1']['life']['spatial']['x'],-15.7)
        req=self.req('b','break_block',{'x':-16,'z':0,'layer':'bridge','instance_id':bridge['instance_id']})
        self.round(w,'r3',{'red_1':[self.req('c','cancel',{'channel':'movement'}),req]})
        for _ in range(20): w.step()
        self.assertNotIn('-16,-1,0',w.state['terrain'])
        self.assertEqual(w.state['execution']['pending_deaths'],[])
        self.assertEqual(w.state['players']['red_1']['life']['kind'],'respawning')
        self.assertTrue(any(f['kind']=='player_died' and f['payload']['reason']=='void' for f in w.last_facts))

    def test_expiration_occurs_before_pickup_at_same_tick(self):
        profile=deepcopy(self.definitions.profile.data)
        profile['ground_items']['lifetime_ticks']=21
        defs=validate_l1_definitions(profile,self.definitions.map.data,self.definitions.scenario.data)
        w=WorldEngine.create(defs,seed=16,match_id='economy',preset={
            'ground_items':[{'item_key':'iron','quantity':1,'x':-25,'z':0,'pickup_ready_at':21}]})
        for _ in range(21): w.step()
        self.assertNotIn('iron',w.state['players']['red_1']['life']['inventory'])
        self.assertTrue(any(f['kind']=='ground_item_expired' for f in w.last_facts))
        self.assertFalse(any(e['source']['kind']=='preset' for e in w.state['entities'].values()))


if __name__=='__main__': unittest.main()
