"""P9 failure injection at world publication and transaction boundaries."""

from copy import deepcopy
import unittest

from bedwars_arena.core.definitions import load_l1_definitions, validate_l1_definitions
from bedwars_arena.core.messages import ScheduledTask
from bedwars_arena.core.transactions import ChangeSet, apply_plan
from bedwars_arena.core.world import WorldEngine, WorldFault
from bedwars_arena.core.world_state import validate_state


class DeliveryFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defs = load_l1_definitions()

    def test_unknown_task_faults_without_consuming_or_publishing_the_tick(self):
        state = WorldEngine.create(self.defs, seed=101, match_id='p9-unknown-task').state
        plan = ChangeSet.from_state(state)
        task = ScheduledTask.create(task_id=plan.allocate(), kind='unimplemented_task',
                                    created_at=0, execute_at=1, phase=0, source_order=0, payload={})
        plan.add_tasks.append(task)
        changed, _ = apply_plan(state, plan, budget=self.defs.profile.data['budget'],
                                validate=lambda value: validate_state(value, self.defs, boundary=True))
        world = WorldEngine(self.defs, changed)
        before = world.snapshot()
        with self.assertRaisesRegex(WorldFault, 'No handler for scheduled task'):
            world.step()
        self.assertEqual(world.snapshot(), before)
        self.assertEqual(world.last_facts, ())
        self.assertIn(task.to_dict(), world._state['execution']['pending_tasks'])
        with self.assertRaisesRegex(WorldFault, 'Faulted world cannot advance'):
            world.step()

    def test_work_budget_exhaustion_keeps_last_published_boundary(self):
        profile = deepcopy(self.defs.profile.data)
        profile['budget']['work_items_per_tick'] = 1
        defs = validate_l1_definitions(profile, self.defs.map.data, self.defs.scenario.data)
        world = WorldEngine.create(defs, seed=101, match_id='p9-work-budget')
        before = world.snapshot()
        with self.assertRaisesRegex(WorldFault, 'Work budget exceeded'):
            world.step()
        self.assertEqual(world.snapshot(), before)
        self.assertEqual(world.last_facts, ())
        self.assertIsNotNone(world.fault)
        with self.assertRaisesRegex(WorldFault, 'Faulted world cannot advance'):
            world.step()


if __name__ == '__main__':
    unittest.main()
