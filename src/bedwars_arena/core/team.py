"""Team state values, independent of policies, rendering and transport."""

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Sequence

from .time import identifier, integer


class BedStatus(StrEnum):
    PRESENT = "present"
    DESTROYED = "destroyed"


class LifeStatus(StrEnum):
    ALIVE = "alive"
    RESPAWNING = "respawning"
    ELIMINATED = "eliminated"


class UpgradeId(StrEnum):
    SHARPENED_SWORDS = "sharpened_swords"
    REINFORCED_ARMOR = "reinforced_armor"
    MANIAC_MINER = "maniac_miner"
    FORGE = "forge"
    HEAL_POOL = "heal_pool"
    CUSHIONED_BOOTS = "cushioned_boots"


class TrapType(StrEnum):
    BLINDNESS = "blindness"
    MINER_FATIGUE = "miner_fatigue"
    REVEAL = "reveal"
    COUNTER_OFFENSIVE = "counter_offensive"


@dataclass(frozen=True, slots=True)
class BedState:
    status: BedStatus = BedStatus.PRESENT
    destroyed_at: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, BedStatus):
            raise ValueError("Invalid bed status")
        if self.status == BedStatus.PRESENT:
            if self.destroyed_at is not None:
                raise ValueError("A present bed cannot have a destruction time")
        else:
            integer(self.destroyed_at, "destroyed_at")


@dataclass(frozen=True, slots=True)
class TrapState:
    trap_id: str
    trap_type: TrapType
    purchased_by: str
    purchased_at: int

    def __post_init__(self) -> None:
        identifier(self.trap_id, "trap_id")
        identifier(self.purchased_by, "purchased_by")
        integer(self.purchased_at, "purchased_at")
        if not isinstance(self.trap_type, TrapType):
            raise ValueError("Invalid trap type")


@dataclass(frozen=True, slots=True)
class TeamState:
    team_id: str
    bed_state: BedState = field(default_factory=BedState)
    upgrades: Mapping[UpgradeId, int] = field(default_factory=dict)
    trap_queue: tuple[TrapState, ...] = ()
    trap_ready_at: int = 0

    def __post_init__(self) -> None:
        identifier(self.team_id, "team_id")
        integer(self.trap_ready_at, "trap_ready_at")
        if not isinstance(self.bed_state, BedState):
            raise ValueError("Invalid bed state")
        copied = dict(self.upgrades)
        for upgrade, level in copied.items():
            if not isinstance(upgrade, UpgradeId):
                raise ValueError("Unknown upgrade ID")
            integer(level, "upgrade level", 1)
        queue = tuple(self.trap_queue)
        if any(not isinstance(trap, TrapState) for trap in queue):
            raise ValueError("Invalid trap instance")
        if len({trap.trap_id for trap in queue}) != len(queue):
            raise ValueError("Duplicate trap instance ID")
        object.__setattr__(self, "upgrades", MappingProxyType(copied))
        object.__setattr__(self, "trap_queue", queue)

    @classmethod
    def initial(cls, team_id: str, *, t0: int) -> "TeamState":
        return cls(team_id=team_id, trap_ready_at=integer(t0, "t0"))

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "bed_state": {"status": self.bed_state.status.value,
                          "destroyed_at": self.bed_state.destroyed_at},
            "upgrades": {key.value: value for key, value in sorted(self.upgrades.items())},
            "trap_queue": [
                {"trap_id": trap.trap_id, "trap_type": trap.trap_type.value,
                 "purchased_by": trap.purchased_by, "purchased_at": trap.purchased_at}
                for trap in self.trap_queue
            ],
            "trap_ready_at": self.trap_ready_at,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "TeamState":
        if not isinstance(value, dict) or set(value) != {
            "team_id", "bed_state", "upgrades", "trap_queue", "trap_ready_at"
        }:
            raise ValueError("Invalid TeamState v1 fields")
        bed, upgrades, queue = value["bed_state"], value["upgrades"], value["trap_queue"]
        if not isinstance(bed, dict) or set(bed) != {"status", "destroyed_at"}:
            raise ValueError("Invalid bed fields")
        if not isinstance(upgrades, dict) or not isinstance(queue, list):
            raise ValueError("Invalid upgrades or trap queue")
        traps = []
        for trap in queue:
            if not isinstance(trap, dict) or set(trap) != {
                "trap_id", "trap_type", "purchased_by", "purchased_at"
            }:
                raise ValueError("Invalid trap fields")
            traps.append(TrapState(trap["trap_id"], TrapType(trap["trap_type"]),
                                   trap["purchased_by"], trap["purchased_at"]))
        return cls(value["team_id"], BedState(BedStatus(bed["status"]), bed["destroyed_at"]),
                   {UpgradeId(key): level for key, level in upgrades.items()}, tuple(traps),
                   value["trap_ready_at"])


@dataclass(frozen=True, slots=True)
class MemberView:
    """An internal projection of players, not a second stored team roster.

    Sequence order is the fixed match player order used for trap arbitration.
    Spatial/shop/milk eligibility must be computed by core, never by a policy.
    """

    player_id: str
    team_id: str
    life: LifeStatus
    life_index: int = 1

    def __post_init__(self) -> None:
        identifier(self.player_id, "player_id")
        identifier(self.team_id, "team_id")
        integer(self.life_index, "life_index", 1)
        if not isinstance(self.life, LifeStatus):
            raise ValueError("Invalid life status")


def validate_members(members: Sequence[MemberView]) -> None:
    if not members or any(not isinstance(member, MemberView) for member in members):
        raise ValueError("A match must have valid members")
    if len({member.player_id for member in members}) != len(members):
        raise ValueError("Duplicate player ID")


def team_active(team_id: str, members: Sequence[MemberView]) -> bool:
    validate_members(members)
    own = [member for member in members if member.team_id == team_id]
    if not own:
        raise ValueError("An enabled team must not be empty")
    return any(member.life != LifeStatus.ELIMINATED for member in own)


def validate_match_teams(teams: Sequence[TeamState], members: Sequence[MemberView]) -> None:
    validate_members(members)
    ids = [team.team_id for team in teams]
    if len(set(ids)) != len(ids) or set(ids) != {member.team_id for member in members}:
        raise ValueError("Teams must exactly match the nonempty enabled rosters")
    traps = [trap for team in teams for trap in team.trap_queue]
    if len({trap.trap_id for trap in traps}) != len(traps):
        raise ValueError("Trap instance IDs must be unique across the match")
    owners = {member.player_id: member.team_id for member in members}
    for team in teams:
        if any(owners.get(trap.purchased_by) != team.team_id for trap in team.trap_queue):
            raise ValueError("Trap purchaser must belong to its team")
