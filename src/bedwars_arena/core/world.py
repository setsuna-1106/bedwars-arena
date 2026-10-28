"""L1 world engine: phase pipeline, atomic commits, scheduling and snapshots."""
from copy import deepcopy

from .messages import Intent, PHASES, ScheduledTask
from .transactions import ChangeSet, apply_plan
from .world_state import create_state, validate_state


class WorldFault(RuntimeError):
    """A batch failed. Restore explicitly from a previously published snapshot."""


class WorldEngine:
    def __init__(self, definitions, state, *, initial_facts=()):
        validate_state(state, definitions, boundary=True)
        self._definitions = definitions
        self._state = deepcopy(state)
        self._published = deepcopy(state)
        self._initial_facts = tuple(deepcopy(initial_facts))
        self._last_facts = ()
        self._fault = None
        self._working_facts = []
        self._phase_has_batch_commit = False

    @classmethod
    def create(cls, definitions, *, seed: int, match_id: str | None = None, preset: dict | None = None):
        state, facts = create_state(definitions, seed=seed, match_id=match_id, preset=preset)
        return cls(definitions, state, initial_facts=facts)

    @property
    def definitions(self):
        """The immutable definition bundle fixed for this engine."""
        return self._definitions

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

    def _publish_input(self, candidate):
        if self._fault is not None or self._state['result'] is not None:
            raise WorldFault('World cannot accept input after fault or result')
        candidate['execution']['revision'] += 1
        validate_state(candidate,self.definitions,boundary=True)
        self._state=candidate
        self._published=deepcopy(candidate)

    def open_round(self, decision_round_id: str):
        from .time import identifier
        identifier(decision_round_id,'decision_round_id')
        execution=self._state['execution']
        current=execution['round']
        if current is not None and current['observed_tick'] == self._state['tick']:
            raise ValueError('A round already exists at this boundary')
        if decision_round_id in execution['round_history']:
            raise ValueError('Decision round ID already used')
        if execution['pending_requests']:
            raise ValueError('Cannot open a round while earlier input is pending')
        candidate=deepcopy(self._state)
        candidate['execution']['round']={'id':decision_round_id,'observed_tick':candidate['tick'],
                                         'sealed':False,'submitted':[]}
        candidate['execution']['round_history'][decision_round_id]=candidate['tick']
        self._publish_input(candidate)

    def receive_actions(self, packet: dict) -> dict:
        from bedwars_arena.interfaces.receiver import receive
        if self._fault is not None or self._state['result'] is not None:
            raise WorldFault('World cannot accept input after fault or result')
        candidate,reply=receive(self._state,self.definitions,packet)
        if candidate is not self._state:
            self._publish_input(candidate)
        return deepcopy(reply)

    def receive_actions_batch(self, packets: list[dict]) -> list[dict]:
        """Atomically publish several independent player receipts at one boundary."""
        from bedwars_arena.interfaces.receiver import receive
        if self._fault is not None or self._state['result'] is not None:
            raise WorldFault('World cannot accept input after fault or result')
        if not isinstance(packets,list):
            raise ValueError('Packets must be a list')
        candidate=self._state
        replies=[]
        for packet in packets:
            candidate,reply=receive(candidate,self.definitions,packet)
            replies.append(deepcopy(reply))
        if candidate is not self._state:
            self._publish_input(candidate)
        return replies

    def seal_round(self):
        current=self._state['execution']['round']
        if current is None or current['observed_tick'] != self._state['tick'] or current['sealed']:
            raise ValueError('No open round at this boundary')
        pending={(d['player_id'],d['life_index']) for d in self._state['execution']['pending_deaths']}
        required={pid for pid,p in self._state['players'].items()
                  if p['life']['kind']=='alive' and (pid,p['life_index']) not in pending}
        if not required.issubset(current['submitted']):
            raise ValueError('Required player packets are missing')
        candidate=deepcopy(self._state)
        candidate['execution']['round']['sealed']=True
        self._publish_input(candidate)

    def observe(self, player_id: str) -> dict:
        from bedwars_arena.interfaces.observations import observe
        return observe(self._published,self.definitions,player_id)

    def feedback(self, player_id: str) -> dict:
        from bedwars_arena.interfaces.observations import feedback
        return feedback(self._published,player_id)

    def _validate(self, value):
        validate_state(value, self.definitions)

    def _commit(self, plan: ChangeSet):
        candidate, facts = apply_plan(self._state, plan, budget=self.definitions.profile.data['budget'],
                                      validate=self._validate)
        self._state = candidate
        self._phase_has_batch_commit = True
        self._working_facts.extend(f.to_dict() for f in facts)

    def _enter_phase(self, tick: int, phase: int):
        old = self._state['execution']['cursor']
        if (tick, phase) <= (old['tick'], old['phase']):
            raise ValueError('Phase cursor must advance')
        execution=self._state['execution']
        target=(tick,phase)
        if any((t['execute_at'],t['phase']) < target for t in execution['pending_tasks']):
            raise ValueError('Scheduled task lies behind the phase cursor')
        if any((r['tick'],r['phase']) < target for r in execution['pending_requests']):
            raise ValueError('Pending request lies behind the phase cursor')
        if any((i['created_at'],i['target_phase']) < target for i in execution['pending_intents']):
            raise ValueError('Pending intent lies behind the phase cursor')
        candidate=self._state.copy()
        candidate['execution']=execution.copy()
        candidate['execution']['cursor']={'tick':tick,'phase':phase}
        candidate['execution']['revision']+=1
        self._state=candidate

    def _phase_plan(self, tick: int, phase: int) -> ChangeSet | None:
        """Build internal phase changes from the current committed state."""
        if phase == 20:
            from .controls import process_controls
            return process_controls(self._state,self.definitions,tick)
        if phase == 35:
            from .controls import interrupt_invalid_interactions
            return interrupt_invalid_interactions(self._state,self.definitions,tick)
        if phase == 60:
            from .combat import resolve_damage_and_deaths
            return resolve_damage_and_deaths(self._state,self.definitions,tick)
        if phase == 70:
            from .outcome import team_eliminations
            return team_eliminations(self._state,self.definitions,tick)
        if phase == 90:
            from .outcome import natural_outcome
            return natural_outcome(self._state,self.definitions,tick)
        if phase != 30:
            return None
        from .geometry import Vec2
        from .physics import move_player
        from .terrain import Terrain
        state = self._state
        profile = self.definitions.profile.data
        terrain = Terrain.from_world(state, self.definitions.map.data)
        awaiting = {(item['player_id'],item['life_index']) for item in state['execution']['pending_deaths']}
        plan = ChangeSet.from_state(state)
        for entry in self.definitions.scenario.data['players']:
            pid = entry['player_id']
            player = state['players'][pid]
            life = player['life']
            if life['kind'] != 'alive':
                continue
            if (pid,player['life_index']) in awaiting:
                if life['spatial']['velocity_x'] or life['spatial']['velocity_z']:
                    updated=deepcopy(player)
                    updated['life']['spatial']['velocity_x']=0.0
                    updated['life']['spatial']['velocity_z']=0.0
                    plan.players[pid]=updated
                continue
            spatial = life['spatial']
            action = life['movement']
            params = {'x':0,'z':0} if action is None else action['params']
            motion = move_player(position=Vec2(spatial['x'],spatial['z']),
                                 direction=Vec2(params['x'],params['z']),
                                 knockback=Vec2(spatial['knockback_x'],spatial['knockback_z']),
                                 terrain=terrain,physics=profile['physics'])
            updated=deepcopy(player)
            new_spatial=updated['life']['spatial']
            new_spatial.update(x=motion.position.x,z=motion.position.z,
                               velocity_x=motion.position.x-spatial['x'],
                               velocity_z=motion.position.z-spatial['z'],
                               knockback_x=motion.knockback.x,knockback_z=motion.knockback.z)
            if updated != player:
                plan.players[pid]=updated
            if motion.contacts:
                plan.emit(kind='movement_collision',tick=tick,phase=30,
                          payload={'player_id':pid,'life_index':player['life_index'],
                                   'contacts':[{'obstacle':list(key),'normal':[nx,nz]}
                                               for key,nx,nz in motion.contacts]})
            if motion.iteration_limit_reached:
                plan.diagnostics.append({'tick':tick,'phase':phase,'player_id':pid,
                                         'reason':'collision_iteration_limit'})
            if motion.void_candidate:
                intent = Intent.create(intent_id=plan.allocate(),kind='void_death_candidate',
                                       created_at=tick,target_phase=60,
                                       payload={'player_id':pid,'life_index':player['life_index'],
                                                'position':{'x':motion.position.x,'z':motion.position.z}})
                plan.add_intents.append(intent)
        if not (plan.players or plan.add_intents or plan.diagnostics or plan.facts):
            return None
        return plan

    def _handle_task(self, task: ScheduledTask) -> ChangeSet:
        state = self._state
        plan = ChangeSet.from_state(state)
        plan.consume_tasks.append(task.task_id)
        reason = None
        if task.task_id in state['execution']['cancelled']:
            reason = 'cancelled'
        elif task.kind == 'respawn':
            from .combat import respawn
            return respawn(state,self.definitions,task)
        elif task.kind == 'global_bed_destruction':
            from .outcome import global_beds
            return global_beds(state,task)
        elif task.kind == 'game_end':
            from .outcome import game_end
            return game_end(state,self.definitions,task)
        elif task.kind == 'generator_spawn':
            from .economy import generator_attempt
            return generator_attempt(state,self.definitions,task)
        elif task.kind == 'expire_ground_item':
            from .economy import expire_ground
            return expire_ground(state,task)
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

    def _process_gameplay_phase(self,tick: int,phase: int,work: int,budget: int) -> int:
        if phase not in (32,40,45,50):
            return work
        from . import building, economy
        roster=[p['player_id'] for p in self.definitions.scenario.data['players']]
        order={pid:i for i,pid in enumerate(roster)}
        tasks=[]
        if phase==32:
            entities=sorted(self._state['entities'].values(),key=lambda e:(e['created_at'],e['entity_id']))
            tasks=[('pickup',pid,e['entity_id']) for pid in roster for e in entities]
        elif phase==40:
            pending=[r for r in self._state['execution']['pending_requests'] if r['tick']==tick and r['phase']==40]
            tasks=[('buy',item,None) for item in sorted(pending,key=lambda r:(order[r['player_id']],r['request_id']))]
        elif phase==45:
            tasks=[('place',pid,None) for pid in roster]
            pending=[r for r in self._state['execution']['pending_requests'] if r['tick']==tick and r['phase']==45]
            tasks.extend(('drop',item,None) for item in sorted(pending,key=lambda r:(order[r['player_id']],r['request_id'])))
        elif phase==50:
            tasks=[('break',pid,None) for pid in roster]
        for kind,first,second in tasks:
            work+=1
            if work>budget:
                raise ValueError('Work budget exceeded')
            if kind=='pickup': plan=economy.pickup(self._state,self.definitions,tick,first,second)
            elif kind=='buy': plan=economy.buy(self._state,self.definitions,tick,first)
            elif kind=='place': plan=building.place(self._state,self.definitions,tick,first)
            elif kind=='drop': plan=economy.drop(self._state,self.definitions,tick,first)
            else: plan=building.break_action(self._state,self.definitions,tick,first)
            if plan is not None:
                self._commit(plan)
        return work

    def _handle_intents(self, tick: int, phase: int, work: int, budget: int) -> int:
        due = [i for i in self._state['execution']['pending_intents'] if i['target_phase'] == phase]
        for raw in due:
            work += 1
            if work > budget:
                raise ValueError('Work budget exceeded')
            if raw['kind'] != 'void_death_candidate' or phase != 60:
                raise ValueError(f'No handler for intent kind {raw["kind"]!r}')
            payload = raw['payload']
            if set(payload) != {'player_id','life_index','position'}:
                raise ValueError('Invalid void candidate')
            plan = ChangeSet.from_state(self._state)
            plan.consume_intents.append(raw['id'])
            player = self._state['players'].get(payload['player_id'])
            if player is None or player['life']['kind'] != 'alive' or player['life_index'] != payload['life_index']:
                plan.diagnostics.append({'tick':tick,'phase':phase,'intent_id':raw['id'],'reason':'stale_life'})
            else:
                plan.pending_deaths.append({'intent_id':raw['id'],'player_id':payload['player_id'],
                                            'life_index':payload['life_index'],'tick':tick,'reason':'void',
                                            'position':deepcopy(payload['position'])})
            self._commit(plan)
        return work

    def step(self) -> dict:
        """Advance exactly one tick, or stop on fault without publishing half a tick."""
        if self._fault is not None:
            raise WorldFault('Faulted world cannot advance; restore a complete snapshot')
        if self._state['result'] is not None:
            raise ValueError('Finished world cannot advance')
        current=self._state['execution']['round']
        if current is not None and current['observed_tick']==self._state['tick'] and not current['sealed']:
            raise ValueError('Seal the decision round before advancing')
        tick = self._state['tick'] + 1
        budget = self.definitions.profile.data['budget']['work_items_per_tick']
        work = 0
        self._working_facts = []
        phase_start = self._state
        self._phase_has_batch_commit = False
        try:
            for phase in PHASES:
                phase_start = self._state
                self._phase_has_batch_commit = False
                self._enter_phase(tick, phase)
                if phase == 30:
                    awaiting = {(item['player_id'],item['life_index']) for item in self._state['execution']['pending_deaths']}
                    work += sum(p['life']['kind']=='alive' and (pid,p['life_index']) not in awaiting
                                for pid,p in self._state['players'].items())
                    if work > budget:
                        raise ValueError('Work budget exceeded')
                plan = self._phase_plan(tick, phase)
                if plan is not None:
                    if phase != 30:
                        work += 1
                    if work > budget:
                        raise ValueError('Work budget exceeded')
                    self._commit(plan)
                work = self._process_gameplay_phase(tick,phase,work,budget)
                while self._state['execution']['pending_tasks']:
                    task = ScheduledTask.from_dict(self._state['execution']['pending_tasks'][0])
                    if (task.execute_at,task.phase) != (tick,phase):
                        break
                    work += 1
                    if work > budget:
                        raise ValueError('Work budget exceeded')
                    self._commit(self._handle_task(task))
                work = self._handle_intents(tick, phase, work, budget)
                if work > budget:
                    raise ValueError('Work budget exceeded')
            candidate = self._state.copy()
            candidate['tick'] = tick
            validate_state(candidate, self.definitions, boundary=True)
            self._state = candidate
            self._published = deepcopy(candidate)
            self._last_facts = tuple(self._working_facts)
            return self.state
        except Exception as error:
            if not self._phase_has_batch_commit:
                # A failed first batch must not leave a partially entered phase.
                self._state = phase_start
            self._fault = f'{type(error).__name__}: {error}'
            self._working_facts = []
            raise WorldFault(f'World failed while advancing tick {tick}: {error}') from error
