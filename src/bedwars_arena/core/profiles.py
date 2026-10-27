"""Validation of the selected L1 experimental rule profile.

This is definition validation, not an implementation of any game handler.
"""

import math
from typing import Any


class L1DefinitionError(ValueError):
    """A definition is malformed, unsupported, or internally inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise L1DefinitionError(message)


def validate_profile(profile: dict[str, Any]) -> None:
    """Validate interdependent L1 fields after the closed schema is checked."""
    g, p = profile["game"], profile["physics"]
    inventory, shop = profile["inventory"], profile["shop"]
    building, generators = profile["building"], profile["generators"]
    ground, combat = profile["ground_items"], profile["combat"]
    life, schedule, protocol, budget = (profile[k] for k in ("life", "schedule", "protocol", "budget"))

    policies = {
        ("game", "coordinate_unit"): "block", ("game", "horizontal_axes"): "x_z",
        ("game", "resource"): "iron", ("game", "player_order"): "scenario_order",
        ("physics", "movement_input"): "world_direction_normalized",
        ("physics", "void_rule"): "first_loss_of_positive_area_support",
        ("inventory", "armor_on_death"): "retain", ("shop", "currency"): "iron",
        ("building", "item"): "wool", ("building", "recovery_tool"): "shears",
        ("building", "recovery_destination"): "inventory_then_safe_drop_else_destroy",
        ("building", "bridge_support"): "four_neighbor", ("building", "wall_support"): "below",
        ("building", "bridge_under_wall"): "reject_until_wall_removed",
        ("generators", "full_behavior"): "continue_schedule_without_backlog",
        ("generators", "resource"): "iron",
        ("ground_items", "movement"): "stationary_remove_when_unsupported",
        ("ground_items", "pickup_order"): "player_then_created_at_entity_id",
        ("combat", "cooldowns_on_death"): "clear",
        ("life", "protection_effect"): "blocks_melee_damage_knockback_attribution",
        ("protocol", "observation"): "global_isolated",
    }
    for (section, name), expected in policies.items():
        _require(profile[section][name] == expected, f"{section}.{name}: unsupported policy")
    for section, key in (("shop", "requires_line_of_sight"), ("shop", "requires_facing"),
                         ("building", "original_islands_breakable"), ("combat", "friendly_fire"),
                         ("combat", "friendly_knockback"), ("life", "protection_blocks_void")):
        _require(profile[section][key] is False, f"{section}.{key}: unsupported feature")
    _require(combat["melee_line_of_sight"] is True, "combat.melee_line_of_sight must be enabled")
    _require(g["feet_y"] == 0, "game.feet_y must be 0 in the L1 flat world")
    _require(g["decision_interval_ticks"] > 0, "decision interval must be positive")

    for key in ("player_width", "player_depth", "player_height", "speed_blocks_per_second",
                "speed_blocks_per_tick", "knockback_per_hit", "knockback_speed_cap",
                "knockback_stop_below", "contact_distance_tolerance", "contact_time_tolerance",
                "velocity_zero_tolerance", "collision_iterations_per_tick"):
        _require(p[key] > 0, f"physics.{key} must be positive")
    for key in ("control_alpha", "control_beta", "knockback_decay"):
        _require(0 <= p[key] <= 1, f"physics.{key} must be in [0, 1]")
    _require(math.isclose(p["speed_blocks_per_second"] / g["ticks_per_second"],
                          p["speed_blocks_per_tick"], rel_tol=1e-12, abs_tol=0),
             "speed per tick and per second disagree")
    _require(p["knockback_per_hit"] <= p["knockback_speed_cap"], "knockback exceeds its cap")
    _require(p["velocity_zero_tolerance"] < p["knockback_stop_below"],
             "velocity tolerance must be below the control recovery threshold")

    limits = inventory["stack_limits"]
    _require(inventory["stack_capacity"] > 0 and all(v > 0 for v in limits.values()),
             "inventory capacity and stack limits must be positive")
    _require(all(limits[item] == 1 for item in ("wooden_sword", "iron_sword", "shears")),
             "L1 swords and shears are unstackable")
    _require(inventory["initial_armor_tier"] == 0, "L1 starts without upgraded armor")
    initial = inventory["initial_items"]
    _require(initial == {"wooden_sword": 1, "shears": 1}, "L1 initial equipment must contain one sword and shears")
    _require(initial.get(inventory["initial_held_item"], 0) > 0,
             "initial held item must be in the initial inventory")
    _require(sum((q + limits[item] - 1) // limits[item] for item, q in initial.items())
             <= inventory["stack_capacity"], "initial inventory exceeds capacity")
    _require(shop["range_blocks"] > 0, "shop range must be positive")
    expected_products = {"wool": ("wool", "item"),
                         "iron_sword": ("iron_sword", "replace_wooden_sword"),
                         "armor_1": ("armor_1", "armor_progression")}
    for name, (item, kind) in expected_products.items():
        product = shop["products"][name]
        _require(product["item"] == item and product["kind"] == kind,
                 f"shop.products.{name}: invalid item or product kind")
        _require(product["cost"] > 0 and product["quantity"] > 0,
                 f"shop.products.{name}: cost and quantity must be positive")
        if name != "wool":
            _require(product["quantity"] == 1, f"shop.products.{name}: must issue one upgrade")
    _require(shop["products"]["wool"]["quantity"] <= limits["wool"] * inventory["stack_capacity"],
             "wool product cannot fit in an empty inventory")
    _require(building["recovery_quantity"] == 1, "L1 recovers one wool per block")
    for key in ("range_blocks", "placement_duration_ticks", "wool_break_duration_ticks", "bed_break_duration_ticks"):
        _require(building[key] > 0, f"building.{key} must be positive")
    _require(0 < building["facing_half_angle_degrees"] <= 180, "invalid building facing angle")
    _require(building["bridge_y"] == -1 and building["wall_y"] == 0,
             "L1 bridge and wall layers must be -1 and 0")

    for name in ("base", "central"):
        stream = generators[name]
        _require(all(stream[k] > 0 for k in ("first_spawn_ticks", "period_ticks", "quantity", "capacity")),
                 f"generators.{name}: times, quantity and capacity must be positive")
    _require(generators["central"]["quantity"] * generators["base"]["period_ticks"] >
             generators["base"]["quantity"] * generators["central"]["period_ticks"],
             "central generation must be faster than base generation")
    _require(generators["accumulation_half_width"] > 0 and
             generators["accumulation_min_y"] < generators["accumulation_max_y"],
             "invalid generator accumulation region")
    for key in ("pickup_horizontal_expansion", "pickup_vertical_expansion"):
        _require(ground[key] >= 0, f"ground_items.{key} must be nonnegative")
    for key in ("generator_pickup_delay_ticks", "drop_pickup_delay_ticks", "death_pickup_delay_ticks",
                "recovery_pickup_delay_ticks"):
        _require(ground[key] >= 0, f"ground_items.{key} must be nonnegative")
    _require(ground["lifetime_ticks"] > 0, "ground item lifetime must be positive")
    _require(all(ground[key] < ground["lifetime_ticks"] for key in
                 ("generator_pickup_delay_ticks", "drop_pickup_delay_ticks", "death_pickup_delay_ticks",
                  "recovery_pickup_delay_ticks")), "pickup delay must be shorter than item lifetime")
    for key in ("width", "depth", "height"):
        _require(ground[key] > 0, f"ground_items.{key} must be positive")
    _require(ground["center_y"] == ground["height"] / 2,
             "ground item center must rest on the walking surface")
    for key, limit in ground["entity_limits"].items():
        _require(limit > 0, f"ground item limit for {key} must be positive")

    for key in ("max_hp", "wooden_sword_damage", "iron_sword_damage", "range_blocks",
                "attack_interval_ticks", "hurt_interval_ticks", "attribution_window_ticks"):
        _require(combat[key] > 0, f"combat.{key} must be positive")
    _require(combat["base_armor_reduction"] == 0 and 0 < combat["armor_1_reduction"] < 1,
             "armor reductions must define an unarmored and one upgraded tier")
    _require(0 < combat["facing_half_angle_degrees"] <= 180, "invalid combat facing angle")
    _require(life["respawn_delay_ticks"] > 0 and life["protection_duration_ticks"] > 0,
             "respawn and protection durations must be positive")
    _require(0 < schedule["global_bed_destruction_tick"] < schedule["game_end_tick"],
             "global bed destruction must precede Game End")
    _require(schedule["episode_limit_ticks"] > 0, "episode limit must be positive")
    for key in ("action_version", "feedback_version", "observation_version", "world_snapshot_version_reserved",
                "team_state_version", "legacy_queue_version"):
        _require(protocol[key] == 1, f"unsupported protocol/version reservation: {key}")
    _require(protocol["policy_soft_timeout_ms"] > 0, "policy soft timeout must be positive")
    _require((protocol["team_reward_win"], protocol["team_reward_loss"], protocol["team_reward_draw"])
             == (1, -1, 0), "L1 team result rewards must be +1/-1/0")
    _require(all(v > 0 for v in budget.values()), "all engineering budgets must be positive")
