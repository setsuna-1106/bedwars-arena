"""Project metadata commands, independent of future simulation rules."""

import argparse
import json
from collections.abc import Sequence

from bedwars_arena import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Show project information without claiming to run a simulation."""
    parser = argparse.ArgumentParser(
        prog="bedwars-arena",
        description="BedWars Arena 工程入口；当前阶段为项目骨架。",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    info = commands.add_parser("info", help="显示项目版本与实现状态")
    info.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    if args.command == "info":
        metadata = {
            "name": "BedWars Arena",
            "version": __version__,
            "stage": "scaffold",
            "simulation_available": False,
        }
        if args.json:
            print(json.dumps(metadata, ensure_ascii=False, indent=2))
        else:
            print(f"BedWars Arena {__version__}")
            print("阶段：工程骨架；模拟引擎尚未实现。")
        return 0

    parser.print_help()
    return 0
