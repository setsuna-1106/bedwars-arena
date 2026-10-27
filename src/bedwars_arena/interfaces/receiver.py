"""Round intake at an already published tick boundary."""
from collections import Counter, defaultdict
from copy import deepcopy

from .actions import ORDER, PHASE, fingerprint, group, packet_error, request_error, result, validate_envelope
from bedwars_arena.core.time import identifier


def receive(state,definitions,packet):
    profile=definitions.profile.data
    issue=validate_envelope(packet,match_id=state['match_id'],players=state['players'],
                            max_bytes=profile['budget']['input_bytes_per_player_per_round'])
    if issue:
        return state, {'request_results':[], 'packet_errors':[packet_error(issue)]}
    candidate=deepcopy(state)
    execution=candidate['execution']
    pid=packet['player_id'];round_id=packet['decision_round_id']
    ledger=execution['request_records'].setdefault(pid,{})
    reply=[];errors=[];new=defaultdict(list)
    for request in packet['requests']:
        if not isinstance(request,dict):
            errors.append(packet_error('MALFORMED',round_id));continue
        rid=request.get('request_id')
        try:
            identifier(rid,'request_id')
        except ValueError:
            errors.append(packet_error('MALFORMED',round_id));continue
        try:
            sig=fingerprint(packet,request)
        except (ValueError,TypeError,UnicodeError,OverflowError):
            errors.append(packet_error('MALFORMED',round_id));continue
        if rid in ledger:
            if ledger[rid]['fingerprint']==sig:
                reply.append(deepcopy(ledger[rid]['result']))
            else:
                reply.append(result(rid,round_id,'rejected','DUPLICATE_ID_CONFLICT'))
        else:
            new[rid].append((sig,request))
    current=execution['round']
    closed=(current is None or current['id']!=round_id or current['sealed'] or
            pid in current['submitted'])
    stale=(current is not None and (packet['observed_tick']!=current['observed_tick'] or
                                   packet['observed_tick']!=state['tick']))
    player=state['players'][pid]
    binding=(player['life']['kind']=='alive' and player['life_index']==packet['life_index'] and
             not any(d['player_id']==pid and d['life_index']==packet['life_index'] for d in execution['pending_deaths']))
    if (new or not packet['requests']) and (closed or stale or not binding):
        reason='STALE_OBSERVATION' if stale and not closed else 'ROUND_CLOSED' if closed else 'INVALID_BINDING'
        errors.append(packet_error(reason,round_id))
        if reason != 'INVALID_BINDING':
            for rid,items in sorted(new.items()):
                sigs=sorted({sig for sig,_ in items})
                item_reason='DUPLICATE_ID_CONFLICT' if len(sigs)>1 else reason
                entry=result(rid,round_id,'rejected',item_reason)
                ledger[rid]={'fingerprint':sigs[0],'result':entry}
                reply.append(deepcopy(entry))
            if new:
                return candidate, {'request_results':sorted(reply,key=lambda x:x['request_id']), 'packet_errors':errors}
        # An invalid common binding rejects the packet as a whole.
        return state, {'request_results':reply,'packet_errors':errors}
    staged=[]
    for rid,items in sorted(new.items()):
        signatures=sorted({sig for sig,_ in items})
        if len(signatures)>1:
            sig=signatures[0]
            entry=result(rid,round_id,'rejected','DUPLICATE_ID_CONFLICT')
            ledger[rid]={'fingerprint':sig,'result':entry}
            reply.append(deepcopy(entry))
            continue
        sig,request=items[0]
        reason=request_error(request)
        if reason:
            entry=result(rid,round_id,'rejected',reason)
            ledger[rid]={'fingerprint':sig,'result':entry}
            reply.append(deepcopy(entry))
        else:
            staged.append((rid,sig,request,group(request)))
    counts=Counter(item[3] for item in staged)
    for rid,sig,request,request_group in staged:
        if counts[request_group]>1:
            reason='CHANNEL_CONFLICT' if request_group in ('movement','interaction') else 'GROUP_LIMIT'
            entry=result(rid,round_id,'rejected',reason)
        else:
            entry=result(rid,round_id,'accepted','OK')
            execution['pending_requests'].append({'player_id':pid,'request_id':rid,
                'kind':request['kind'],'payload':deepcopy(request['payload']),'group':request_group,
                'phase':PHASE[request_group],'tick':packet['observed_tick']+1,
                'life_index':packet['life_index'],'decision_round_id':round_id})
        ledger[rid]={'fingerprint':sig,'result':entry}
        reply.append(deepcopy(entry))
    if not closed and not stale and binding and pid not in current['submitted']:
        current['submitted'].append(pid)
        roster=[p['player_id'] for p in definitions.scenario.data['players']]
        current['submitted'].sort(key=roster.index)
    if errors:
        execution['packet_errors'].setdefault(pid,[]).extend(deepcopy(errors))
    roster_order={p['player_id']:i for i,p in enumerate(definitions.scenario.data['players'])}
    execution['pending_requests'].sort(key=lambda item:(item['tick'],item['phase'],ORDER[item['group']],
                                                       roster_order[item['player_id']],item['request_id']))
    if candidate == state:
        candidate = state
    return candidate, {'request_results':sorted(reply,key=lambda x:x['request_id']), 'packet_errors':errors}
