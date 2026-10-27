"""L1 P2 geometry, swept motion, P07 knockback and void candidates."""
from copy import deepcopy
import math
import random
import unittest

from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.geometry import AABB, Vec2, distance, distance_to_aabb, grid_cell
from bedwars_arena.core.physics import add_knockback, combined_velocity, move_player
from bedwars_arena.core.terrain import Terrain
from bedwars_arena.core.transactions import ChangeSet
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.replay.snapshot import restore_snapshot


class GeometryAndMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions=load_l1_definitions()
        cls.physics=cls.definitions.profile.data['physics']

    def terrain(self, ground=None, walls=(), beds=()):
        if ground is None:
            ground={(x,z) for x in range(-6,7) for z in range(-6,7)}
        return Terrain(frozenset(ground),frozenset(walls),tuple(beds),(-10,10,-10,10))

    def move(self,x,z,dx,dz,*,kx=0,kz=0,terrain=None,physics=None):
        return move_player(position=Vec2(x,z),direction=Vec2(dx,dz),knockback=Vec2(kx,kz),
                           terrain=terrain or self.terrain(),physics=physics or self.physics)

    def test_half_open_cells_and_contact_geometry(self):
        self.assertEqual([grid_cell(x) for x in (-1.0,-0.2,0.0,1.0)],[-1,-1,0,1])
        box=AABB.centered(Vec2(0.5,0.5),0.6,0.6)
        self.assertFalse(box.overlaps(AABB(0.8,1.8,0,1)))
        self.assertAlmostEqual(distance_to_aabb(Vec2(1,0.5),box),0.2)
        self.assertAlmostEqual(distance(Vec2(0,0),Vec2(3,4)),5)
        one=self.terrain(ground={(0,0)})
        self.assertTrue(one.supported(AABB.centered(Vec2(1.299,0.5),0.6,0.6)))
        self.assertFalse(one.supported(AABB.centered(Vec2(1.3,0.5),0.6,0.6)))
        self.assertFalse(one.supported(AABB.centered(Vec2(1.3,1.3),0.6,0.6)))

    def test_terrain_copies_mutable_inputs(self):
        ground={(0,0)}
        walls={(1,0)}
        beds=[['red',2,0]]
        terrain=Terrain(ground,walls,beds,(-5,5,-5,5))
        ground.clear();walls.clear();beds[0][1]=4
        self.assertEqual(terrain.ground,frozenset({(0,0)}))
        self.assertEqual(terrain.walls,frozenset({(1,0)}))
        self.assertEqual(terrain.beds,(('red',2,0),))

    def test_straight_and_diagonal_same_speed(self):
        straight=self.move(0.5,0.5,1,0)
        diagonal=self.move(0.5,0.5,1,1)
        self.assertAlmostEqual(straight.position.x,0.7)
        self.assertAlmostEqual(distance(Vec2(0.5,0.5),diagonal.position),0.2)
        self.assertAlmostEqual(diagonal.position.x,0.5+0.2/math.sqrt(2))
        huge=self.move(0.5,0.5,1e308,1e308)
        self.assertAlmostEqual(huge.position.x,diagonal.position.x)
        with self.assertRaises(ValueError):
            self.move(0.5,0.5,float('nan'),0)

    def test_sweep_contact_sliding_and_negative_coordinates(self):
        terrain=self.terrain(walls={(1,0),(-2,0)})
        hit=self.move(0.5,0.5,1,0,terrain=terrain)
        self.assertAlmostEqual(hit.position.x,0.7)
        slide=self.move(hit.position.x,hit.position.z,1,1,terrain=terrain)
        self.assertAlmostEqual(slide.position.x,0.7)
        self.assertAlmostEqual(slide.position.z,0.5+0.2/math.sqrt(2))
        self.assertFalse(slide.void_candidate)
        left=self.move(-0.5,0.5,-1,0,terrain=terrain)
        self.assertAlmostEqual(left.position.x,-0.7)
        with self.assertRaisesRegex(ValueError,'inside'):
            self.move(1.1,0.5,1,0,terrain=terrain)

    def test_contact_rounding_never_enters_wall(self):
        terrain=self.terrain(walls={(1,-2)})
        hit=self.move(2.4,-1.5,-1,0,terrain=terrain)
        self.assertAlmostEqual(hit.position.x,2.3)
        self.assertTrue(terrain.free(AABB.centered(hit.position,0.6,0.6)))
        # A second tick can move tangentially without treating contact as penetration.
        slide=self.move(hit.position.x,hit.position.z,0,1,terrain=terrain)
        self.assertTrue(terrain.free(AABB.centered(slide.position,0.6,0.6)))

    def test_corner_simultaneous_faces_and_high_speed_do_not_tunnel(self):
        corner=self.terrain(walls={(1,0),(0,1)})
        hit=self.move(0.65,0.65,1,1,terrain=corner)
        self.assertAlmostEqual(hit.position.x,0.7)
        self.assertAlmostEqual(hit.position.z,0.7)
        self.assertEqual({(nx,nz) for _,nx,nz in hit.contacts},{(-1,0),(0,-1)})
        fast=deepcopy(self.physics); fast['speed_blocks_per_tick']=5.0
        hit=self.move(-1.0,0.5,1,0,terrain=self.terrain(walls={(1,0)}),physics=fast)
        self.assertAlmostEqual(hit.position.x,0.7)
        self.assertFalse(hit.void_candidate)

    def test_iteration_limit_stops_remaining_motion(self):
        physics=deepcopy(self.physics);physics['collision_iterations_per_tick']=1
        hit=self.move(0.65,0.5,1,1,terrain=self.terrain(walls={(1,0)}),physics=physics)
        self.assertTrue(hit.iteration_limit_reached)
        self.assertAlmostEqual(hit.position.x,0.7)
        self.assertGreater(hit.position.z,0.5)
        self.assertLess(hit.position.z,0.5+0.2/math.sqrt(2))

    def test_knockback_control_decay_cap_and_wall_removal(self):
        result=self.move(0.5,0.5,-1,0,kx=0.3)
        self.assertAlmostEqual(result.position.x,0.74)  # 0.3 - 0.2*0.3
        self.assertAlmostEqual(result.knockback.x,0.225)
        sideways=combined_velocity(Vec2(0,1),Vec2(0.3,0),self.physics)
        self.assertAlmostEqual(sideways.z,0.15)
        self.assertAlmostEqual(add_knockback(Vec2(0.5,0),Vec2(0.3,0),self.physics).x,0.6)
        wall=self.move(0.5,0.5,0,0,kx=0.3,kz=0.1,terrain=self.terrain(walls={(1,0)}))
        self.assertAlmostEqual(wall.position.x,0.7)
        self.assertAlmostEqual(wall.knockback.x,0)
        self.assertAlmostEqual(wall.knockback.z,0.075)
        tiny=self.move(0.5,0.5,0,0,kx=0.0049)
        self.assertEqual(tiny.knockback,Vec2(0,0))
        decay=self.move(0.5,0.5,0,0,kx=0.006)
        self.assertEqual(decay.knockback,Vec2(0,0))

    def test_loss_along_path_cannot_cross_gap_even_when_end_has_ground(self):
        terrain=self.terrain(ground={(0,0),(2,0)})
        start=Vec2(1.25,0.5)
        end=Vec2(2.05,0.5)
        self.assertTrue(terrain.supported(AABB.centered(start,0.6,0.6)))
        self.assertTrue(terrain.supported(AABB.centered(end,0.6,0.6)))
        result=self.move(start.x,start.z,1,0,kx=0.6,terrain=terrain)
        self.assertTrue(result.void_candidate)
        self.assertAlmostEqual(result.position.x,1.3)
        self.assertLess(result.position.x,end.x)
        unsupported=self.move(1.3,0.5,0,0,terrain=terrain)
        self.assertTrue(unsupported.void_candidate)

    def test_line_of_sight_and_safe_drop_share_real_obstacles(self):
        terrain=self.terrain(ground={(0,0),(1,0),(2,0)},walls={(1,0)},beds=(('blue',2,0),))
        self.assertFalse(terrain.line_of_sight(Vec2(0.5,0.5),Vec2(2.5,0.5)))
        self.assertTrue(terrain.line_of_sight(Vec2(0.5,0),Vec2(2.5,0)))  # wall edge only
        self.assertTrue(terrain.line_of_sight(Vec2(0.5,0.5),Vec2(1.5,0.5),ignore=(1,0,'wall','')))
        self.assertTrue(terrain.safe_drop(Vec2(0.5,0.5),0.25,0.25))
        self.assertFalse(terrain.safe_drop(Vec2(1.5,0.5),0.25,0.25))
        self.assertFalse(terrain.safe_drop(Vec2(3.5,0.5),0.25,0.25))
        self.assertFalse(terrain.safe_drop(Vec2(2.5,0.5),0.25,0.25))

    def test_bed_collision_comes_from_team_bed_state(self):
        world=WorldEngine.create(self.definitions,seed=7,match_id='bed-test')
        state=world.state
        present=Terrain.from_world(state,self.definitions.map.data)
        bed_box=AABB(-22,-21,0,1)
        self.assertFalse(present.free(bed_box))
        state['teams']['red']['bed_state']={'status':'destroyed','destroyed_at':0}
        destroyed=Terrain.from_world(state,self.definitions.map.data)
        self.assertTrue(destroyed.free(bed_box))
        self.assertTrue(destroyed.supported(bed_box))

    def test_randomized_contacts_never_end_in_wall_interior(self):
        rng=random.Random(12345)
        ground={(x,z) for x in range(-8,9) for z in range(-8,9)}
        checked=0
        for _ in range(300):
            walls={(rng.randrange(-5,6),rng.randrange(-5,6)) for _ in range(14)}
            terrain=self.terrain(ground=ground,walls=walls)
            point=Vec2(rng.uniform(-4,4),rng.uniform(-4,4))
            if not terrain.free(AABB.centered(point,0.6,0.6)):
                continue
            physics=deepcopy(self.physics)
            physics['speed_blocks_per_tick']=rng.uniform(0,2)
            result=move_player(position=point,direction=Vec2(rng.uniform(-1,1),rng.uniform(-1,1)),
                               knockback=Vec2(0,0),terrain=terrain,physics=physics)
            x,z=result.position.x,result.position.z
            # Independent strict-overlap assertion, not the solver's sweep test.
            for wx,wz in walls:
                overlap=(x-0.3 < wx+1 and wx < x+0.3 and z-0.3 < wz+1 and wz < z+0.3)
                self.assertFalse(overlap, (point,result.position,(wx,wz)))
            checked+=1
        self.assertGreater(checked,180)

    def test_wall_plan_cannot_commit_player_penetration(self):
        from bedwars_arena.core.transactions import apply_plan
        from bedwars_arena.core.world_state import validate_state
        world=WorldEngine.create(self.definitions,seed=3,match_id='wall-test')
        state=world.state
        plan=ChangeSet.from_state(state)
        plan.terrain['-25,0,0']={'instance_id':plan.allocate(),'kind':'wool'}
        with self.assertRaisesRegex(ValueError,'penetrates'):
            apply_plan(state,plan,budget=self.definitions.profile.data['budget'],
                       validate=lambda candidate:validate_state(candidate,self.definitions))
        self.assertNotIn('-25,0,0',state['terrain'])

    def test_world_movement_void_intent_is_not_a_death_fact_and_restores(self):
        class OneMove(WorldEngine):
            def _phase_plan(self,tick,phase):
                if tick==1 and phase==20:
                    plan=ChangeSet.from_state(self._state)
                    player=deepcopy(self._state['players']['red_1'])
                    player['life']['movement']={'action_id':plan.allocate(),'kind':'move','target':None,
                         'params':{'x':1,'z':0},'started_at':1,'progress':0,'phase':'active'}
                    plan.players['red_1']=player
                    return plan
                return super()._phase_plan(tick,phase)
        preset={'players':{'red_1':{'x':-15.75,'z':0,'knockback_x':0.6}}}
        base=WorldEngine.create(self.definitions,seed=1,match_id='physics-test',preset=preset)
        world=OneMove(self.definitions,base.state)
        world.step()
        state=world.state
        self.assertEqual(state['tick'],1)
        self.assertAlmostEqual(state['players']['red_1']['life']['spatial']['x'],-15.7)
        self.assertEqual(state['players']['red_1']['life']['kind'],'alive')
        self.assertEqual(len(state['execution']['pending_deaths']),1)
        self.assertEqual(state['execution']['pending_deaths'][0]['reason'],'void')
        self.assertEqual(state['execution']['pending_intents'],[])
        self.assertEqual(world.last_facts,())
        restored=restore_snapshot(world.snapshot(),self.definitions)
        self.assertEqual(world.step(),restored.step())
        self.assertEqual(len(world.state['execution']['pending_deaths']),1)
        self.assertAlmostEqual(world.state['players']['red_1']['life']['spatial']['x'],-15.7)

    def test_players_are_not_collision_obstacles(self):
        class Cross(WorldEngine):
            def _phase_plan(self,tick,phase):
                if tick==1 and phase==20:
                    plan=ChangeSet.from_state(self._state)
                    for pid,direction in [('red_1',1),('red_2',-1)]:
                        player=deepcopy(self._state['players'][pid])
                        player['life']['movement']={'action_id':plan.allocate(),'kind':'move','target':None,
                              'params':{'x':direction,'z':0},'started_at':1,'progress':0,'phase':'active'}
                        plan.players[pid]=player
                    return plan
                return super()._phase_plan(tick,phase)
        preset={'players':{'red_1':{'x':-25.2},'red_2':{'x':-24.8}}}
        base=WorldEngine.create(self.definitions,seed=2,match_id='cross',preset=preset)
        world=Cross(self.definitions,base.state)
        world.step()
        for pid in ('red_1','red_2'):
            self.assertAlmostEqual(world.state['players'][pid]['life']['spatial']['x'],-25.0)


if __name__=='__main__':
    unittest.main()
