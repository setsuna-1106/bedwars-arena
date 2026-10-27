"""P0 definition, geometry, identity and installed-data acceptance tests."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bedwars_arena.core.definitions import (L1DefinitionError, load_l1_definitions,
                                            validate_l1_definitions)


class L1DefinitionTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_l1_definitions()
        self.profile = self.bundle.profile.data
        self.map = self.bundle.map.data
        self.scenario = self.bundle.scenario.data

    def validate(self):
        return validate_l1_definitions(self.profile, self.map, self.scenario)

    def test_adopted_configuration_and_fixed_map(self):
        profile, map_data = self.profile, self.map
        self.assertEqual((profile['game']['teams'], profile['game']['players_per_team'],
                          profile['game']['ticks_per_second']), (2, 2, 20))
        self.assertFalse(any(profile['features'].values()))
        self.assertEqual(profile['shop']['products']['wool']['cost'], 4)
        self.assertEqual(profile['shop']['products']['wool']['quantity'], 16)
        self.assertEqual(profile['shop']['products']['iron_sword']['cost'], 12)
        self.assertEqual(profile['shop']['products']['armor_1']['cost'], 20)
        self.assertEqual(profile['inventory']['initial_items'], {'wooden_sword': 1, 'shears': 1})
        self.assertEqual(profile['building']['recovery_tool'], 'shears')
        self.assertEqual((profile['building']['placement_duration_ticks'],
                          profile['building']['wool_break_duration_ticks'],
                          profile['building']['bed_break_duration_ticks']), (4, 20, 40))
        self.assertEqual((profile['generators']['base']['period_ticks'],
                          profile['generators']['central']['period_ticks']), (20, 10))
        self.assertEqual((profile['schedule']['global_bed_destruction_tick'],
                          profile['schedule']['game_end_tick']), (9600, 12000))
        self.assertEqual(map_data['bounds'], {'min_x': -32, 'max_x': 32, 'min_z': -16, 'max_z': 16})
        self.assertEqual([t['bed'] for t in map_data['teams']], [{'x': -22, 'z': 0}, {'x': 21, 'z': 0}])
        self.assertEqual([t['spawn'] for t in map_data['teams']], [{'x': -25, 'z': 0}, {'x': 25, 'z': 0}])
        self.assertEqual([g['position'] for g in map_data['generators']],
                         [{'x': -25, 'y': 0.125, 'z': -3}, {'x': 0, 'y': 0.125, 'z': 0},
                          {'x': 25, 'y': 0.125, 'z': -3}])
        self.assertEqual([p['player_id'] for p in self.scenario['players']],
                         ['red_1', 'red_2', 'blue_1', 'blue_2'])

    def test_hashes_are_stable_and_separate(self):
        self.assertEqual(self.bundle.hashes, {
            'profile': '3e74d9648c77af874f36789e6b090b0935bd7154ad280eb01e546352c78b5fc5',
            'map': '0ea23c72a673b530a0d1ff9d3e68d1654c38f6bd48891a4583befa6314b47f6f',
            'scenario': '2af3373da36d1f0918d2d2e85429a6e7971e288c61a61b185973c2dc390e9dd8'})
        load_l1_definitions(expected_hashes=self.bundle.hashes)
        self.profile['shop']['products']['wool']['cost'] = 5
        changed = self.validate()
        self.assertNotEqual(changed.profile.sha256, self.bundle.profile.sha256)
        self.assertEqual(changed.map.sha256, self.bundle.map.sha256)
        with self.assertRaisesRegex(L1DefinitionError, 'profile content hash mismatch'):
            validate_l1_definitions(self.profile, self.map, self.scenario,
                                    expected_hashes=self.bundle.hashes)
        with self.assertRaisesRegex(L1DefinitionError, 'expected hashes'):
            load_l1_definitions(expected_hashes={'map': self.bundle.map.sha256})

    def test_definitions_are_detached(self):
        p = self.bundle.profile.data
        p['shop']['products']['wool']['cost'] = 999
        self.assertEqual(self.bundle.profile.data['shop']['products']['wool']['cost'], 4)
        with self.assertRaises(FrozenInstanceError):
            self.bundle.profile.sha256 = 'modified'

    def test_explicit_paths_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in [('profile', self.profile), ('map', self.map), ('scenario', self.scenario)]:
                (root / f'{name}.json').write_text(json.dumps(data, indent=4), encoding='utf-8')
            loaded = load_l1_definitions(profile_path=root / 'profile.json', map_path=root / 'map.json',
                                         scenario_path=root / 'scenario.json')
            self.assertEqual(loaded.hashes, self.bundle.hashes)
            (root / 'profile.json').write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaisesRegex(L1DefinitionError, 'duplicate JSON key'):
                load_l1_definitions(profile_path=root / 'profile.json')
            (root / 'profile.json').write_text('{"number": NaN}')
            with self.assertRaisesRegex(L1DefinitionError, 'non-finite'):
                load_l1_definitions(profile_path=root / 'profile.json')
            with self.assertRaisesRegex(L1DefinitionError, 'cannot read JSON'):
                load_l1_definitions(profile_path=root / 'missing.json')

    def test_cli_rejects_invalid_definition_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            map_path = Path(directory) / 'map.json'
            self.map['teams'][0]['spawn']['x'] = -16.1
            map_path.write_text(json.dumps(self.map), encoding='utf-8')
            result = subprocess.run([sys.executable, '-I', '-m', 'bedwars_arena', 'validate-l1',
                                     '--map', str(map_path)], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('spawn body not fully supported', result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_missing_unknown_and_wrong_types(self):
        mutations = [
            lambda p: p['budget'].pop('work_items_per_tick'),
            lambda p: p['game'].update({'extra': 1}),
            lambda p: p['game'].update({'ticks_per_second': True}),
            lambda p: p['physics'].update({'player_width': float('nan')}),
            lambda p: p['physics'].update({'player_width': float('inf')}),
            lambda p: p['physics'].update({'player_width': 10**1000}),
            lambda p: p['budget'].update({'ground_entities': 0}),
            lambda p: p.update({'schema_version': 2}),
            lambda p: p['features'].update({'traps': True}),
            lambda p: p['shop'].update({'requires_line_of_sight': True}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.profile = self.bundle.profile.data
                mutate(self.profile)
                with self.assertRaises(L1DefinitionError):
                    self.validate()

    def test_parameter_consistency(self):
        mutations = [
            lambda p: p['physics'].update({'speed_blocks_per_tick': 0.3}),
            lambda p: p['physics'].update({'velocity_zero_tolerance': 0.1}),
            lambda p: p['inventory'].update({'stack_capacity': 1}),
            lambda p: p['inventory']['initial_items'].update({'shears': 0}),
            lambda p: p['inventory'].update({'initial_held_item': 'iron_sword'}),
            lambda p: p['shop']['products']['wool'].update({'cost': -1}),
            lambda p: p['shop']['products']['armor_1'].update({'quantity': 2}),
            lambda p: p['building'].update({'bridge_y': 0}),
            lambda p: p['generators']['base'].update({'period_ticks': 0}),
            lambda p: p['generators']['central'].update({'period_ticks': 100}),
            lambda p: p['ground_items'].update({'center_y': 10}),
            lambda p: p['ground_items'].update({'drop_pickup_delay_ticks': 2400}),
            lambda p: p['combat'].update({'armor_1_reduction': 1.0}),
            lambda p: p['schedule'].update({'game_end_tick': 9600}),
            lambda p: p['protocol'].update({'action_version': 2}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.profile = self.bundle.profile.data
                mutate(self.profile)
                with self.assertRaises(L1DefinitionError):
                    self.validate()

    def test_invalid_map_geometry(self):
        mutations = [
            lambda m: m['terrain'].update({'wall_y': 1}),
            lambda m: m['terrain']['islands'][0]['bounds'].update({'min_x': -40}),
            lambda m: m['terrain']['islands'][0]['bounds'].update({'max_x': 0}),
            lambda m: m['teams'][0]['spawn'].update({'x': -16.1}),
            lambda m: m['teams'][0]['spawn'].update({'x': -21.5, 'z': 0.5}),
            lambda m: m['teams'][0]['facing'].update({'x': 0}),
            lambda m: m['teams'][0]['bed'].update({'x': -15}),
            lambda m: m['generators'][0]['position'].update({'y': 0.5}),
            lambda m: m['protected_regions'][0]['bounds'].update({'min_x': -25}),
            lambda m: m['protected_regions'][0].update({'target_id': 'unknown'}),
            lambda m: m['generators'][0].update({'team_id': 'blue'}),
            lambda m: m['teams'][1].update({'team_id': 'red'}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.map = self.bundle.map.data
                mutate(self.map)
                with self.assertRaises(L1DefinitionError):
                    self.validate()

    def test_spawn_with_tiny_unsupported_gap_is_rejected(self):
        # A real positive gap cannot be rounded away by an area comparison.
        self.map['teams'][0]['spawn']['x'] = -16.3 + 1e-10
        with self.assertRaisesRegex(L1DefinitionError, 'spawn body not fully supported'):
            self.validate()

    def test_scenario_reference_roster_and_version(self):
        mutations = [
            lambda s: s['map'].update({'version': '2'}),
            lambda s: s['profile'].update({'id': 'missing'}),
            lambda s: s['players'][0].update({'team_id': 'unknown'}),
            lambda s: s['players'][0].update({'player_id': 'red_2'}),
            lambda s: s['players'].pop(),
            lambda s: s.update({'initial_tick': 1}),
            lambda s: s.update({'initial_life_index': 0}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.scenario = self.bundle.scenario.data
                mutate(self.scenario)
                with self.assertRaises(L1DefinitionError):
                    self.validate()

    def test_continuous_fields_are_not_limited_to_integers(self):
        self.profile['shop']['range_blocks'] = 2.5
        self.profile['physics']['speed_blocks_per_second'] = 5.0
        self.profile['physics']['speed_blocks_per_tick'] = 0.25
        self.assertEqual(self.validate().profile.data['shop']['range_blocks'], 2.5)

    def test_batch_yield_and_ground_stack_can_exceed_other_limits(self):
        # W09 clips generator yield to remaining capacity; pickup can transfer
        # part of a ground entity even if its limit exceeds a backpack stack.
        self.profile['generators']['base']['quantity'] = 65
        self.profile['generators']['central']['quantity'] = 40
        self.profile['ground_items']['entity_limits']['iron'] = 128
        self.assertEqual(self.validate().profile.data['generators']['base']['quantity'], 65)


if __name__ == '__main__':
    unittest.main()
