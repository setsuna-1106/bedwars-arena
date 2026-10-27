"""Project information and validation of the L1 definition bundle."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from bedwars_arena import __version__
from bedwars_arena.core.definitions import L1DefinitionError, load_l1_definitions


def main(argv: Sequence[str] | None = None) -> int:
    """Show metadata or validate definitions without claiming a simulation exists."""
    parser = argparse.ArgumentParser(
        prog="bedwars-arena",
        description="BedWars Arena L1 实验对局和定义校验入口。",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    info = commands.add_parser("info", help="显示项目版本与实现状态")
    info.add_argument("--json", action="store_true", help="输出 JSON")
    validate = commands.add_parser("validate-l1", help="校验 L1 规则、地图和初始场景")
    validate.add_argument("--profile", help="规则 JSON 路径；省略时使用内置档案")
    validate.add_argument("--map", dest="map_path", help="地图 JSON 路径；省略时使用内置地图")
    validate.add_argument("--scenario", help="场景 JSON 路径；省略时使用内置场景")
    validate.add_argument("--json", action="store_true", help="输出 JSON")
    def add_run_options(command):
        command.add_argument('--seed',type=int,default=101,help='64 位非负种子')
        command.add_argument('--red',choices=('attack','defend'),default='attack')
        command.add_argument('--blue',choices=('attack','defend'),default='defend')
        command.add_argument('--decision-interval',type=int,default=1,help='每次决策后逐 tick 推进次数')
        command.add_argument('--episode-limit',type=int,help='外部 episode 上限 tick')
        command.add_argument('--profile',help='自定义 L1 规则 JSON')
        command.add_argument('--map',dest='map_path',help='自定义固定地图 JSON')
        command.add_argument('--scenario',help='自定义场景 JSON')
        command.add_argument('--preset',help='训练预置 JSON；省略为标准对局')
        command.add_argument('--output',help='必须尚不存在的记录目录')
        command.add_argument('--progress-every',type=int,default=0,help='每隔多少 tick 在 stderr 显示进度，0 为关闭')
        command.add_argument('--json',action='store_true',help='输出 JSON 摘要')
    run=commands.add_parser('run-l1',help='运行一局 L1 2v2 并保存记录')
    add_run_options(run)
    batch=commands.add_parser('batch-l1',help='运行多局 L1 2v2 并保存记录')
    add_run_options(batch)
    batch.add_argument('--games',type=int,default=2,help='对局数量；逐局递增 seed')
    args = parser.parse_args(argv)

    if args.command == "info":
        metadata = {
            "name": "BedWars Arena",
            "version": __version__,
            "stage": "l1_p6",
            "team_state_available": True,
            "l1_definitions_available": True,
            "simulation_available": True,
        }
        if args.json:
            print(json.dumps(metadata, ensure_ascii=False, indent=2))
        else:
            print(f"BedWars Arena {__version__}")
            print("阶段：L1 P6 完整 2v2 对局；回放和训练仍待实现。")
        return 0

    if args.command == "validate-l1":
        try:
            definitions = load_l1_definitions(profile_path=args.profile, map_path=args.map_path,
                                              scenario_path=args.scenario)
        except L1DefinitionError as error:
            parser.exit(2, f"L1 定义校验失败：{error}\n")
        result = {"valid": True, "simulation_available": True,
                  "definitions": {name: {"id": definition.id, "version": definition.version,
                                          "sha256": definition.sha256}
                                  for name in ("profile", "map", "scenario")
                                  for definition in (getattr(definitions, name),)}}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("L1 定义校验通过；可通过 run-l1 启动对局。")
            for name, definition in result["definitions"].items():
                print(f"{name}: {definition['id']} v{definition['version']}  sha256={definition['sha256']}")
        return 0

    if args.command in ('run-l1','batch-l1'):
        from bedwars_arena.agents.scripts import EconomicAttacker, DefensiveCounterattacker
        from bedwars_arena.core.definitions import _read_json
        from bedwars_arena.core.world import WorldEngine
        from bedwars_arena.runner.match import MatchRunner
        from uuid import uuid4
        try:
            definitions=load_l1_definitions(profile_path=args.profile,map_path=args.map_path,scenario_path=args.scenario)
            preset=None if args.preset is None else _read_json(Path(args.preset))
            games=1 if args.command=='run-l1' else args.games
            if args.progress_every < 0:
                raise ValueError('progress-every 必须非负')
            if type(games) is not int or not 1 <= games <= 10000:
                raise ValueError('games 必须为 1–10000')
            if not 0 <= args.seed < 2**64 or args.seed+games-1 >= 2**64:
                raise ValueError('seed 必须为无符号 64 位整数，批量种子不能溢出')
            classes={'attack':EconomicAttacker,'defend':DefensiveCounterattacker}
            root=Path(args.output) if args.output else Path('artifacts')/f'l1-{uuid4().hex}'
            if args.command=='batch-l1':
                root.mkdir(parents=True,exist_ok=False)
            summaries=[]
            for index in range(games):
                world=WorldEngine.create(definitions,seed=args.seed+index,preset=preset)
                teams=[team['team_id'] for team in definitions.map.data['teams']]
                policies={entry['player_id']:classes[args.red if entry['team_id']==teams[0] else args.blue]()
                          for entry in definitions.scenario.data['players']}
                runner=MatchRunner(world,policies,decision_interval=args.decision_interval,
                                   episode_limit_ticks=args.episode_limit)
                try:
                    while not (runner.terminated or runner.truncated):
                        runner.decision_step()
                        tick=runner.world.state['tick']
                        if args.progress_every and tick % args.progress_every == 0:
                            print(f'对局 {index+1}/{games}: tick {tick}',file=sys.stderr,flush=True)
                    summary=runner.summary()
                except Exception:
                    summary=runner.summary()
                output=root if args.command=='run-l1' else root/f'game-{index+1:04d}'
                runner.write_artifacts(output)
                summary['output']=str(output.resolve())
                summaries.append(summary)
            result=summaries[0] if args.command=='run-l1' else {'games':summaries,
                'terminated':sum(x['terminated'] for x in summaries),'truncated':sum(x['truncated'] for x in summaries),
                'failures':sum(x['failure'] is not None for x in summaries)}
            if args.command=='batch-l1':
                (root/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
            return 1 if any(summary['failure'] is not None for summary in summaries) else 0
        except (ValueError,OSError,L1DefinitionError) as error:
            parser.exit(2,f'L1 运行失败：{error}\n')

    parser.print_help()
    return 0
