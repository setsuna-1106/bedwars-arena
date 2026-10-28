"""Measure serial L1 throughput with full P7 recording and unchanged rule checks."""
import argparse
from pathlib import Path
import json
import os
import platform
import resource
import sys
import time

from bedwars_arena.agents.scripts import DefensiveCounterattacker, EconomicAttacker
from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.core.world_state import runtime_info
from bedwars_arena.runner.match import MatchRunner


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticks',type=int,default=200)
    parser.add_argument('--seed',type=int,default=101)
    parser.add_argument('--output',required=True,help='new output directory')
    args=parser.parse_args()
    if args.ticks<1:parser.error('ticks must be positive')
    definitions=load_l1_definitions();world=WorldEngine.create(definitions,seed=args.seed)
    teams=[t['team_id'] for t in definitions.map.data['teams']]
    policies={p['player_id']:(EconomicAttacker() if p['team_id']==teams[0] else DefensiveCounterattacker())
              for p in definitions.scenario.data['players']}
    runner=MatchRunner(world,policies,episode_limit_ticks=args.ticks)
    start=time.perf_counter();summary=runner.run();seconds=time.perf_counter()-start
    root=runner.write_artifacts(Path(args.output))
    raw_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report={'runtime':runtime_info(),'platform':platform.platform(),'machine':platform.machine(),
            'logical_cpus':os.cpu_count(),'recording_level':'p7_full','worlds':1,
            'ticks':summary['tick']-summary['start_tick'],'seconds':seconds,
            'ticks_per_second':(summary['tick']-summary['start_tick'])/seconds,
            'peak_rss_bytes':raw_rss if sys.platform=='darwin' else raw_rss*1024,
            'record_bytes':sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
            'summary':summary}
    (root/'benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
