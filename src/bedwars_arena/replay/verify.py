"""Re-execute recorded input from a complete boundary and compare every tick."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from bedwars_arena.core.definitions import _read_json, validate_l1_definitions
from bedwars_arena.core.world import WorldFault
from bedwars_arena.core.world_state import definition_ref, runtime_info
from bedwars_arena.replay.record import apply_changes, canonical, decode_packet, first_difference, state_hash
from bedwars_arena.replay.snapshot import restore_snapshot


class ReplayMismatch(ValueError):
    def __init__(self,tick,path,expected,actual):
        self.tick=tick;self.path=path;self.expected=expected;self.actual=actual
        super().__init__(f'tick {tick}: first difference at {path}: expected {str(expected)[:300]!r}, got {str(actual)[:300]!r}')


def _compare(expected,actual,tick,path):
    diff=first_difference(expected,actual,path)
    if diff:
        raise ReplayMismatch(tick,*diff)


def _lines(path):
    try:
        with path.open(encoding='utf-8') as source:
            return [json.loads(line) for line in source if line.strip()]
    except (OSError,UnicodeError,json.JSONDecodeError) as error:
        raise ValueError(f'Cannot read complete replay log {path.name}: {error}') from error


def _load(directory):
    root=Path(directory)
    manifest=_read_json(root/'manifest.json')
    if manifest.get('kind')!='l1-run-manifest' or manifest.get('schema_version')!=2:
        raise ValueError('Unsupported replay record version: P7 records require manifest schema 2')
    if manifest.get('runtime')!=runtime_info():
        raise ValueError('Replay runtime or package version mismatch')
    data=_read_json(root/'definitions.json')
    if set(data)!={'profile','map','scenario'}:
        raise ValueError('Invalid replay definitions')
    definitions=validate_l1_definitions(data['profile'],data['map'],data['scenario'])
    if definition_ref(definitions)!=manifest.get('definitions'):
        raise ValueError('Replay definition hash/version mismatch')
    inputs=_lines(root/'inputs.jsonl');external=_lines(root/'external-inputs.jsonl')
    rounds=_lines(root/'rounds.jsonl');events=_lines(root/'events.jsonl')
    for name,items in (('input',inputs),('external_input',external),('round',rounds),('fact',events)):
        if len(items)!=manifest.get(name+'_count'):
            raise ValueError(f'Replay {name} log is incomplete')
    index=_read_json(root/'index.json')
    if index.get('schema_version')!=1 or not isinstance(index.get('snapshots'),list):
        raise ValueError('Invalid snapshot index')
    return root,manifest,definitions,inputs,external,rounds,events,index['snapshots']


def verify_run(directory, *, from_tick=None):
    """Validate one recorded run without invoking any policy or duplicating sealed inputs.

    Starting ticks must have a recorded complete snapshot. The saved log cursors
    select exactly the operations/facts after that boundary, including k > 1.
    """
    root,manifest,defs,inputs,external,rounds,events,index=_load(directory)
    start=manifest['episode_start_tick'] if from_tick is None else from_tick
    if type(start) is not int:
        raise ValueError('Replay start tick must be an integer')
    candidates=[x for x in index if isinstance(x,dict) and x.get('tick')==start]
    if not candidates:
        raise ValueError(f'No complete indexed snapshot at tick {start}')
    entry=candidates[0]
    path=entry.get('path')
    if not isinstance(path,str) or Path(path).is_absolute() or '..' in Path(path).parts:
        raise ValueError('Invalid indexed snapshot path')
    snapshot=_read_json(root/path)
    world=restore_snapshot(snapshot,defs)
    expected=deepcopy(snapshot['state'])
    actual=world.state
    if expected['tick']!=start or state_hash(expected)!=entry.get('state_sha256'):
        raise ValueError('Indexed snapshot state/hash mismatch')
    input_cursor=entry['input_cursor'];external_cursor=entry['external_cursor']
    round_cursor=entry['round_cursor'];event_cursor=entry['event_cursor']
    for cursor,total in ((input_cursor,len(inputs)),(external_cursor,len(external)),
                         (round_cursor,len(rounds)),(event_cursor,len(events))):
        if type(cursor) is not int or not 0<=cursor<=total:
            raise ValueError('Invalid replay log cursor')
    last_fact_id=''
    for i,event in enumerate(events[:event_cursor]):
        fact_id=event.get('id') if isinstance(event,dict) else None
        if (not isinstance(fact_id,str) or fact_id<=last_fact_id or
                type(event.get('happened_at')) is not int or event['happened_at']>start):
            raise ValueError('Invalid fact sequence before snapshot')
        recorded=expected['execution']['seen_messages'].get(fact_id)
        if recorded is None:
            raise ReplayMismatch(start,f'$.events[{i}].id','fact present in snapshot',fact_id)
        _compare(json.loads(recorded),event,start,f'$.events[{i}]')
        last_fact_id=fact_id
    frame_index=entry['frame_index'];frame_offset=entry['frame_offset']
    if type(frame_index) is not int or type(frame_offset) is not int or frame_index<0 or frame_offset<1:
        raise ValueError('Invalid frame index')
    frame_path=root/'frames.jsonl'
    try:
        with frame_path.open('rb') as source:
            # Verify the index really points just after its advertised frame.
            indexed=None
            for i in range(frame_index+1):
                line=source.readline()
                if not line: raise ValueError('Frame log ends before indexed snapshot')
                indexed=json.loads(line)
            if source.tell()!=frame_offset:
                raise ValueError('Snapshot frame offset mismatch')
            _compare({'tick':start,'state_sha256':state_hash(expected),'input_cursor':input_cursor,
                      'external_cursor':external_cursor,'round_cursor':round_cursor,'event_cursor':event_cursor},
                     {k:indexed.get(k) for k in ('tick','state_sha256','input_cursor','external_cursor','round_cursor','event_cursor')},
                     start,'$.index')
            checked=0
            for line in source:
                if not line.strip(): raise ValueError('Empty frame line')
                frame=json.loads(line);tick=frame.get('tick')
                if type(tick) is not int or tick!=actual['tick']+1:
                    raise ValueError('Frame ticks must be consecutive')
                next_external=frame.get('external_cursor')
                if type(next_external) is not int or not external_cursor<=next_external<=len(external):
                    raise ValueError('Invalid external input cursor in frame')
                while external_cursor<next_external:
                    item=external[external_cursor]
                    if item.get('boundary_tick')!=tick-1:
                        raise ValueError('External input is at the wrong boundary')
                    receipt=world.receive_actions(decode_packet(item['packet']))
                    _compare(item['receipt'],receipt,tick-1,'$.external.receipt')
                    external_cursor+=1
                next_round=frame.get('round_cursor')
                if type(next_round) is not int or next_round not in (round_cursor,round_cursor+1):
                    raise ValueError('Invalid round cursor in frame')
                if next_round>round_cursor:
                    record=rounds[round_cursor]
                    if record.get('observed_tick')!=tick-1:
                        raise ValueError('Recorded round is at the wrong boundary')
                    world.open_round(record['round_id'])
                    batch=[decode_packet(item) for item in record['batch']]
                    receipts=world.receive_actions_batch(batch)
                    _compare(record['receipts'],receipts,tick-1,'$.receipts')
                    batch_inputs=inputs[input_cursor:input_cursor+len(batch)]
                    if len(batch_inputs)!=len(batch): raise ValueError('Missing input records')
                    _compare(record.get('inputs_sha256'),sha256(canonical(batch_inputs)).hexdigest(),
                             tick-1,'$.inputs.sha256')
                    for row,packet,encoded,receipt in zip(batch_inputs,batch,record['batch'],receipts):
                        if row.get('observed_tick')!=tick-1 or row.get('round_id')!=record['round_id']:
                            raise ValueError('Input record belongs to a different round')
                        if 'json' in encoded and (not isinstance(packet,dict) or row.get('player_id')!=packet.get('player_id')):
                            raise ValueError('Input player does not match batch packet')
                        _compare(row['initial_receipt'],receipt,tick-1,'$.inputs.initial_receipt')
                    replacements={item['player_id']:item for item in record['replacements']}
                    if len(replacements)!=len(record['replacements']):
                        raise ValueError('Duplicate replacement player')
                    for row,receipt in zip(batch_inputs,receipts):
                        replacement=replacements.pop(row['player_id'],None)
                        if replacement is not None:
                            receipt=world.receive_actions(decode_packet(replacement['packet']))
                            _compare(replacement['receipt'],receipt,tick-1,'$.replacement.receipt')
                        _compare(row['receipt'],receipt,tick-1,'$.inputs.receipt')
                    if replacements: raise ValueError('Replacement has no original input')
                    input_cursor+=len(batch);round_cursor+=1
                    world.seal_round()
                if frame.get('input_cursor')!=input_cursor or frame.get('round_cursor')!=round_cursor:
                    raise ValueError('Frame input cursor mismatch')
                try:
                    actual=world.step()
                except WorldFault as error:
                    raise ReplayMismatch(tick,'$.engine','complete tick',str(error)) from error
                next_event=frame.get('event_cursor')
                if type(next_event) is not int or not event_cursor<=next_event<=len(events):
                    raise ValueError('Invalid frame event cursor')
                _compare(events[event_cursor:next_event],list(world.last_facts),tick,'$.events')
                event_cursor=next_event
                apply_changes(expected,frame['changes'])
                if state_hash(expected)!=frame.get('state_sha256'):
                    diff=first_difference(expected,actual,'$.state')
                    if diff: raise ReplayMismatch(tick,*diff)
                    raise ReplayMismatch(tick,'$.frame.state_sha256',frame.get('state_sha256'),state_hash(expected))
                if state_hash(actual)!=frame['state_sha256']:
                    diff=first_difference(expected,actual,'$.state')
                    if diff: raise ReplayMismatch(tick,*diff)
                    raise ReplayMismatch(tick,'$.frame.state_sha256',frame['state_sha256'],state_hash(actual))
                checked+=1
    except (OSError,UnicodeError,json.JSONDecodeError,KeyError,IndexError,TypeError) as error:
        raise ValueError(f'Invalid or incomplete replay record: {error}') from error
    final_tick=actual['tick']
    summary=manifest['summary']
    if final_tick!=summary['tick'] or frame_index+checked+1!=manifest['frame_count']:
        raise ValueError('Frame log does not reach the recorded final boundary')
    if manifest['summary']['failure'] is None:
        if (input_cursor,external_cursor,round_cursor,event_cursor)!=(len(inputs),len(external),len(rounds),len(events)):
            raise ValueError('Replay contains unconsumed log records')
        final=_read_json(root/'final-snapshot.json')
        restored_final=restore_snapshot(final,defs)
        _compare(restored_final.state,actual,final_tick,'$.final_state')
        result=actual['result']
        terminated=result is not None
        truncated=final_tick-manifest['episode_start_tick']>=manifest['episode_limit_ticks']
        rewards={pid:(0 if result is None or result['kind']=='draw' else
                 1 if player['team_id']==result['winner_team_id'] else -1)
                 for pid,player in actual['players'].items()}
        _compare({'result':result,'terminated':terminated,'truncated':truncated,'rewards':rewards,
                  'match_id':manifest['match_id'],'start_tick':manifest['episode_start_tick']},
                 {k:summary[k] for k in ('result','terminated','truncated','rewards','match_id','start_tick')},
                 final_tick,'$.summary')
    return {'valid':True,'match_id':manifest['match_id'],'from_tick':start,'to_tick':final_tick,
            'ticks_compared':checked,'inputs_consumed':input_cursor-entry['input_cursor'],
            'external_inputs_consumed':external_cursor-entry['external_cursor'],
            'facts_compared':event_cursor-entry['event_cursor'],'terminated':summary['terminated'],
            'truncated':summary['truncated'],'failure':summary['failure']}
