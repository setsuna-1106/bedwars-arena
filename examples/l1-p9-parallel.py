"""Continue an existing P9 matrix with at most two isolated game processes.

Each game still advances one world serially. This coordinator only schedules
independent cases, preserves individual records, and stops launching cases on
the first failure. Start it only after the serial matrix process has stopped.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='existing P9 matrix directory')
    args = parser.parse_args()
    root = args.output.resolve()
    config = json.loads((root / 'matrix-config.json').read_text(encoding='utf-8'))
    script = Path(__file__).with_name('l1-p9-matrix.py')
    spec = importlib.util.spec_from_file_location('p9_matrix', script)
    matrix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matrix)
    ids = ['red_1', 'red_2', 'blue_1', 'blue_2']
    cases = [(seed, label, dict(zip(ids, seats)))
             for seed in config['seeds'] for label, seats in matrix.SEATS.items()]
    rows = {}
    pending = []
    for seed, label, seats in cases:
        name = f'{seed}-{label}'
        path = root / name
        if path.exists():
            rows[name] = matrix.read_row(path, seed=seed, seats=seats, config=config)
        else:
            pending.append((seed, label, seats))

    def save_summary():
        ordered = [rows[f'{seed}-{label}'] for seed, label, _ in cases if f'{seed}-{label}' in rows]
        matrix.write_json(root / 'matrix-summary.json',
                          {'expected_games': 40, 'completed_games': len(ordered), 'games': ordered})

    save_summary()
    running = {}
    failure = None
    try:
        while pending or running:
            while failure is None and pending and len(running) < 2:
                seed, label, seats = pending.pop(0)
                name = f'{seed}-{label}'
                command = [sys.executable, str(script), str(root), '--resume', '--case', name,
                           '--limit', str(config['episode_limit_ticks'])]
                print(f'{name}: launching independent worker', file=sys.stderr, flush=True)
                running[name] = (subprocess.Popen(command), seed, seats)
            for name, (process, seed, seats) in list(running.items()):
                returncode = process.poll()
                if returncode is None:
                    continue
                del running[name]
                if returncode:
                    failure = (name, returncode)
                    print(f'{name}: worker failed ({returncode}); no new cases will start',
                          file=sys.stderr, flush=True)
                else:
                    try:
                        rows[name] = matrix.read_row(root / name, seed=seed, seats=seats, config=config)
                        save_summary()
                    except (OSError, ValueError, KeyError) as error:
                        failure = (name, str(error))
                        print(f'{name}: invalid record ({error}); no new cases will start',
                              file=sys.stderr, flush=True)
                    else:
                        print(f'{name}: complete; {len(rows)}/40 recorded', file=sys.stderr, flush=True)
            if failure is not None and not running:
                break
            if running:
                time.sleep(0.5)
    except KeyboardInterrupt:
        for process, _, _ in running.values():
            process.terminate()
        for process, _, _ in running.values():
            process.wait()
        raise
    if failure is not None:
        raise SystemExit(f'P9 matrix stopped after worker failure: {failure[0]} ({failure[1]})')
    print(json.dumps({'expected_games': 40, 'completed_games': len(rows), 'output': str(root)},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
