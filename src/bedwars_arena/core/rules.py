"""Versioned reference values, with explicit gates for unverified rules."""

from dataclasses import dataclass, replace
from enum import StrEnum
from importlib.resources import files
import json
from types import MappingProxyType
from typing import Mapping

from .team import TeamState, UpgradeId
from .time import identifier, integer, seconds_to_ticks


class GameMode(StrEnum):
    SOLO = "solo"
    DOUBLES = "doubles"
    THREES = "3v3v3v3"
    FOURS = "4v4v4v4"


class UnresolvedRuleError(ValueError):
    """No measured/selected value is available for the requested operation."""


@dataclass(frozen=True, slots=True)
class TeamRules:
    mode: GameMode
    queue_prices: tuple[int, ...]
    upgrade_prices: Mapping[UpgradeId, tuple[int, ...]]
    effect_duration_ticks: Mapping[str, int | None]
    shared_trap_cooldown_ticks: int | None = None
    cooldown_origin: str | None = None
    community_prices_enabled: bool = False
    profile_id: str = "hypixel-team-reference-v1"

    def __post_init__(self) -> None:
        identifier(self.profile_id, "profile_id")
        if not isinstance(self.mode, GameMode) or not self.queue_prices:
            raise ValueError("An explicit supported mode and queue prices are required")
        prices = tuple(integer(price, "trap price", 1) for price in self.queue_prices)
        upgrades = {UpgradeId(key): tuple(integer(v, "upgrade price", 1) for v in values)
                    for key, values in self.upgrade_prices.items()}
        if set(upgrades) != set(UpgradeId) or any(not values for values in upgrades.values()):
            raise ValueError("An explicit price schedule for every upgrade is required")
        durations = dict(self.effect_duration_ticks)
        for key, value in durations.items():
            identifier(key, "effect_id")
            if value is not None:
                integer(value, "effect duration")
        if type(self.community_prices_enabled) is not bool:
            raise ValueError("Candidate price opt-in must be bool")
        if self.shared_trap_cooldown_ticks is not None:
            integer(self.shared_trap_cooldown_ticks, "shared trap cooldown")
            if not isinstance(self.cooldown_origin, str) or not self.cooldown_origin.strip():
                raise ValueError("An explicit cooldown requires an evidence/experiment origin")
        elif self.cooldown_origin is not None:
            raise ValueError("An unknown cooldown cannot have a selected-value origin")
        object.__setattr__(self, "queue_prices", prices)
        object.__setattr__(self, "upgrade_prices", MappingProxyType(upgrades))
        object.__setattr__(self, "effect_duration_ticks", MappingProxyType(durations))

    @property
    def trap_capacity(self) -> int:
        return len(self.queue_prices)

    def upgrade_price(self, upgrade: UpgradeId, target_level: int) -> int:
        integer(target_level, "target_level", 1)
        if not isinstance(upgrade, UpgradeId) or target_level > len(self.upgrade_prices[upgrade]):
            raise ValueError("Unknown upgrade or invalid target level")
        if not self.community_prices_enabled:
            raise UnresolvedRuleError("Upgrade prices are community candidates; opt in explicitly")
        return self.upgrade_prices[upgrade][target_level - 1]

    def require_cooldown(self) -> int:
        if self.shared_trap_cooldown_ticks is None:
            raise UnresolvedRuleError("Q15 trap cooldown is unknown; provide an explicit override")
        return self.shared_trap_cooldown_ticks

    def with_cooldown(self, ticks: int, *, origin: str) -> "TeamRules":
        return replace(self, shared_trap_cooldown_ticks=ticks, cooldown_origin=origin)

    def to_dict(self) -> dict:
        return {"schema_version": 1, "mode": self.mode.value, "profile_id": self.profile_id,
                "queue_prices": list(self.queue_prices),
                "upgrade_prices": {key.value: list(values) for key, values in self.upgrade_prices.items()},
                "effect_duration_ticks": dict(self.effect_duration_ticks),
                "shared_trap_cooldown_ticks": self.shared_trap_cooldown_ticks,
                "cooldown_origin": self.cooldown_origin,
                "community_prices_enabled": self.community_prices_enabled}

    @classmethod
    def from_dict(cls, value: dict) -> "TeamRules":
        keys = {"schema_version", "mode", "profile_id", "queue_prices", "upgrade_prices",
                "effect_duration_ticks", "shared_trap_cooldown_ticks", "cooldown_origin",
                "community_prices_enabled"}
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError("Invalid TeamRules fields")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("Unknown rule schema version")
        return cls(mode=GameMode(value["mode"]), queue_prices=tuple(value["queue_prices"]),
                   upgrade_prices=value["upgrade_prices"],
                   effect_duration_ticks=value["effect_duration_ticks"],
                   shared_trap_cooldown_ticks=value["shared_trap_cooldown_ticks"],
                   cooldown_origin=value["cooldown_origin"],
                   community_prices_enabled=value["community_prices_enabled"],
                   profile_id=value["profile_id"])


def validate_team_state(team: TeamState, rules: TeamRules) -> None:
    if len(team.trap_queue) > rules.trap_capacity:
        raise ValueError("Trap queue exceeds the selected rule capacity")
    if any(level > len(rules.upgrade_prices[upgrade]) for upgrade, level in team.upgrades.items()):
        raise ValueError("Upgrade level exceeds the selected rule maximum")


def load_team_rules(mode: GameMode, *, accept_community_prices: bool = False) -> TeamRules:
    if not isinstance(mode, GameMode):
        raise ValueError("Choose solo/doubles/3v3v3v3/4v4v4v4 explicitly; 4v4 is not interchangeable")
    data = json.loads(files("bedwars_arena").joinpath(
        "core/data/hypixel_team_reference_v1.json").read_text(encoding="utf-8"))
    group = "solo_doubles" if mode in (GameMode.SOLO, GameMode.DOUBLES) else "threes_fours"
    return TeamRules(
        mode, tuple(data["queue_prices_diamonds"]),
        {UpgradeId(key): tuple(prices) for key, prices in data["upgrade_prices"][group].items()},
        {key: None if seconds is None else seconds_to_ticks(seconds)
         for key, seconds in data["effect_duration_seconds"].items()},
        community_prices_enabled=accept_community_prices,
        profile_id=data["profile_id"],
    )
