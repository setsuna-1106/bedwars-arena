"""Internal transaction plans: all state, queue, ID and fact changes commit together."""
from copy import deepcopy
from dataclasses import dataclass, field

from .messages import FactEvent, Intent, ScheduledTask
from .scheduler import _json
from .time import integer


@dataclass
class ChangeSet:
    """Produced from an isolated state copy. No effect until the engine validates it."""
    base_next_id: int
    next_id: int
    base_revision: int
    players: dict = field(default_factory=dict)
    teams: dict = field(default_factory=dict)
    terrain: dict = field(default_factory=dict)
    generators: dict = field(default_factory=dict)
    entities: dict = field(default_factory=dict)
    add_tasks: list = field(default_factory=list)
    consume_tasks: list = field(default_factory=list)
    cancel_tasks: list = field(default_factory=list)
    add_intents: list = field(default_factory=list)
    consume_intents: list = field(default_factory=list)
    pending_deaths: list = field(default_factory=list)
    facts: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    execution_updates: dict = field(default_factory=dict)
    result: dict | None = None

    @classmethod
    def from_state(cls, state: dict):
        next_id = state['execution']['next_id']
        return cls(next_id, next_id, state['execution']['revision'])

    def allocate(self) -> str:
        integer(self.next_id, 'next_id', 1)
        value = f'i{self.next_id:016x}'
        self.next_id += 1
        return value

    def emit(self, *, kind: str, tick: int, phase: int, payload: dict,
             caused_by: dict | None = None) -> FactEvent:
        # All facts in one plan share the same commit ID.
        if not self.facts:
            commit_id = self.allocate()
        else:
            commit_id = self.facts[0].commit_id
        fact = FactEvent.create(fact_id=self.allocate(), commit_id=commit_id, kind=kind,
                                happened_at=tick, phase=phase, payload=payload, caused_by=caused_by)
        self.facts.append(fact)
        return fact


def schedule(state: dict, task: ScheduledTask, budget: dict) -> bool:
    """Idempotent same-content retry; check closed phase even when the queue is empty."""
    if not isinstance(task, ScheduledTask):
        raise ValueError('Expected ScheduledTask')
    execution = state['execution']
    encoded = _json(task.to_dict())
    previous = execution['seen_messages'].get(task.task_id)
    if previous is not None:
        if previous != encoded:
            raise ValueError('Message ID reused with different content')
        return False
    cursor = execution['cursor']
    if (task.execute_at, task.phase) <= (cursor['tick'], cursor['phase']):
        raise ValueError('Cannot schedule into a started or completed phase')
    if len(execution['pending_tasks']) >= budget['active_scheduled_tasks']:
        raise ValueError('Scheduled task budget exceeded')
    if len(execution['seen_messages']) >= budget['seen_messages_and_requests']:
        raise ValueError('Message ledger budget exceeded')
    execution['seen_messages'][task.task_id] = encoded
    execution['pending_tasks'].append(task.to_dict())
    execution['pending_tasks'].sort(key=lambda item: ScheduledTask.from_dict(item).key)
    return True


def apply_plan(state: dict, plan: ChangeSet, *, budget: dict, validate) -> tuple[dict, tuple[FactEvent, ...]]:
    """Build a candidate, validate it completely, then return it with committed facts.

    `state` is never modified, including when validation raises. The caller owns
    publishing the returned candidate and must never expose intermediate ticks.
    """
    if (not isinstance(plan, ChangeSet) or state['execution']['next_id'] != plan.base_next_id
            or state['execution']['revision'] != plan.base_revision):
        raise ValueError('Stale or invalid transaction plan')
    integer(plan.next_id, 'next_id', 1)
    if plan.next_id < plan.base_next_id:
        raise ValueError('ID counter cannot go backwards')
    if plan.next_id - plan.base_next_id > budget['work_items_per_tick']:
        raise ValueError('Transaction ID allocation budget exceeded')
    allocated = {f'i{number:016x}' for number in range(plan.base_next_id, plan.next_id)}
    for task in plan.add_tasks:
        if task.task_id not in state['execution']['seen_messages'] and task.task_id not in allocated:
            raise ValueError('New task ID was not allocated by this plan')
    for intent in plan.add_intents:
        if intent.intent_id not in state['execution']['seen_messages'] and intent.intent_id not in allocated:
            raise ValueError('New intent ID was not allocated by this plan')
    for fact in plan.facts:
        if fact.fact_id not in allocated or fact.commit_id not in allocated:
            raise ValueError('Fact or commit ID was not allocated by this plan')
    candidate = deepcopy(state)
    execution = candidate['execution']
    allowed_execution = {'pending_requests','request_records','round','round_history','action_outcomes','packet_errors','attributed_beds','pending_deaths'}
    if not isinstance(plan.execution_updates,dict) or plan.execution_updates.keys() - allowed_execution:
        raise ValueError('Invalid execution updates')
    for key,value in plan.execution_updates.items():
        execution[key] = deepcopy(value)
    for field_name in ('players','teams','generators','entities'):
        updates = getattr(plan, field_name)
        if not isinstance(updates, dict):
            raise ValueError('Invalid state updates')
        for key, value in updates.items():
            if value is None:
                candidate[field_name].pop(key, None)
            else:
                candidate[field_name][key] = deepcopy(value)
    for key, value in plan.terrain.items():
        if value is None:
            candidate['terrain'].pop(key, None)
        else:
            candidate['terrain'][key] = deepcopy(value)
    pending = {item['id']: item for item in execution['pending_tasks']}
    if len(set(plan.consume_tasks)) != len(plan.consume_tasks):
        raise ValueError('Duplicate task consumption')
    for task_id in plan.consume_tasks:
        if task_id not in pending:
            raise ValueError('Cannot consume absent task')
        item = ScheduledTask.from_dict(pending.pop(task_id))
        cursor = execution['cursor']
        if (item.execute_at, item.phase) != (cursor['tick'], cursor['phase']):
            raise ValueError('Cannot consume task outside its phase')
    execution['pending_tasks'] = sorted(pending.values(), key=lambda item: ScheduledTask.from_dict(item).key)
    for task_id in plan.cancel_tasks:
        if task_id not in execution['seen_messages']:
            raise ValueError('Cannot cancel an unknown task')
        record = execution['seen_messages'][task_id]
        if '"category":"task"' not in record:
            raise ValueError('Only tasks may be cancelled')
        if task_id not in execution['cancelled']:
            execution['cancelled'].append(task_id)
    execution['cancelled'].sort()
    for task in plan.add_tasks:
        schedule(candidate, task, budget)
    intents = {item['id']: item for item in execution['pending_intents']}
    if len(set(plan.consume_intents)) != len(plan.consume_intents):
        raise ValueError('Duplicate intent consumption')
    for intent_id in plan.consume_intents:
        if intent_id not in intents:
            raise ValueError('Cannot consume absent intent')
        item = intents[intent_id]
        cursor = execution['cursor']
        if (item['created_at'], item['target_phase']) != (cursor['tick'], cursor['phase']):
            raise ValueError('Cannot consume intent outside its target phase')
        del intents[intent_id]
    for intent in plan.add_intents:
        if not isinstance(intent, Intent):
            raise ValueError('Expected Intent')
        raw = intent.to_dict()
        cursor = execution['cursor']
        fingerprint = _json(raw)
        previous = execution['seen_messages'].get(intent.intent_id)
        if previous is not None:
            if previous != fingerprint:
                raise ValueError('Message ID reused with different content')
            continue
        if raw['created_at'] != cursor['tick'] or raw['target_phase'] <= cursor['phase']:
            raise ValueError('Intent must target a later phase of this tick')
        execution['seen_messages'][intent.intent_id] = fingerprint
        intents[intent.intent_id] = raw
    execution['pending_intents'] = sorted(intents.values(), key=lambda x: (x['target_phase'], x['id']))
    if len(intents) > budget['pending_intents']:
        raise ValueError('Pending intent budget exceeded')
    execution['pending_deaths'].extend(deepcopy(plan.pending_deaths))
    if plan.result is not None:
        if candidate['result'] is not None:
            raise ValueError('World result is already fixed')
        candidate['result'] = deepcopy(plan.result)
    for fact in plan.facts:
        if not isinstance(fact, FactEvent):
            raise ValueError('Expected FactEvent')
        raw = fact.to_dict()
        cursor = execution['cursor']
        if (fact.happened_at, fact.phase) != (cursor['tick'], cursor['phase']):
            raise ValueError('Fact time does not match commit phase')
        if fact.fact_id in execution['seen_messages']:
            raise ValueError('Fact ID already seen')
        execution['seen_messages'][fact.fact_id] = _json(raw)
    if plan.facts and len({f.commit_id for f in plan.facts}) != 1:
        raise ValueError('Facts in a plan must share a commit ID')
    execution['log_cursor'] += len(plan.facts)
    execution['diagnostics'].extend(deepcopy(plan.diagnostics))
    execution['next_id'] = plan.next_id
    execution['revision'] += 1
    if len(execution['seen_messages']) > budget['seen_messages_and_requests']:
        raise ValueError('Message ledger budget exceeded')
    def instance_ids(value):
        ids = {block['instance_id'] for block in value['terrain'].values()}
        ids.update(gen['schedule_id'] for gen in value['generators'].values())
        ids.update(value['entities'].keys())
        for player in value['players'].values():
            life = player['life']
            if life['kind'] == 'alive':
                ids.update(effect['effect_id'] for effect in life['effects'])
                ids.update(life[ch]['action_id'] for ch in ('movement','interaction') if life[ch] is not None)
        return ids
    old_ids, new_ids = instance_ids(state), instance_ids(candidate)
    if not new_ids - old_ids <= allocated:
        raise ValueError('New instance ID was not allocated by this plan')
    if plan.facts and (plan.facts[0].commit_id in new_ids or plan.facts[0].commit_id in execution['seen_messages']):
        raise ValueError('Commit ID collides with another instance or message')
    validate(candidate)
    return candidate, tuple(plan.facts)
