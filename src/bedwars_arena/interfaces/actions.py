"""L1 request validation and recoverable request ledger (protocol v1)."""
from copy import deepcopy
import json
import math

from bedwars_arena.core.scheduler import _json
from bedwars_arena.core.time import MAX_SAFE_INTEGER, identifier, integer

FIELDS = {'protocol_version','match_id','player_id','decision_round_id','observed_tick','life_index','requests'}
KINDS = {'turn','select_item','move','attack','break_block','break_bed','place_block','cancel','buy','drop_resource'}
GROUPS = {'turn':'turn','select_item':'select_item','move':'movement','attack':'interaction',
          'break_block':'interaction','break_bed':'interaction','place_block':'interaction',
          'buy':'buy','drop_resource':'drop_resource'}
ORDER = {'turn':0,'select_item':1,'movement':2,'interaction':3,'buy':4,'drop_resource':5}
PHASE = {'turn':20,'select_item':20,'movement':20,'interaction':20,'buy':40,'drop_resource':45}


def _is_number(v):
    return type(v) in (int,float) and math.isfinite(v)


def request_error(request):
    if not isinstance(request,dict) or set(request) != {'request_id','kind','payload'}:
        return 'MALFORMED'
    try:
        identifier(request['request_id'],'request_id')
    except ValueError:
        return 'INVALID_ID'
    kind=request['kind']
    if not isinstance(kind,str) or kind not in KINDS:
        return 'UNKNOWN_ACTION'
    payload=request['payload']
    if not isinstance(payload,dict):
        return 'MALFORMED'
    try:
        if kind in ('turn','move'):
            if set(payload) != {'x','z'} or not all(_is_number(payload[k]) for k in ('x','z')):
                return 'MALFORMED'
            if kind == 'turn' and payload['x'] == payload['z'] == 0:
                return 'MALFORMED'
        elif kind == 'select_item':
            if set(payload) != {'item'} or payload['item'] not in ('iron','wool','wooden_sword','iron_sword','shears'):
                return 'MALFORMED'
        elif kind == 'attack':
            if set(payload) != {'player_id','life_index'}:
                return 'MALFORMED'
            identifier(payload['player_id'],'player_id');integer(payload['life_index'],'life_index',1)
        elif kind in ('break_block','place_block'):
            expected={'x','z','layer'} | ({'instance_id'} if kind=='break_block' else set())
            if set(payload) != expected or payload['layer'] not in ('bridge','wall'):
                return 'MALFORMED'
            for key in ('x','z'):
                if type(payload[key]) is not int or not -MAX_SAFE_INTEGER <= payload[key] <= MAX_SAFE_INTEGER:
                    return 'MALFORMED'
            if kind=='break_block':
                identifier(payload['instance_id'],'instance_id')
        elif kind == 'break_bed':
            if set(payload) != {'team_id'}:
                return 'MALFORMED'
            identifier(payload['team_id'],'team_id')
        elif kind == 'cancel':
            if set(payload) != {'channel'} or payload['channel'] not in ('movement','interaction'):
                return 'MALFORMED'
        elif kind == 'buy':
            if set(payload) != {'product'} or payload['product'] not in ('wool','iron_sword','armor_1'):
                return 'MALFORMED'
        elif kind == 'drop_resource':
            if set(payload) != {'resource','quantity'} or payload['resource'] != 'iron':
                return 'MALFORMED'
            integer(payload['quantity'],'quantity',1)
        _json(request)
    except (ValueError,TypeError,OverflowError):
        return 'MALFORMED'
    return None


def group(request):
    return request['payload']['channel'] if request['kind']=='cancel' else GROUPS[request['kind']]


def fingerprint(packet,request):
    value={'match_id':packet['match_id'],'player_id':packet['player_id'],
           'decision_round_id':packet['decision_round_id'],'observed_tick':packet['observed_tick'],
           'life_index':packet['life_index'],'request':request}
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=True)


def result(request_id,round_id,status,reason,*,tick=None,action_id=None):
    return {'request_id':request_id,'decision_round_id':round_id,'status':status,'reason':reason,
            'processed_tick':tick,'action_id':action_id}


def packet_error(reason,round_id=None):
    return {'reason':reason,'decision_round_id':round_id}


def validate_envelope(packet, *, match_id, players, max_bytes):
    if not isinstance(packet,dict) or set(packet) != FIELDS:
        return 'MALFORMED'
    try:
        encoded=json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=True).encode('utf-8')
    except (TypeError,ValueError,UnicodeError,OverflowError):
        return 'MALFORMED'
    if len(encoded) > max_bytes:
        return 'MALFORMED'
    if type(packet['protocol_version']) is not int or packet['protocol_version'] != 1:
        return 'UNSUPPORTED_PROTOCOL'
    try:
        identifier(packet['match_id'],'match_id')
        identifier(packet['player_id'],'player_id')
        identifier(packet['decision_round_id'],'decision_round_id')
        integer(packet['observed_tick'],'observed_tick')
        integer(packet['life_index'],'life_index',1)
    except ValueError:
        return 'MALFORMED'
    if packet['match_id'] != match_id or packet['player_id'] not in players:
        return 'INVALID_BINDING'
    if not isinstance(packet['requests'],list):
        return 'MALFORMED'
    return None


def validate_execution_requests(execution, state, profile):
    """Check the recoverable external ledger and pending input, not policy visibility."""
    players=state['players']
    records=execution['request_records']
    pending=execution['pending_requests']
    outcomes=execution['action_outcomes']
    errors=execution['packet_errors']
    history=execution['round_history']
    if not all(isinstance(x,dict) for x in (records,outcomes,errors,history)):
        raise ValueError('Invalid request ledgers')
    if any(k not in players for k in records.keys() | outcomes.keys() | errors.keys()):
        raise ValueError('Unknown player in request ledgers')
    for round_id,tick in history.items():
        identifier(round_id,'round id');integer(tick,'round tick')
    current=execution['round']
    if current is not None:
        if not isinstance(current,dict) or set(current) != {'id','observed_tick','sealed','submitted'}:
            raise ValueError('Invalid decision round')
        identifier(current['id'],'round id');integer(current['observed_tick'],'observed_tick')
        if type(current['sealed']) is not bool or not isinstance(current['submitted'],list):
            raise ValueError('Invalid round state')
        if history.get(current['id']) != current['observed_tick'] or current['observed_tick'] > state['tick']:
            raise ValueError('Round history mismatch')
        if len(set(current['submitted'])) != len(current['submitted']) or any(p not in players for p in current['submitted']):
            raise ValueError('Invalid round participants')
    total=0
    for pid,by_id in records.items():
        if not isinstance(by_id,dict):
            raise ValueError('Invalid request records')
        for rid,entry in by_id.items():
            total+=1;identifier(rid,'request id')
            if not isinstance(entry,dict) or set(entry) != {'fingerprint','result'} or not isinstance(entry['fingerprint'],str):
                raise ValueError('Invalid request record')
            value=entry['result']
            if not isinstance(value,dict) or set(value) != {'request_id','decision_round_id','status','reason','processed_tick','action_id'}:
                raise ValueError('Invalid request result')
            if value['request_id'] != rid or value['status'] not in ('accepted','rejected','applied','failed'):
                raise ValueError('Request identity/status mismatch')
            identifier(value['decision_round_id'],'round id');identifier(value['reason'],'reason')
            if value['processed_tick'] is not None:
                integer(value['processed_tick'],'processed_tick')
            if value['action_id'] is not None:
                identifier(value['action_id'],'action_id')
            if value['status'] in ('accepted','rejected') and value['processed_tick'] is not None:
                raise ValueError('Unprocessed request has a tick')
            if value['status'] in ('applied','failed') and value['processed_tick'] is None:
                raise ValueError('Processed request is missing its tick')
            try:
                raw=json.loads(entry['fingerprint'])
                canonical=json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=True)
                if (canonical != entry['fingerprint'] or raw['player_id'] != pid or raw['match_id'] != state['match_id']
                        or raw['request']['request_id'] != rid or raw['decision_round_id'] != value['decision_round_id']):
                    raise ValueError('Invalid request fingerprint')
                integer(raw['observed_tick'],'observed_tick');integer(raw['life_index'],'life_index',1)
            except (ValueError,TypeError,KeyError) as error:
                raise ValueError('Invalid request fingerprint') from error
    if len(execution['seen_messages']) + total > profile['budget']['seen_messages_and_requests']:
        raise ValueError('Message/request ledger budget exceeded')
    pending_keys=set()
    for item in pending:
        if not isinstance(item,dict) or set(item) != {'player_id','request_id','kind','payload','group','phase','tick','life_index','decision_round_id'}:
            raise ValueError('Invalid pending request')
        pid,rid=item['player_id'],item['request_id']
        key=(pid,rid)
        if key in pending_keys or pid not in records or rid not in records[pid]:
            raise ValueError('Pending request identity invalid')
        pending_keys.add(key)
        if records[pid][rid]['result']['status'] != 'accepted' or request_error({'request_id':rid,'kind':item['kind'],'payload':item['payload']}) is not None:
            raise ValueError('Pending request not accepted/valid')
        raw=json.loads(records[pid][rid]['fingerprint'])
        if (raw['request'] != {'request_id':rid,'kind':item['kind'],'payload':item['payload']}
                or raw['life_index'] != item['life_index'] or raw['observed_tick']+1 != item['tick']
                or raw['decision_round_id'] != item['decision_round_id']):
            raise ValueError('Pending request differs from accepted content')
        if item['group'] != group({'kind':item['kind'],'payload':item['payload']}) or item['phase'] != PHASE[item['group']]:
            raise ValueError('Pending request phase/group mismatch')
        integer(item['tick'],'request tick',1);integer(item['life_index'],'life_index',1)
        cursor=execution['cursor']
        if (item['tick'],item['phase']) < (cursor['tick'],cursor['phase']):
            raise ValueError('Pending request is behind phase cursor')
    for pid,by_id in records.items():
        for rid,entry in by_id.items():
            if entry['result']['status']=='accepted' and (pid,rid) not in pending_keys:
                raise ValueError('Accepted request is missing from pending queue')
    for mapping in (outcomes,errors):
        if any(not isinstance(v,list) for v in mapping.values()):
            raise ValueError('Invalid feedback arrays')
