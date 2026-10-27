"""Pure team transitions. Callers commit state, inventory and event together.

Core computes spatial/shop/effect eligibility. These inputs are internal rule
results, not fields an external policy may assert. Full physics and effect
application belong to the future world engine.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Sequence

from .rules import TeamRules, validate_team_state
from .team import (BedState, BedStatus, LifeStatus, MemberView, TeamState,
                   TrapState, TrapType, UpgradeId, team_active, validate_members)
from .time import identifier, integer


class Rejection(StrEnum):
    INELIGIBLE = "ineligible"
    TARGET_LEVEL = "target_level_changed_or_invalid"
    INSUFFICIENT_RESOURCES = "insufficient_resources"
    QUEUE_FULL = "trap_queue_full"
    PRICE_LIMIT = "price_exceeds_max_cost"
    DUPLICATE_TRAP_ID = "duplicate_trap_id"
    NO_TRIGGER = "no_trigger"
    BED_ALREADY_DESTROYED = "bed_already_destroyed"


@dataclass(frozen=True, slots=True)
class Transition:
    team: TeamState
    inventory: Mapping[str, int] | None = None
    event: Mapping | None = None
    rejection: Rejection | None = None

    def __post_init__(self) -> None:
        if self.inventory is not None:
            object.__setattr__(self, "inventory", MappingProxyType(dict(self.inventory)))
        if self.event is not None:
            object.__setattr__(self, "event", MappingProxyType(dict(self.event)))

    @property
    def accepted(self) -> bool:
        return self.rejection is None


def _inventory(value: Mapping[str, int]) -> dict[str, int]:
    result = dict(value)
    for item, count in result.items():
        identifier(item, "item_id")
        integer(count, "item quantity")
    return result


def _buyer(team: TeamState, members: Sequence[MemberView], payer: str, can_shop: bool) -> bool:
    if type(can_shop) is not bool:
        raise ValueError("can_shop must be a core-computed boolean")
    return team_active(team.team_id, members) and can_shop and any(
        member.player_id == payer and member.team_id == team.team_id
        and member.life == LifeStatus.ALIVE for member in members)


def purchase_upgrade(team: TeamState, inventory: Mapping[str, int], *,
                     members: Sequence[MemberView], payer: str, upgrade: UpgradeId,
                     target_level: int, now: int, rules: TeamRules, can_shop: bool) -> Transition:
    integer(now, "now")
    validate_team_state(team, rules)
    integer(target_level, "target_level", 1)
    identifier(payer, "payer")
    if not isinstance(upgrade, UpgradeId):
        raise ValueError("Unknown upgrade ID")
    bag = _inventory(inventory)
    if not _buyer(team, members, payer, can_shop):
        return Transition(team, bag, rejection=Rejection.INELIGIBLE)
    if target_level != team.upgrades.get(upgrade, 0) + 1 or target_level > len(rules.upgrade_prices[upgrade]):
        return Transition(team, bag, rejection=Rejection.TARGET_LEVEL)
    price = rules.upgrade_price(upgrade, target_level)
    if bag.get("diamond", 0) < price:
        return Transition(team, bag, rejection=Rejection.INSUFFICIENT_RESOURCES)
    bag["diamond"] -= price
    upgrades = dict(team.upgrades)
    upgrades[upgrade] = target_level
    return Transition(replace(team, upgrades=upgrades), bag, {
        "kind": "upgrade_purchased", "tick": now, "team_id": team.team_id,
        "player_id": payer, "upgrade_id": upgrade.value, "target_level": target_level,
        "cost_diamond": price, "profile_id": rules.profile_id,
    })


def purchase_trap(team: TeamState, inventory: Mapping[str, int], *,
                  members: Sequence[MemberView], payer: str, trap_type: TrapType,
                  trap_id: str, max_cost: int, now: int, rules: TeamRules,
                  can_shop: bool) -> Transition:
    integer(now, "now")
    validate_team_state(team, rules)
    integer(max_cost, "max_cost")
    identifier(trap_id, "trap_id")
    identifier(payer, "payer")
    if not isinstance(trap_type, TrapType):
        raise ValueError("Unknown trap type")
    bag = _inventory(inventory)
    if not _buyer(team, members, payer, can_shop):
        return Transition(team, bag, rejection=Rejection.INELIGIBLE)
    if any(trap.trap_id == trap_id for trap in team.trap_queue):
        return Transition(team, bag, rejection=Rejection.DUPLICATE_TRAP_ID)
    if len(team.trap_queue) >= rules.trap_capacity:
        return Transition(team, bag, rejection=Rejection.QUEUE_FULL)
    price = rules.queue_prices[len(team.trap_queue)]
    if price > max_cost:
        return Transition(team, bag, rejection=Rejection.PRICE_LIMIT)
    if bag.get("diamond", 0) < price:
        return Transition(team, bag, rejection=Rejection.INSUFFICIENT_RESOURCES)
    bag["diamond"] -= price
    trap = TrapState(trap_id, trap_type, payer, now)
    return Transition(replace(team, trap_queue=team.trap_queue + (trap,)), bag, {
        "kind": "trap_purchased", "tick": now, "team_id": team.team_id,
        "player_id": payer, "trap_id": trap_id, "trap_type": trap_type.value,
        "cost_diamond": price, "profile_id": rules.profile_id,
    })


def trigger_trap(team: TeamState, *, members: Sequence[MemberView],
                 eligible_player_ids: Sequence[str], now: int, rules: TeamRules) -> Transition:
    """Emit an effect/alarm intent; applying it is the world engine's job."""
    integer(now, "now")
    validate_team_state(team, rules)
    if not team_active(team.team_id, members) or not team.trap_queue or now < team.trap_ready_at:
        return Transition(team, rejection=Rejection.NO_TRIGGER)
    eligible = {identifier(value, "candidate player ID") for value in eligible_player_ids}
    intruder = next((member for member in members if member.player_id in eligible
                     and member.team_id != team.team_id and member.life == LifeStatus.ALIVE), None)
    if intruder is None:
        return Transition(team, rejection=Rejection.NO_TRIGGER)
    ready_at = integer(now + rules.require_cooldown(), "trap_ready_at")
    trap = team.trap_queue[0]
    return Transition(replace(team, trap_queue=team.trap_queue[1:], trap_ready_at=ready_at), event={
        "kind": "trap_triggered", "tick": now, "team_id": team.team_id,
        "trap_id": trap.trap_id, "trap_type": trap.trap_type.value,
        "triggered_by": intruder.player_id, "life_index": intruder.life_index,
        "trap_ready_at": ready_at, "cooldown_origin": rules.cooldown_origin,
        "profile_id": rules.profile_id,
    })


def destroy_bed(team: TeamState, *, now: int, source: str | None,
                cause: str) -> Transition:
    """Commit an already validated world destruction; not an external action."""
    integer(now, "now")
    identifier(cause, "bed destruction cause")
    if source is not None:
        identifier(source, "bed destruction source")
    if team.bed_state.status == BedStatus.DESTROYED:
        return Transition(team, rejection=Rejection.BED_ALREADY_DESTROYED)
    return Transition(replace(team, bed_state=BedState(BedStatus.DESTROYED, now)), event={
        "kind": "bed_destroyed", "tick": now, "team_id": team.team_id,
        "source_player_id": source, "cause": cause,
    })


def death_destination(team: TeamState) -> LifeStatus:
    """Called at death settlement, never to revoke an existing respawn."""
    return LifeStatus.RESPAWNING if team.bed_state.status == BedStatus.PRESENT else LifeStatus.ELIMINATED


def settle_elimination(team: TeamState, *, before: Sequence[MemberView],
                       after: Sequence[MemberView], now: int) -> Transition:
    integer(now, "now")
    validate_members(before)
    validate_members(after)
    if [(m.player_id, m.team_id) for m in before] != [(m.player_id, m.team_id) for m in after]:
        raise ValueError("The match roster and its ordering are fixed")
    if team_active(team.team_id, before) and not team_active(team.team_id, after):
        return Transition(team, event={"kind": "team_eliminated", "tick": now,
                                       "team_id": team.team_id})
    return Transition(team)
