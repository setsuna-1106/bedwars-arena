"""Run four P7 samples sequentially and verify early/middle snapshots.

A/B and C/D swap independent sessions of the same two deterministic policies;
this is a reproducibility test, not independent random evidence of policy strength.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

from bedwars_arena.agents.scripts import DefensiveCounterattacker, EconomicAttacker
from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.replay.verify import verify_run
from bedwars_arena.runner.match import MatchRunner


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',help='new validation directory')
    parser.add_argument('--existing-a',help='reuse an already recorded seed-101 A match')
    parser.add_argument('--limit',type=int,default=1100,help='episode tick limit (default 1100)')
    args=parser.parse_args()
    root=Path(args.output);root.mkdir(parents=True,exist_ok=False)
    definitions=load_l1_definitions()
    preset=json.loads(Path(__file__).with_name('l1-controlled-2v2.json').read_text(encoding='utf-8'))
    cases=[(101,'A',['E1','E2','D1','D2']), (102,'B',['E2','E1','D2','D1']),
           (103,'C',['D1','D2','E1','E2']), (104,'D',['D2','D1','E2','E1'])]
    ids=[p['player_id'] for p in definitions.scenario.data['players']]
    results=[]
    for seed,label,seats in cases:
        name=f'{seed}-{label}';path=root/name
        print(f'{name}: running',file=sys.stderr,flush=True)
        if label=='A' and args.existing_a:
            source=Path(args.existing_a)
            meta=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
            expected=['economic-attacker','economic-attacker','defensive-counterattacker','defensive-counterattacker']
            if meta['seed_hex']!=f'{seed:016x}' or [meta['roster'][p]['name'] for p in ids]!=expected:
                raise ValueError('Existing A record has the wrong seed or policies')
            shutil.copytree(source,path)
        else:
            world=WorldEngine.create(definitions,seed=seed,preset=preset)
            policies={pid:(EconomicAttacker() if seat.startswith('E') else DefensiveCounterattacker())
                      for pid,seat in zip(ids,seats)}
            runner=MatchRunner(world,policies,episode_limit_ticks=args.limit)
            while not (runner.terminated or runner.truncated):
                runner.decision_step()
                if runner.world.state['tick']%200==0:
                    print(f'{name}: tick {runner.world.state["tick"]}',file=sys.stderr,flush=True)
            runner.write_artifacts(path)
        checkpoints=(0,200,400) if label=='A' else (200,400)
        reports=[]
        for tick in checkpoints:
            print(f'{name}: verifying from tick {tick}',file=sys.stderr,flush=True)
            reports.append(verify_run(path,from_tick=tick))
        summary=json.loads((path/'manifest.json').read_text(encoding='utf-8'))['summary']
        results.append({'sample':name,'seed':seed,'seats':dict(zip(ids,seats)),
                        'summary':summary,'replays':reports})
        (root/'validation-summary.json').write_text(json.dumps({'samples':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'{name}: valid through tick {summary["tick"]}',file=sys.stderr,flush=True)
    print(json.dumps({'samples':results},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
