"""Project information and validation of the L1 definition bundle."""

import argparse
import json
from collections.abc import Sequence

from bedwars_arena import __version__
from bedwars_arena.core.definitions import L1DefinitionError, load_l1_definitions


def main(argv: Sequence[str] | None = None) -> int:
    """Show metadata or validate definitions without claiming a simulation exists."""
    parser = argparse.ArgumentParser(
        prog="bedwars-arena",
        description="BedWars Arena 工程入口；当前提供 L1 定义校验。",
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
    args = parser.parse_args(argv)

    if args.command == "info":
        metadata = {
            "name": "BedWars Arena",
            "version": __version__,
            "stage": "l1_p5",
            "team_state_available": True,
            "l1_definitions_available": True,
            "simulation_available": False,
        }
        if args.json:
            print(json.dumps(metadata, ensure_ascii=False, indent=2))
        else:
            print(f"BedWars Arena {__version__}")
            print("阶段：L1 P5 战斗、死亡复活与终局；完整对局 Runner 尚未实现。")
        return 0

    if args.command == "validate-l1":
        try:
            definitions = load_l1_definitions(profile_path=args.profile, map_path=args.map_path,
                                              scenario_path=args.scenario)
        except L1DefinitionError as error:
            parser.exit(2, f"L1 定义校验失败：{error}\n")
        result = {"valid": True, "simulation_available": False,
                  "definitions": {name: {"id": definition.id, "version": definition.version,
                                          "sha256": definition.sha256}
                                  for name in ("profile", "map", "scenario")
                                  for definition in (getattr(definitions, name),)}}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("L1 定义校验通过；对局引擎尚未实现。")
            for name, definition in result["definitions"].items():
                print(f"{name}: {definition['id']} v{definition['version']}  sha256={definition['sha256']}")
        return 0

    parser.print_help()
    return 0
