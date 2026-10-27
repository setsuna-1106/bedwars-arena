"""Inspect team transitions with an explicit experimental cooldown.

This is not a match runner and does not claim a Hypixel cooldown measurement.
"""

import argparse
import json

from bedwars_arena.core.rules import GameMode, load_team_rules
from bedwars_arena.core.team import LifeStatus, MemberView, TeamState, TrapType
from bedwars_arena.core.team_rules import purchase_trap, trigger_trap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trap-cooldown-ticks", type=int, required=True,
                        help="Explicit experimental/calibrated value; there is no default")
    parser.add_argument("--cooldown-origin", required=True,
                        help="Evidence or experiment label saved with the rule override")
    args = parser.parse_args()
    rules = load_team_rules(GameMode.DOUBLES).with_cooldown(
        args.trap_cooldown_ticks, origin=args.cooldown_origin)
    members = (MemberView("red-1", "red", LifeStatus.ALIVE),
               MemberView("blue-1", "blue", LifeStatus.ALIVE))
    state = TeamState.initial("red", t0=0)
    purchase = purchase_trap(state, {"diamond": 5}, members=members, payer="red-1",
                             trap_type=TrapType.MINER_FATIGUE, trap_id="example-trap-1",
                             max_cost=1, now=0, rules=rules, can_shop=True)
    # A real world engine must calculate shop/range/milk eligibility itself.
    fired = trigger_trap(purchase.team, members=members, eligible_player_ids=["blue-1"],
                         now=1, rules=rules)
    print(json.dumps({"team": fired.team.to_dict(), "inventory": dict(purchase.inventory),
                      "purchase": dict(purchase.event), "trigger_intent": dict(fired.event),
                      "rules": rules.to_dict(), "full_match": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
