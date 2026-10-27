"""Load, validate and hash L1 definitions, without constructing a game world."""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
import json
import math
from pathlib import Path
from typing import Any

from .profiles import L1DefinitionError, _require, validate_profile
from .time import MAX_SAFE_INTEGER

_DATA = "data/l1"
_BUILTIN = {"profile": "profile-v0.1.json", "map": "three-islands-v1.json",
            "scenario": "standard-2v2-v1.json"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise L1DefinitionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bad_constant(value: str) -> None:
    raise L1DefinitionError(f"non-finite JSON number: {value}")


def _read_json(source: Any) -> dict[str, Any]:
    try:
        value = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_bad_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise L1DefinitionError(f"cannot read JSON definition {source}: {error}") from error
    if not isinstance(value, dict):
        raise L1DefinitionError("definition root must be an object")
    return value


def _validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the closed subset used by our bundled draft-2020-12 schemas."""
    supported = {"$schema", "$id", "title", "description", "type", "properties", "required",
                 "additionalProperties", "const", "minimum", "maximum", "minLength", "maxLength",
                 "minItems", "maxItems", "items"}
    if schema.keys() - supported:
        raise L1DefinitionError(f"{path}: unsupported schema keywords {sorted(schema.keys() - supported)}")
    kinds = schema.get("type", [])
    if isinstance(kinds, str):
        kinds = [kinds]
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "null": lambda v: v is None,
              "boolean": lambda v: type(v) is bool, "integer": lambda v: type(v) is int,
              "number": lambda v: type(v) in (int, float)}
    if any(kind not in checks for kind in kinds):
        raise L1DefinitionError(f"{path}: unsupported schema type")
    if kinds and not any(checks[kind](value) for kind in kinds):
        raise L1DefinitionError(f"{path}: expected {' or '.join(kinds)}")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise L1DefinitionError(f"{path}: unsupported value")
    if type(value) in (int, float):
        if abs(value) > MAX_SAFE_INTEGER or not math.isfinite(value):
            raise L1DefinitionError(f"{path}: expected a finite, JSON-safe number")
        if "minimum" in schema and value < schema["minimum"]:
            raise L1DefinitionError(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise L1DefinitionError(f"{path}: above maximum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 2**31):
            raise L1DefinitionError(f"{path}: invalid string length")
        if any(ord(c) < 32 for c in value):
            raise L1DefinitionError(f"{path}: control characters are not permitted")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise L1DefinitionError(f"{path}: object keys must be strings")
        props = schema.get("properties", {})
        missing = set(schema.get("required", ())) - value.keys()
        extra = value.keys() - props.keys()
        if missing:
            raise L1DefinitionError(f"{path}: missing fields {sorted(missing)}")
        if schema.get("additionalProperties") is False and extra:
            raise L1DefinitionError(f"{path}: unknown fields {sorted(extra)}")
        for key, child in value.items():
            if key in props:
                _validate_schema(child, props[key], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 2**31):
            raise L1DefinitionError(f"{path}: invalid array length")
        if "items" in schema:
            for i, child in enumerate(value):
                _validate_schema(child, schema["items"], f"{path}[{i}]")


def _canonical(value: dict[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise L1DefinitionError(f"cannot encode definition: {error}") from error


@dataclass(frozen=True, slots=True)
class Definition:
    """An immutable canonical value; each call to data returns a detached copy."""

    kind: str
    id: str
    version: str
    sha256: str
    _canonical_bytes: bytes

    @property
    def data(self) -> dict[str, Any]:
        return json.loads(self._canonical_bytes)


@dataclass(frozen=True, slots=True)
class L1Definitions:
    profile: Definition
    map: Definition
    scenario: Definition

    @property
    def hashes(self) -> dict[str, str]:
        return {name: getattr(self, name).sha256 for name in _BUILTIN}


def _rect(rect: dict[str, Any], name: str) -> tuple[float, float, float, float]:
    a, b, c, d = (rect[k] for k in ("min_x", "max_x", "min_z", "max_z"))
    _require(a < b and c < d, f"{name}: rectangle must have positive area")
    return a, b, c, d


def _inside(inner: tuple, outer: tuple) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1] and outer[2] <= inner[2] and inner[3] <= outer[3]


def _overlap(a: tuple, b: tuple) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1]) and max(a[2], b[2]) < min(a[3], b[3])


def _supported(box: tuple, islands: list[tuple]) -> bool:
    # Sweep island edges: a small unsupported gap must not be hidden by an area tolerance.
    cuts = sorted({box[0], box[1]} | {x for i in islands for x in i[:2] if box[0] < x < box[1]})
    for left, right in zip(cuts, cuts[1:]):
        intervals = sorted((max(box[2], i[2]), min(box[3], i[3])) for i in islands
                           if i[0] <= left and i[1] >= right and i[2] < box[3] and i[3] > box[2])
        covered_to = box[2]
        for start, end in intervals:
            if start > covered_to:
                return False
            covered_to = max(covered_to, end)
        if covered_to < box[3]:
            return False
    return True


def _center_box(position: dict, width: float, depth: float) -> tuple:
    x, z = position["x"], position["z"]
    return x - width / 2, x + width / 2, z - depth / 2, z + depth / 2


def _unique(values: list[str], label: str) -> None:
    _require(len(set(values)) == len(values), f"duplicate {label}")


def _validate_map(profile: dict, map_data: dict) -> None:
    bounds = _rect(map_data["bounds"], "map bounds")
    terrain = map_data["terrain"]
    _require(terrain["original_island_y"] == terrain["bridge_y"] == profile["building"]["bridge_y"]
             and terrain["wall_y"] == profile["building"]["wall_y"], "inconsistent terrain layers")
    island_defs = terrain["islands"]
    _unique([i["id"] for i in island_defs], "island id")
    _require(len(island_defs) == 3, "L1 needs three original islands")
    islands = [_rect(i["bounds"], f"island {i['id']}") for i in island_defs]
    for index, island in enumerate(islands):
        _require(_inside(island, bounds), "island outside map bounds")
        _require(not any(_overlap(island, other) for other in islands[:index]), "original islands overlap")

    teams, generators, regions = map_data["teams"], map_data["generators"], map_data["protected_regions"]
    _require(len(teams) == profile["game"]["teams"], "wrong map team count")
    _unique([team["team_id"] for team in teams], "team id")
    _unique([gen["generator_id"] for gen in generators], "generator id")
    _unique([region["id"] for region in regions], "protected region id")
    team_ids = {team["team_id"] for team in teams}
    gen_ids = {gen["generator_id"] for gen in generators}
    _require(len(generators) == len(teams) + 1, "L1 requires one base generator per team and one central generator")
    _require(sum(g["kind"] == "central" and g["team_id"] is None for g in generators) == 1,
             "L1 requires one unowned central generator")
    base_teams = [g["team_id"] for g in generators if g["kind"] == "base"]
    _require(len(base_teams) == len(teams) and set(base_teams) == team_ids,
             "base generator ownership must cover each team exactly once")

    beds = [(t["bed"]["x"], t["bed"]["x"] + 1, t["bed"]["z"], t["bed"]["z"] + 1) for t in teams]
    for i, bed in enumerate(beds):
        _require(_inside(bed, bounds) and _supported(bed, islands), "bed is outside supported ground")
        _require(not any(_overlap(bed, b) for b in beds[:i]), "beds overlap")
    required_regions = {(kind, team_id) for team_id in team_ids for kind in ("spawn", "shop")}
    required_regions |= {("generator", gen_id) for gen_id in gen_ids}
    actual_regions = [(r["kind"], r["target_id"]) for r in regions]
    _require(len(actual_regions) == len(required_regions) and set(actual_regions) == required_regions,
             "protected regions must reference every spawn, shop and generator exactly once")
    region_map = {(r["kind"], r["target_id"]): _rect(r["bounds"], f"region {r['id']}") for r in regions}
    _require(all(_inside(r, bounds) for r in region_map.values()), "protected region outside map bounds")
    physics = profile["physics"]
    for team in teams:
        team_id = team["team_id"]
        spawn = _center_box(team["spawn"], physics["player_width"], physics["player_depth"])
        _require(_inside(spawn, bounds) and _supported(spawn, islands), "spawn body not fully supported")
        _require(_inside(spawn, region_map[("spawn", team_id)]), "spawn body is not fully protected")
        _require(not any(_overlap(spawn, b) for b in beds), "spawn intersects a bed")
        facing = team["facing"]
        _require(math.isclose(math.hypot(facing["x"], facing["z"]), 1, rel_tol=1e-12, abs_tol=1e-12),
                 "spawn facing must be a unit vector")
        shop = _center_box(team["shop"], 2, 2)
        _require(_inside(shop, region_map[("shop", team_id)]), "shop protection does not cover its point ±1")
        _require(_inside(shop, bounds) and _supported(shop, islands), "shop region is not supported")
    ground = profile["ground_items"]
    for gen in generators:
        _require(gen["position"]["y"] == ground["center_y"], "generator item center height disagrees with profile")
        box = _center_box(gen["position"], ground["width"], ground["depth"])
        _require(_inside(box, bounds) and _supported(box, islands), "generator item is outside supported ground")
        _require(not any(_overlap(box, bed) for bed in beds), "generator item intersects a bed")
        _require(_inside(_center_box(gen["position"], 2, 2), region_map[("generator", gen["generator_id"])]),
                 "generator protection does not cover its point ±1")


def _validate_scenario(profile: dict, map_data: dict, scenario: dict) -> None:
    for name, definition in (("profile", profile), ("map", map_data)):
        ref = scenario[name]
        _require(ref["id"] == definition[f"{name}_id"] and ref["version"] == definition[f"{name}_version"],
                 f"scenario {name} reference mismatch")
    players = scenario["players"]
    _unique([p["player_id"] for p in players], "player id")
    team_ids = {t["team_id"] for t in map_data["teams"]}
    _require(len(players) == profile["game"]["teams"] * profile["game"]["players_per_team"],
             "scenario has the wrong number of players")
    _require({p["team_id"] for p in players} == team_ids, "scenario references unknown or missing teams")
    for team_id in team_ids:
        _require(sum(p["team_id"] == team_id for p in players) == profile["game"]["players_per_team"],
                 f"scenario has the wrong roster size for {team_id}")


def validate_l1_definitions(profile: dict, map_data: dict, scenario: dict, *,
                            expected_hashes: Mapping[str, str] | None = None) -> L1Definitions:
    """Validate explicit data, cross-references and optional expected canonical SHA-256 hashes."""
    values = {"profile": profile, "map": map_data, "scenario": scenario}
    for kind, value in values.items():
        schema = _read_json(files("bedwars_arena").joinpath(_DATA, "schemas", f"{kind}-v1.schema.json"))
        _validate_schema(value, schema)
    validate_profile(profile)
    _validate_map(profile, map_data)
    _validate_scenario(profile, map_data, scenario)
    definitions = {}
    for kind, value in values.items():
        encoded = _canonical(value)
        definitions[kind] = Definition(kind, value[f"{kind}_id"], value[f"{kind}_version"],
                                       sha256(encoded).hexdigest(), encoded)
    bundle = L1Definitions(**definitions)
    if expected_hashes is not None:
        _require(isinstance(expected_hashes, Mapping) and set(expected_hashes) == set(values),
                 "expected hashes must specify profile, map and scenario")
        for kind, digest in bundle.hashes.items():
            _require(expected_hashes[kind] == digest, f"{kind} content hash mismatch")
    return bundle


def load_l1_definitions(*, profile_path: str | Path | None = None,
                        map_path: str | Path | None = None, scenario_path: str | Path | None = None,
                        expected_hashes: Mapping[str, str] | None = None) -> L1Definitions:
    """Read bundled definitions, or explicitly supplied files; no dependency on cwd."""
    paths = {"profile": profile_path, "map": map_path, "scenario": scenario_path}
    values = {}
    for kind, path in paths.items():
        source = Path(path) if path is not None else files("bedwars_arena").joinpath(_DATA, _BUILTIN[kind])
        values[kind] = _read_json(source)
    return validate_l1_definitions(values["profile"], values["map"], values["scenario"],
                                   expected_hashes=expected_hashes)
