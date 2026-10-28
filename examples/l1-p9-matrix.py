"""Run the fixed P9 standard-start matrix serially, retaining every record.

The 1,100-tick default is an explicit external episode limit, not Game End.
An existing output directory is accepted only with --resume and the exact
same configuration/runtime. Completed games are never executed a second time.
"""

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

from bedwars_arena.agents.scripts import DefensiveCounterattacker, EconomicAttacker
from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.core.world_state import runtime_info
from bedwars_arena.runner.match import MatchRunner


SEATS = {
    'A': ('E1', 'E2', 'D1', 'D2'),
    'B': ('E2', 'E1', 'D2', 'D1'),
    'C': ('D1', 'D2', 'E1', 'E2'),
    'D': ('D2', 'D1', 'E2', 'E1'),
}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def read_row(path, *, seed, seats, config):
    row = json.loads((path / 'matrix-row.json').read_text(encoding='utf-8'))
    manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    if (row['seed'] != seed or row['seats'] != seats or row['summary'] != manifest['summary']
            or manifest['seed_hex'] != f'{seed:016x}' or manifest['runtime'] != config['runtime']
            or manifest['episode_limit_ticks'] != config['episode_limit_ticks']
            or manifest['definitions'] != config['definitions']):
        raise ValueError(f'Existing record does not match the matrix: {path}')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', help='new matrix directory')
    parser.add_argument('--limit', type=int, default=1100, help='external tick limit per game')
    parser.add_argument('--resume', action='store_true', help='continue an existing matching matrix')
    parser.add_argument('--progress-every', type=int, default=200)
    parser.add_argument('--case', help='run one matrix case; used by the parallel coordinator')
    args = parser.parse_args()
    if args.limit < 1 or args.progress_every < 1:
        parser.error('limit and progress-every must be positive')
    root = Path(args.output)
    definitions = load_l1_definitions()
    ids = [player['player_id'] for player in definitions.scenario.data['players']]
    initial = WorldEngine.create(definitions, seed=101, match_id='p9-config')
    config = {'schema_version': 1, 'runtime': runtime_info(),
              'definitions': initial.state['definition_ref'],
              'seeds': list(range(101, 111)), 'seat_configurations': SEATS,
              'episode_limit_ticks': args.limit, 'decision_interval': 1,
              'preset': None, 'recording_level': 'p7_full',
              'platform': platform.platform(), 'logical_cpus': os.cpu_count()}
    # Tuples serialize as lists; normalize before comparing a previous run.
    config = json.loads(json.dumps(config))
    if root.exists():
        if not args.resume:
            raise FileExistsError(f'Output directory already exists: {root}')
        existing = json.loads((root / 'matrix-config.json').read_text(encoding='utf-8'))
        if existing != config:
            raise ValueError('Cannot resume with a different matrix configuration or runtime')
    else:
        if args.resume:
            raise FileNotFoundError(f'Cannot resume a missing matrix: {root}')
        root.mkdir(parents=True)
        write_json(root / 'matrix-config.json', config)
    rows = []
    case_names = {f'{seed}-{label}' for seed in config['seeds'] for label in SEATS}
    if args.case is not None and args.case not in case_names:
        parser.error('case must be one of 101-A through 110-D')
    for seed in config['seeds']:
        for label, session_names in SEATS.items():
            name = f'{seed}-{label}'
            if args.case is not None and name != args.case:
                continue
            path = root / name
            seats = dict(zip(ids, session_names))
            if path.exists():
                row = read_row(path, seed=seed, seats=seats, config=config)
                print(f'{name}: already recorded', file=sys.stderr, flush=True)
            else:
                print(f'{name}: starting standard game', file=sys.stderr, flush=True)
                world = WorldEngine.create(definitions, seed=seed, match_id=f'p9-{name}')
                policies = {pid: (EconomicAttacker() if session.startswith('E') else DefensiveCounterattacker())
                            for pid, session in seats.items()}
                runner = MatchRunner(world, policies, episode_limit_ticks=args.limit)
                start = time.perf_counter()
                try:
                    while not (runner.terminated or runner.truncated):
                        runner.decision_step()
                        tick = runner.world.state['tick']
                        if tick % args.progress_every == 0:
                            print(f'{name}: tick {tick}', file=sys.stderr, flush=True)
                except Exception:
                    runner.write_artifacts(path)
                    raise
                simulation_seconds = time.perf_counter() - start
                runner.write_artifacts(path)
                wall_seconds = time.perf_counter() - start
                facts = Counter(fact['kind'] for fact in runner.events)
                decisions = [[item['observed_tick'], item['player_id'], item['original_requests']]
                             for item in runner.inputs]
                action_hash = sha256(json.dumps(decisions, ensure_ascii=False, sort_keys=True,
                                                separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                row = {'name': name, 'seed': seed, 'seats': seats, 'summary': runner.summary(),
                       'fallbacks': Counter(item['fallback'] for item in runner.inputs if item['fallback']),
                       'facts': dict(facts), 'decision_sha256': action_hash,
                       'simulation_seconds': simulation_seconds, 'wall_seconds': wall_seconds,
                       'peak_process_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024,
                       'record_bytes': sum(file.stat().st_size for file in path.rglob('*') if file.is_file())}
                write_json(path / 'matrix-row.json', row)
                print(f'{name}: tick {row["summary"]["tick"]}, '
                      f'terminated={row["summary"]["terminated"]}, '
                      f'truncated={row["summary"]["truncated"]}, '
                      f'{wall_seconds:.1f}s', file=sys.stderr, flush=True)
            rows.append(row)
            if args.case is None:
                write_json(root / 'matrix-summary.json', {'expected_games': 40, 'completed_games': len(rows),
                                                           'games': rows})
    print(json.dumps({'expected_games': 40, 'completed_games': len(rows), 'output': str(root.resolve())},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
