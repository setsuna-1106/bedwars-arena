"""Behavioral checks for team transactions, restoration and time boundaries."""

from dataclasses import replace
import json
import unittest

from bedwars_arena.core.rules import (GameMode, TeamRules, UnresolvedRuleError,
                                      load_team_rules, validate_team_state)
from bedwars_arena.core.scheduler import EventQueue, Phase, ScheduledEvent
from bedwars_arena.core.team import (BedState, BedStatus, LifeStatus, MemberView,
                                     TeamState, TrapState, TrapType, UpgradeId,
                                     team_active, validate_match_teams)
from bedwars_arena.core.team_rules import (Rejection, death_destination, destroy_bed,
    purchase_trap, purchase_upgrade, settle_elimination, trigger_trap)
from bedwars_arena.core.time import MAX_SAFE_INTEGER, integer, seconds_to_ticks


class TeamBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.members = (
            MemberView("a", "red", LifeStatus.ALIVE),
            MemberView("b", "red", LifeStatus.ALIVE),
            MemberView("y", "blue", LifeStatus.ALIVE),
            MemberView("x", "blue", LifeStatus.ALIVE),
        )
        self.rules = load_team_rules(GameMode.DOUBLES, accept_community_prices=True)
        self.team = TeamState.initial("red", t0=10)

    def buy(self, team=None, *, bag=None, payer="a", trap_id="trap-1", max_cost=4, now=10):
        return purchase_trap(self.team if team is None else team,
                             {"diamond": 20, "wool": 64} if bag is None else bag,
                             members=self.members, payer=payer, trap_type=TrapType.MINER_FATIGUE,
                             trap_id=trap_id, max_cost=max_cost, now=now, rules=self.rules, can_shop=True)

    def test_price_change_rechecks_budget_without_partial_charge(self):
        original = {"diamond": 5, "wool": 64}
        first = self.buy(bag=original, max_cost=1)
        second = self.buy(first.team, bag={"diamond": 8}, payer="b", trap_id="trap-2", max_cost=1)
        self.assertEqual(second.rejection, Rejection.PRICE_LIMIT)
        self.assertIs(second.team, first.team)
        self.assertEqual(second.inventory["diamond"], 8)
        self.assertIsNone(second.event)
        self.assertEqual(first.inventory["diamond"], 4)
        self.assertEqual(original, {"diamond": 5, "wool": 64})
        third = self.buy(first.team, bag=first.inventory, trap_id="trap-2", max_cost=4)
        self.assertEqual(third.inventory["diamond"], 2)
        self.assertEqual(third.event["cost_diamond"], 2)

    def test_duplicate_types_are_instances_and_capacity_is_enforced(self):
        state = self.team
        for index, cost in enumerate((1, 2, 4)):
            result = self.buy(state, trap_id=f"t{index}")
            self.assertTrue(result.accepted)
            self.assertEqual(result.event["cost_diamond"], cost)
            state = result.team
        self.assertEqual(len({trap.trap_id for trap in state.trap_queue}), 3)
        rejected = self.buy(state, trap_id="fourth")
        self.assertEqual(rejected.rejection, Rejection.QUEUE_FULL)
        self.assertEqual(rejected.inventory["diamond"], 20)
        self.assertIs(rejected.team, state)

    def test_same_target_upgrade_charged_once_without_auto_promotion(self):
        def buy(team, payer):
            return purchase_upgrade(team, {"diamond": 100}, members=self.members,
                payer=payer, upgrade=UpgradeId.REINFORCED_ARMOR, target_level=1,
                now=10, rules=self.rules, can_shop=True)
        first = buy(self.team, "a")
        second = buy(first.team, "b")
        self.assertEqual(first.inventory["diamond"], 98)
        self.assertEqual(second.rejection, Rejection.TARGET_LEVEL)
        self.assertEqual(second.inventory["diamond"], 100)
        self.assertEqual(second.team.upgrades[UpgradeId.REINFORCED_ARMOR], 1)

    def test_modes_have_separate_candidate_prices_and_opt_in(self):
        with self.assertRaises(UnresolvedRuleError):
            load_team_rules(GameMode.SOLO).upgrade_price(UpgradeId.REINFORCED_ARMOR, 1)
        for mode, expected in ((GameMode.SOLO, 2), (GameMode.DOUBLES, 2),
                               (GameMode.THREES, 5), (GameMode.FOURS, 5)):
            rules = load_team_rules(mode, accept_community_prices=True)
            self.assertEqual(rules.upgrade_price(UpgradeId.REINFORCED_ARMOR, 1), expected)
            self.assertEqual(rules.effect_duration_ticks["miner_fatigue"], 160)
            self.assertIsNone(rules.shared_trap_cooldown_ticks)
        with self.assertRaises(ValueError):
            load_team_rules("4v4")

    def test_unknown_cooldown_never_consumes_a_trap(self):
        state = self.buy().team
        with self.assertRaises(UnresolvedRuleError):
            trigger_trap(state, members=self.members, eligible_player_ids=["x"], now=10, rules=self.rules)
        self.assertEqual(len(state.trap_queue), 1)
        self.assertEqual(state.trap_ready_at, 10)

    def test_cooldown_boundary_and_resident_intruders(self):
        rules = self.rules.with_cooldown(40, origin="test fixture; not a Hypixel claim")
        state = self.buy().team
        state = self.buy(state, trap_id="second").team
        fired = trigger_trap(state, members=self.members, eligible_player_ids=["x", "y", "a"], now=10, rules=rules)
        self.assertEqual(fired.event["triggered_by"], "y")
        self.assertEqual(fired.team.trap_ready_at, 50)
        early = trigger_trap(fired.team, members=self.members, eligible_player_ids=["y"], now=49, rules=rules)
        self.assertEqual(early.rejection, Rejection.NO_TRIGGER)
        next_fire = trigger_trap(early.team, members=self.members, eligible_player_ids=["y"], now=50, rules=rules)
        self.assertTrue(next_fire.accepted)
        self.assertEqual(len(next_fire.team.trap_queue), 0)
        purchased = self.buy(next_fire.team, trap_id="third", now=51).team
        self.assertEqual(purchased.trap_ready_at, 90)
        self.assertEqual(trigger_trap(purchased, members=self.members, eligible_player_ids=["y"],
                                    now=89, rules=rules).rejection, Rejection.NO_TRIGGER)

    def test_bed_loss_and_team_elimination_keep_state_but_disable_operations(self):
        state = self.buy().team
        broken = destroy_bed(state, now=12, source="x", cause="player").team
        self.assertEqual(broken.trap_queue, state.trap_queue)
        self.assertEqual(broken.trap_ready_at, state.trap_ready_at)
        self.assertEqual(destroy_bed(broken, now=13, source="x", cause="player").rejection,
                         Rejection.BED_ALREADY_DESTROYED)
        self.assertTrue(self.buy(broken, trap_id="after-bed-loss", now=13).accepted)
        after = tuple(replace(m, life=LifeStatus.ELIMINATED) if m.team_id == "red" else m for m in self.members)
        settled = settle_elimination(broken, before=self.members, after=after, now=14)
        self.assertIs(settled.team, broken)
        self.assertEqual(settled.event["kind"], "team_eliminated")
        self.assertIsNone(settle_elimination(broken, before=after, after=after, now=15).event)
        self.assertEqual(trigger_trap(broken, members=after, eligible_player_ids=["x"],
                                    now=15, rules=self.rules).rejection, Rejection.NO_TRIGGER)
        denied = purchase_trap(broken, {"diamond": 50}, members=after, payer="a",
            trap_type=TrapType.REVEAL, trap_id="no", max_cost=4, now=15, rules=self.rules, can_shop=True)
        self.assertEqual(denied.rejection, Rejection.INELIGIBLE)

    def test_waiting_respawn_keeps_team_active_even_after_bed_loss(self):
        self.assertEqual(death_destination(self.team), LifeStatus.RESPAWNING)
        waiting = tuple(replace(m, life=LifeStatus.RESPAWNING) if m.team_id == "red" else m for m in self.members)
        broken = destroy_bed(self.team, now=11, source="x", cause="player").team
        self.assertTrue(team_active("red", waiting))
        self.assertEqual(death_destination(broken), LifeStatus.ELIMINATED)

    def test_json_round_trip_detaches_nested_values_and_preserves_cooldown(self):
        state = replace(self.buy().team, trap_ready_at=500)
        raw = json.loads(json.dumps(state.to_dict()))
        restored = TeamState.from_dict(raw)
        raw["trap_queue"][0]["trap_id"] = "mutated"
        self.assertEqual(restored.to_dict(), state.to_dict())
        self.assertEqual(restored.trap_ready_at, 500)
        rules = self.rules.with_cooldown(40, origin="experiment fixture")
        self.assertEqual(TeamRules.from_dict(json.loads(json.dumps(rules.to_dict()))), rules)
        with self.assertRaises(TypeError):
            restored.upgrades[UpgradeId.FORGE] = 1

    def test_snapshot_validation_rejects_unknown_ids_and_invalid_quantities(self):
        raw = self.team.to_dict()
        raw["upgrades"] = {"invented": 1}
        with self.assertRaises(ValueError):
            TeamState.from_dict(raw)
        for value in (True, -1, 1.5, MAX_SAFE_INTEGER + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.buy(bag={"diamond": value})
        with self.assertRaises(ValueError):
            BedState(BedStatus.PRESENT, 5)
        with self.assertRaises(ValueError):
            validate_team_state(replace(self.team, upgrades={UpgradeId.FORGE: 5}), self.rules)

    def test_roster_and_match_wide_trap_id_validation(self):
        state = self.buy().team
        blue = TeamState("blue", trap_queue=(TrapState("trap-1", TrapType.REVEAL, "x", 10),))
        with self.assertRaises(ValueError):
            validate_match_teams([state, blue], self.members)
        with self.assertRaises(ValueError):
            team_active("unused-map-slot", self.members)
        with self.assertRaises(ValueError):
            settle_elimination(state, before=self.members, after=self.members[::-1], now=10)


class EventOrderingTests(unittest.TestCase):
    def event(self, name, phase=Phase.PURCHASES, rank=0, tick=100):
        return ScheduledEvent.create(tick=tick, phase=phase, actor_order=rank, event_id=name,
                                     payload={"kind": "purchase", "nested": [1, 2]})

    def test_arrival_order_does_not_determine_execution_order(self):
        events = [self.event("b", rank=1), self.event("a", rank=0),
                  self.event("bed", Phase.BED_DESTRUCTION), self.event("death", Phase.DAMAGE_AND_DEATH)]
        traces = []
        for submitted in (events, events[::-1]):
            queue = EventQueue()
            for event in submitted:
                queue.schedule(event)
            trace = []
            while (event := queue.pop()) is not None:
                trace.append(event.event_id)
            traces.append(trace)
        self.assertEqual(traces[0], ["a", "b", "bed", "death"])
        self.assertEqual(traces[0], traces[1])

    def test_same_tick_bed_destruction_precedes_death(self):
        queue = EventQueue()
        queue.schedule(self.event("death", Phase.DAMAGE_AND_DEATH))
        queue.schedule(self.event("bed", Phase.BED_DESTRUCTION))
        team = TeamState.initial("red", t0=0)
        while (event := queue.pop()) is not None:
            if event.phase == Phase.BED_DESTRUCTION:
                team = destroy_bed(team, now=100, source="x", cause="player").team
            else:
                self.assertEqual(death_destination(team), LifeStatus.ELIMINATED)

    def test_restore_keeps_completed_request_dedup_and_future_order(self):
        queue = EventQueue()
        first, second = self.event("first"), self.event("second", rank=1)
        queue.schedule(first)
        queue.schedule(second)
        self.assertEqual(queue.pop(), first)
        restored = EventQueue.restore(json.loads(json.dumps(queue.snapshot())))
        self.assertFalse(restored.schedule(first))
        self.assertFalse(restored.schedule(second))
        self.assertEqual(restored.pop(), second)
        self.assertIsNone(restored.pop())
        with self.assertRaises(ValueError):
            restored.schedule(self.event("first", tick=101))
        with self.assertRaises(ValueError):
            restored.schedule(self.event("past", tick=99))

    def test_identical_payload_new_request_is_not_semantically_deduplicated(self):
        queue = EventQueue()
        self.assertTrue(queue.schedule(self.event("r1")))
        self.assertTrue(queue.schedule(self.event("r2")))
        event = queue.peek()
        changed = event.payload
        changed["nested"].append(3)
        self.assertEqual(event.payload["nested"], [1, 2])
        snapshot = queue.snapshot()
        snapshot["pending"].pop()
        with self.assertRaises(ValueError):
            EventQueue.restore(snapshot)

    def test_time_is_exact_and_bool_is_not_a_tick(self):
        self.assertEqual(seconds_to_ticks("0.05"), 1)
        self.assertEqual(seconds_to_ticks(8), 160)
        for value in ("0.001", "NaN", "Infinity", -1, True, 0.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                seconds_to_ticks(value)
        with self.assertRaises(ValueError):
            integer(True, "tick")

    def test_payload_and_snapshot_cursor_reject_unsafe_wire_numbers(self):
        for payload in ({"bad": float("nan")}, {"bad": 2**53}, {1: "not a string key"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ScheduledEvent.create(tick=0, phase=Phase.CONTROLS, actor_order=0,
                                      event_id="invalid", payload=payload)
        queue = EventQueue()
        queue.schedule(self.event("done", tick=1))
        queue.pop()
        snapshot = queue.snapshot()
        snapshot["cursor"][0] = True
        with self.assertRaises(ValueError):
            EventQueue.restore(snapshot)


if __name__ == "__main__":
    unittest.main()
