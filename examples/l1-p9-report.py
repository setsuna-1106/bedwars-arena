"""Audit the completed P9 matrix and summarize outcomes and measurements."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import statistics

from bedwars_arena.agents.scripts import DefensiveCounterattacker, EconomicAttacker
from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.core.world_state import runtime_info


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('matrix', type=Path)
    parser.add_argument('output', type=Path, help='new JSON audit path')
    parser.add_argument('--skip-replay-checks', action='store_true',
                        help='for short coordinator probes; not final acceptance')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f'Audit output already exists: {args.output}')
    config = read_json(args.matrix / 'matrix-config.json')
    summary = read_json(args.matrix / 'matrix-summary.json')
    script = Path(__file__).with_name('l1-p9-matrix.py')
    spec = importlib.util.spec_from_file_location('p9_matrix', script)
    matrix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matrix)
    if config['seeds'] != list(range(101, 111)) or config['seat_configurations'] != {
            label: list(seats) for label, seats in matrix.SEATS.items()}:
        raise ValueError('Unexpected P9 case matrix')
    if config['runtime'] != runtime_info() or config['preset'] is not None or config['decision_interval'] != 1:
        raise ValueError('The standard matrix must be audited with its recorded runtime')
    definitions = load_l1_definitions()
    expected = {f'{seed}-{label}' for seed in config['seeds'] for label in matrix.SEATS}
    listed = {row['name']: row for row in summary['games']}
    if (summary['expected_games'] != 40 or summary['completed_games'] != 40
            or len(summary['games']) != 40 or set(listed) != expected):
        raise ValueError('The complete 40-game matrix is required')
    ids = ('red_1', 'red_2', 'blue_1', 'blue_2')
    rows = []
    groups = defaultdict(list)
    facts_total = Counter()
    fallback_total = Counter()
    for name in sorted(expected):
        seed_text, label = name.split('-')
        seed = int(seed_text)
        seats = dict(zip(ids, matrix.SEATS[label]))
        path = args.matrix / name
        row = matrix.read_row(path, seed=seed, seats=seats, config=config)
        if row != listed[name]:
            raise ValueError(f'Matrix summary disagrees with {name}')
        manifest = read_json(path / 'manifest.json')
        roster = {pid: {'name': (EconomicAttacker if seat.startswith('E') else DefensiveCounterattacker).name,
                        'version': (EconomicAttacker if seat.startswith('E') else DefensiveCounterattacker).version}
                  for pid, seat in seats.items()}
        if manifest['roster'] != roster or manifest['decision_interval'] != 1:
            raise ValueError(f'Policy roster mismatch for {name}')
        initial = read_json(path / 'initial-snapshot.json')['state']
        expected_initial = WorldEngine.create(definitions, seed=seed, match_id=f'p9-{name}').state
        if initial != expected_initial:
            raise ValueError(f'Nonstandard initial world for {name}')
        inputs = [json.loads(line) for line in (path / 'inputs.jsonl').read_text(encoding='utf-8').splitlines()]
        decisions = [[item['observed_tick'], item['player_id'], item['original_requests']] for item in inputs]
        digest = sha256(json.dumps(decisions, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                                   allow_nan=False).encode('utf-8')).hexdigest()
        if digest != row['decision_sha256']:
            raise ValueError(f'Input hash mismatch for {name}')
        facts = Counter(json.loads(line)['kind'] for line in (path / 'events.jsonl').read_text(encoding='utf-8').splitlines())
        fallbacks = Counter(item['fallback'] for item in inputs if item['fallback'])
        if dict(facts) != row['facts'] or dict(fallbacks) != row['fallbacks']:
            raise ValueError(f'Fact or fallback count mismatch for {name}')
        facts_total.update(facts)
        fallback_total.update(fallbacks)
        groups[digest].append(name)
        rows.append(row)
    replay_checks = {}
    if not args.skip_replay_checks:
        for name in ('101-A', '102-B', '103-C', '104-D'):
            report = read_json(args.matrix / f'{name}-replay-check.json')
            checks = report['checks']
            if ({check['from_tick'] for check in checks} != {200, 600}
                    or any(not check['valid'] or check['to_tick'] != listed[name]['summary']['tick'] for check in checks)):
                raise ValueError(f'Incomplete replay verification for {name}')
            replay_checks[name] = checks
    total_ticks = sum(row['summary']['tick'] - row['summary']['start_tick'] for row in rows)
    measured_wall = (args.matrix / 'matrix-summary.json').stat().st_mtime - (args.matrix / 'matrix-config.json').stat().st_mtime
    elapsed = [row['wall_seconds'] for row in rows]
    simulation_seconds = sum(row['simulation_seconds'] for row in rows)
    result = {'schema_version': 1, 'runtime': config['runtime'], 'definitions': config['definitions'],
              'games': len(rows), 'episode_limit_ticks': config['episode_limit_ticks'],
              'terminated': sum(row['summary']['terminated'] for row in rows),
              'truncated': sum(row['summary']['truncated'] for row in rows),
              'faults': {row['name']: row['summary']['failure'] for row in rows if row['summary']['failure'] is not None},
              'fallbacks': dict(fallback_total), 'facts': dict(facts_total),
              'decision_groups': dict(groups), 'total_ticks': total_ticks,
              'game_wall_seconds_min': min(elapsed), 'game_wall_seconds_median': statistics.median(elapsed),
              'game_wall_seconds_max': max(elapsed), 'batch_elapsed_seconds': measured_wall,
              'batch_ticks_per_second': total_ticks / measured_wall if measured_wall > 0 else None,
              'summed_simulation_seconds': simulation_seconds,
              'per_world_ticks_per_second': total_ticks / simulation_seconds if simulation_seconds > 0 else None,
              'measurement_note': 'Batch elapsed uses matrix-config and final summary modification times; '
                                  'it includes other concurrent work, pauses and coordinator overhead.',
              'max_process_peak_rss_bytes': max(row['peak_process_rss_bytes'] for row in rows),
              'record_bytes_total': sum(row['record_bytes'] for row in rows),
              'record_bytes_per_game_min': min(row['record_bytes'] for row in rows),
              'record_bytes_per_game_max': max(row['record_bytes'] for row in rows),
              'replay_checks': replay_checks, 'replay_checks_skipped': args.skip_replay_checks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps({'games': result['games'], 'faults': len(result['faults']),
                      'truncated': result['truncated'], 'output': str(args.output.resolve())}, indent=2))


if __name__ == '__main__':
    main()
