"""Verify chosen indexed snapshots of a P9 record without calling its policies."""

import argparse
import json
from pathlib import Path
import time

from bedwars_arena.replay.verify import verify_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('output', type=Path, help='new JSON report path')
    parser.add_argument('--ticks', type=int, nargs='+', default=[200, 600])
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f'Report already exists: {args.output}')
    reports = []
    for tick in args.ticks:
        start = time.perf_counter()
        result = verify_run(args.record, from_tick=tick)
        result['verification_seconds'] = time.perf_counter() - start
        reports.append(result)
        print(f"tick {tick}: verified through {result['to_tick']}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump({'record': str(args.record.resolve()), 'checks': reports}, output,
                  ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')


if __name__ == '__main__':
    main()
