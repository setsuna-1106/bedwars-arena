"""L1 world engine foundation. A full game is not yet implemented."""
from copy import deepcopy
import json

from .messages import PHASES, ScheduledTask
from .transactions import ChangeSet, apply_plan
from .world_state import create_state, validate_state


class WorldFault(RuntimeError):
    """A batch failed. Restore explicitly from a previously published snapshot."""


class WorldEngine:
    def __init__(self, definitions, state, *, initial_facts=()):
        validate_state(state, definitions, boundary=True, check_positions=True)
        self.definitions = definitions
        self._state = deepcopy(state)
        self._published = deepcopy(state)
        self._initial_facts = tuple(deepcopy(initial_facts))
        self._last_facts = ()
        self._fault = None
        self._working_facts = []

    @classmethod
    def create(cls, definitions, *, seed: int, match_id: str | None = None, preset: dict | None = None):
        state, facts = create_state(definitions, seed=seed, match_id=match_id, preset=preset)
        return cls(definitions, state, initial_facts=facts)

    @property
    def state(self) -> dict:
        """Only the last complete boundary, detached from the engine."""
        return deepcopy(self._published)

    @property
    def initial_facts(self) -> tuple[dict, ...]:
        return tuple(deepcopy(self._initial_facts))

    @property
    def last_facts(self) -> tuple[dict, ...]:
        return tuple(deepcopy(self._last_facts))

    @property
    def fault(self) -> str | None:
        return self._fault

    def snapshot(self) -> dict:
        """A detached last complete boundary, even after a later tick faults."""
        from bedwars_arena.replay.snapshot import encode_snapshot
        return encode_snapshot(self._published, self.definitions)

    def _validate(self, value):
        validate_state(value, self.definitions)

    def _commit(self, plan: ChangeSet):
        candidate, facts = apply_plan(self._state, plan, budget=self.definitions.profile.data['budget'],
                                      validate=self._validate)
        self._state = candidate
        self._working_facts.extend(f.to_dict() for f in facts)

    def _enter_phase(self, tick: int, phase: int):
        candidate = deepcopy(self._state)
        old = candidate['execution']['cursor']
        if (tick, phase) <= (old['tick'], old['phase']):
            raise ValueError('Phase cursor must advance')
        candidate['execution']['cursor'] = {'tick':tick,'phase':phase}
        candidate['execution']['revision'] += 1
        self._validate(candidate)
        self._state = candidate

    def _phase_plan(self, tick: int, phase: int) -> ChangeSet | None:
        """Override for built-in pure phase handlers; never called by strategies."""
        return None

    def _handle_task(self, task: ScheduledTask) -> ChangeSet:
        state = self._state
        plan = ChangeSet.from_state(state)
        plan.consume_tasks.append(task.task_id)
        reason = None
        if task.task_id in state['execution']['cancelled']:
            reason = 'cancelled'
        elif task.kind == 'expire_protection':
            payload = task.payload
            if set(payload) != {'player_id','life_index','effect_id'}:
                raise ValueError('Invalid protection expiration payload')
            player = state['players'].get(payload['player_id'])
            if player is None or player['life_index'] != payload['life_index'] or player['life']['kind'] != 'alive':
                reason = 'stale_life'
            else:
                effects = player['life']['effects']
                target = next((effect for effect in effects if effect['effect_id'] == payload['effect_id']), None)
                if target is None or target['expires_at'] != task.execute_at:
                    reason = 'stale_instance'
                else:
                    updated = deepcopy(player)
                    updated['life']['effects'] = [effect for effect in effects if effect['effect_id'] != target['effect_id']]
                    plan.players[player['player_id']] = updated
                    plan.emit(kind='protection_expired', tick=task.execute_at, phase=task.phase,
                              payload={'player_id':player['player_id'],'life_index':player['life_index'],
                                       'effect_id':target['effect_id']},
                              caused_by={'category':'task','id':task.task_id})
        else:
            raise ValueError(f'No handler for scheduled task kind {task.kind!r}')
        if reason is not None:
            plan.diagnostics.append({'tick':task.execute_at,'phase':task.phase,'task_id':task.task_id,'reason':reason})
        return plan

    def _handle_intents(self, tick: int, phase: int) -> None:
        due = [i for i in self._state['execution']['pending_intents'] if i['target_phase'] == phase]
        if due:
            raise ValueError(f'No handler for intent kind {due[0]["kind"]!r}')

    def step(self) -> dict:
        """Advance exactly one tick, or stop on fault without publishing half a tick."""
        if self._fault is not None:
            raise WorldFault('Faulted world cannot advance; restore a complete snapshot')
        if self._state['result'] is not None:
            raise ValueError('Finished world cannot advance')
        tick = self._state['tick'] + 1
        budget = self.definitions.profile.data['budget']['work_items_per_tick']
        work = 0
        self._working_facts = []
        try:
            for phase in PHASES:
                self._enter_phase(tick, phase)
                plan = self._phase_plan(tick, phase)
                if plan is not None:
                    work += 1
                    if work > budget:
                        raise ValueError('Work budget exceeded')
                    self._commit(plan)
                while self._state['execution']['pending_tasks']:
                    task = ScheduledTask.from_dict(self._state['execution']['pending_tasks'][0])
                    if (task.execute_at,task.phase) != (tick,phase):
                        break
                    work += 1
                    if work > budget:
                        raise ValueError('Work budget exceeded')
                    self._commit(self._handle_task(task))
                self._handle_intents(tick, phase)
                if work > budget:
                    raise ValueError('Work budget exceeded')
            candidate = deepcopy(self._state)
            candidate['tick'] = tick
            validate_state(candidate, self.definitions, boundary=True)
            self._state = candidate
            self._published = deepcopy(candidate)
            self._last_facts = tuple(self._working_facts)
            return self.state
        except Exception as error:
            self._fault = f'{type(error).__name__}: {error}'
            self._working_facts = []
            raise WorldFault(f'World failed while advancing tick {tick}: {error}') from error
