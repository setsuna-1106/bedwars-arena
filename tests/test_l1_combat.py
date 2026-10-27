"""P5 simultaneous damage, life transitions, resources and match outcome."""
from copy import deepcopy
import unittest

from bedwars_arena.core.definitions import load_l1_definitions, validate_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.replay.snapshot import restore_snapshot


class CombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions=load_l1_definitions()
        cls.roster=('red_1','red_2','blue_1','blue_2')

    def defs(self,*,global_tick=None,end_tick=None,break_ticks=None,attack_ticks=None):
        profile=deepcopy(self.definitions.profile.data)
        if global_tick is not None: profile['schedule']['global_bed_destruction_tick']=global_tick
        if end_tick is not None: profile['schedule']['game_end_tick']=end_tick
        if break_ticks is not None: profile['building']['bed_break_duration_ticks']=break_ticks
        if attack_ticks is not None: profile['combat']['attack_interval_ticks']=attack_ticks
        return validate_l1_definitions(profile,self.definitions.map.data,self.definitions.scenario.data)

    def world(self,preset=None,definitions=None):
        return WorldEngine.create(definitions or self.definitions,seed=1,match_id='combat',preset=preset)

    def req(self,rid,kind,payload):
        return {'request_id':rid,'kind':kind,'payload':payload}

    def round(self,w,rid,requests):
        w.open_round(rid)
        for pid in self.roster:
            player=w.state['players'][pid]
            if player['life']['kind']!='alive':
                continue
            w.receive_actions({'protocol_version':1,'match_id':'combat','player_id':pid,
                'decision_round_id':rid,'observed_tick':w.state['tick'],'life_index':player['life_index'],
                'requests':requests.get(pid,[])})
        w.seal_round();w.step()

    def duel_preset(self,beds=None):
        return {'beds':beds or {},'players':{
            'red_1':{'x':-25,'z':2,'health':4,'protection_ticks':0,
                     'inventory':{'wooden_sword':1,'shears':1,'iron':4}},
            'blue_1':{'x':-23,'z':2,'health':4,'protection_ticks':0,
                      'inventory':{'wooden_sword':1,'shears':1,'iron':7}}}}

    def test_mutual_kill_freezes_attacks_and_destroys_cross_transfers(self):
        w=self.world(self.duel_preset())
        self.round(w,'r1',{'red_1':[self.req('ra','attack',{'player_id':'blue_1','life_index':1})],
                           'blue_1':[self.req('ba','attack',{'player_id':'red_1','life_index':1})]})
        for pid in ('red_1','blue_1'):
            p=w.state['players'][pid]
            self.assertEqual(p['life'],{'kind':'respawning','died_at':1,'respawn_at':61})
            self.assertEqual((p['stats']['kills'],p['stats']['deaths']),(1,1))
        deaths=[f['payload'] for f in w.last_facts if f['kind']=='player_died']
        self.assertEqual(len(deaths),2)
        self.assertEqual(sorted(d['iron']['destroyed'] for d in deaths),[4,7])
        self.assertTrue(all(d['iron']['received']==d['iron']['dropped']==0 for d in deaths))
        self.assertIsNone(w.state['result'])

    def test_protection_and_hurt_interval_are_independent_from_attack_cooldown(self):
        w=self.world({'players':{'red_1':{'x':-25,'z':2,'protection_ticks':0},
                                 'red_2':{'x':-25,'z':2,'protection_ticks':0},
                                 'blue_1':{'x':-23,'z':2,'protection_ticks':0}}})
        attack=lambda rid:self.req(rid,'attack',{'player_id':'blue_1','life_index':1})
        self.round(w,'r1',{'red_1':[attack('a')],'red_2':[attack('b')]})
        self.assertEqual(w.state['players']['blue_1']['life']['vitality']['health'],16)
        self.assertEqual(w.state['players']['red_1']['cooldowns']['attack'],11)
        self.assertEqual(w.state['players']['red_2']['cooldowns']['attack'],11)
        self.assertEqual(w.state['players']['blue_1']['cooldowns']['hurt'],7)
        self.assertEqual([f['kind'] for f in w.last_facts].count('melee_hit'),1)
        protected=self.world({'players':{'blue_1':{'x':-23,'z':0}}})
        self.round(protected,'r1',{'red_1':[attack('a')]})
        self.assertEqual(protected.state['players']['blue_1']['life']['vitality']['health'],20)
        self.assertEqual(protected.state['players']['red_1']['cooldowns']['attack'],11)
        self.assertEqual(protected.state['players']['red_1']['life']['effects'],[])
        self.assertEqual(next(f for f in protected.last_facts if f['kind']=='attack_blocked')['payload']['reason'],'protection')

    def test_surviving_killer_receives_capacity_then_drops_overflow(self):
        w=self.world({'players':{
            'red_1':{'x':-25,'z':2,'protection_ticks':0,
                     'inventory':{'wooden_sword':1,'shears':1,'iron':383}},
            'blue_1':{'x':-23,'z':2,'health':4,'protection_ticks':0,
                      'inventory':{'wooden_sword':1,'shears':1,'iron':10}}}})
        self.round(w,'r1',{'red_1':[self.req('hit','attack',{'player_id':'blue_1','life_index':1})]})
        self.assertEqual(w.state['players']['red_1']['life']['inventory']['iron'],384)
        death=next(f['payload'] for f in w.last_facts if f['kind']=='player_died')
        self.assertEqual(death['iron'],{'received':1,'dropped':9,'destroyed':0})
        ground=next(e for e in w.state['entities'].values() if e['source']['kind']=='death')
        self.assertEqual((ground['quantity'],ground['spatial']['x'],ground['spatial']['z']),(9,-25,2))
        self.assertEqual(ground['pickup_ready_at'],1)

    def test_unattributed_void_destroys_unsafe_drop(self):
        w=self.world({'players':{'red_1':{'x':-15.75,'z':0.5,
                    'inventory':{'wooden_sword':1,'shears':1,'iron':5}}}})
        self.round(w,'r1',{'red_1':[self.req('move','move',{'x':1,'z':0})]})
        death=next(f['payload'] for f in w.last_facts if f['kind']=='player_died')
        self.assertIsNone(death['killer_id'])
        self.assertEqual(death['iron'],{'received':0,'dropped':0,'destroyed':5})
        self.assertEqual(w.state['players']['red_1']['life']['kind'],'respawning')
        self.assertEqual(w.state['players']['red_1']['stats']['deaths'],1)

    def test_waiting_player_respawns_after_bed_destroyed(self):
        defs=self.defs(break_ticks=1)
        w=self.world({'players':{
            'red_1':{'x':-25,'z':2,'health':3.2,'armor_tier':1,'protection_ticks':0},
            'blue_1':{'x':-23.5,'z':2,'protection_ticks':0},
            'blue_2':{'x':-23,'z':0.5,'facing_x':1,'facing_z':0,'protection_ticks':0}}},defs)
        self.round(w,'r1',{'blue_1':[self.req('hit','attack',{'player_id':'red_1','life_index':1})],
                           'blue_2':[self.req('bed','break_bed',{'team_id':'red'})]})
        self.assertEqual(w.state['players']['red_1']['life']['respawn_at'],61)
        w.step()
        self.assertEqual(w.state['teams']['red']['bed_state']['destroyed_at'],2)
        for _ in range(59): w.step()
        p=w.state['players']['red_1']
        self.assertEqual(p['life_index'],2)
        self.assertEqual(p['life']['kind'],'alive')
        self.assertEqual(p['life']['vitality']['health'],20)
        self.assertEqual(p['progression']['armor_tier'],1)
        self.assertEqual(p['life']['inventory'],{'wooden_sword':1,'shears':1})
        self.assertEqual(p['life']['held_item'],'wooden_sword')
        self.assertEqual(p['life']['effects'][0]['expires_at'],101)
        self.assertIsNone(p['life']['movement'])
        self.assertIsNone(p['life']['interaction'])

    def test_same_tick_bed_break_precedes_final_death(self):
        defs=self.defs(break_ticks=1)
        w=self.world({'players':{
            'red_1':{'x':-25,'z':2,'health':4,'protection_ticks':0},
            'blue_1':{'x':-23.5,'z':2,'protection_ticks':0},
            'blue_2':{'x':-23,'z':0.5,'facing_x':1,'facing_z':0,'protection_ticks':0}}},defs)
        self.round(w,'r1',{'blue_2':[self.req('bed','break_bed',{'team_id':'red'})]})
        self.round(w,'r2',{'blue_1':[self.req('hit','attack',{'player_id':'red_1','life_index':1})]})
        self.assertEqual(w.state['teams']['red']['bed_state']['destroyed_at'],2)
        self.assertEqual(w.state['players']['red_1']['life']['kind'],'eliminated')
        self.assertEqual(w.state['players']['blue_1']['stats']['final_kills'],1)
        kinds=[f['kind'] for f in w.last_facts]
        self.assertLess(kinds.index('bed_destroyed'),kinds.index('player_died'))

    def test_all_players_mutually_die_draw_or_wait_based_on_beds(self):
        players={}
        for pid in self.roster:
            red=pid.startswith('red')
            players[pid]={'x':-25 if red else -23,'z':2,'health':4,'protection_ticks':0}
        for final in (False,True):
            w=self.world({'players':players,'beds':{'red':not final,'blue':not final}})
            reqs={}
            for pid in self.roster:
                other=('blue_' if pid.startswith('red') else 'red_')+pid[-1]
                reqs[pid]=[self.req('attack','attack',{'player_id':other,'life_index':1})]
            self.round(w,'r1',reqs)
            self.assertTrue(all(p['life']['kind']==('eliminated' if final else 'respawning')
                                for p in w.state['players'].values()))
            if final:
                self.assertEqual(w.state['result'],{'kind':'draw','winner_team_id':None,
                                                    'reason':'mutual_elimination','tick':1})
                before=w.snapshot()
                with self.assertRaisesRegex(ValueError,'Finished'): w.step()
                self.assertEqual(w.snapshot(),before)
            else:
                self.assertIsNone(w.state['result'])

    def test_final_elimination_sets_single_winner(self):
        players={}
        for pid in self.roster:
            red=pid.startswith('red')
            players[pid]={'x':-25 if red else -23,'z':2,'health':20 if red else 4,'protection_ticks':0}
        w=self.world({'players':players,'beds':{'blue':False}})
        self.round(w,'r1',{'red_1':[self.req('a','attack',{'player_id':'blue_1','life_index':1})],
                           'red_2':[self.req('b','attack',{'player_id':'blue_2','life_index':1})]})
        self.assertEqual(w.state['result'],{'kind':'win','winner_team_id':'red','reason':'elimination','tick':1})
        self.assertEqual(sum(f['kind']=='team_eliminated' for f in w.last_facts),1)
        self.assertEqual(restore_snapshot(w.snapshot(),self.definitions).state,w.state)

    def test_void_kill_attribution_and_cross_life_resource_destruction(self):
        players={'red_1':{'x':-17,'z':0.5,'health':4,'protection_ticks':0},
                 'blue_1':{'x':-15.8,'z':0.5,'protection_ticks':0,
                           'inventory':{'wooden_sword':1,'shears':1,'iron':9}},
                 'blue_2':{'x':-17,'z':0.5,'protection_ticks':0}}
        w=self.world({'players':players})
        self.round(w,'r1',{'red_1':[self.req('hit','attack',{'player_id':'blue_1','life_index':1})],
                           'blue_2':[self.req('kill','attack',{'player_id':'red_1','life_index':1})]})
        self.assertEqual(w.state['players']['red_1']['life']['kind'],'respawning')
        w.step()
        death=next(f['payload'] for f in w.last_facts if f['kind']=='player_died' and f['payload']['player_id']=='blue_1')
        self.assertEqual(death['reason'],'void')
        self.assertEqual(death['killer_id'],'red_1')
        self.assertEqual(death['iron'],{'received':0,'dropped':0,'destroyed':9})
        self.assertEqual(w.state['players']['red_1']['stats']['kills'],1)

    def test_game_end_tie_and_player_break_before_global_beds(self):
        defs=self.defs(global_tick=2,end_tick=3,break_ticks=1)
        tied=self.world(definitions=defs)
        for _ in range(3): tied.step()
        self.assertEqual(tied.state['result'],{'kind':'draw','winner_team_id':None,'reason':'game_end','tick':3})
        w=self.world({'players':{'red_1':{'x':19.5,'z':0.5,'facing_x':1,'facing_z':0}}},defs)
        self.round(w,'r1',{'red_1':[self.req('bed','break_bed',{'team_id':'blue'})]})
        w.step()
        self.assertEqual(w.state['execution']['attributed_beds'],{'blue':0,'red':1})
        self.assertEqual(w.state['teams']['red']['bed_state']['destroyed_at'],2)
        self.assertEqual(w.state['teams']['blue']['bed_state']['destroyed_at'],2)
        self.assertLess([f['kind'] for f in w.last_facts].index('bed_destroyed'),
                        [f['kind'] for f in w.last_facts].index('bed_destroyed_globally'))
        w.step()
        self.assertEqual(w.state['result'],{'kind':'win','winner_team_id':'red','reason':'game_end','tick':3})


if __name__=='__main__': unittest.main()
