"""Canonical boundary records, deterministic deltas and replay input encoding."""
from copy import deepcopy
from hashlib import sha256
import json
import math


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def state_hash(state):
    return sha256(canonical(state)).hexdigest()


def changes(before, after, path=()):
    """Object deltas; lists are replaced atomically, preserving their exact order."""
    result=[]
    if isinstance(before,dict) and isinstance(after,dict):
        for key in sorted(before.keys() - after.keys()):
            result.append({'op':'delete','path':[*path,key]})
        for key in sorted(after.keys() - before.keys()):
            result.append({'op':'set','path':[*path,key],'value':after[key]})
        for key in sorted(before.keys() & after.keys()):
            result.extend(changes(before[key],after[key],(*path,key)))
    elif isinstance(before,list) and isinstance(after,list):
        # Python list equality treats 1 == 1.0 and -0.0 == 0.0 as true.
        # Compare their JSON encodings so nested numeric representations survive.
        if canonical(before)!=canonical(after):
            result.append({'op':'set','path':list(path),'value':after})
    elif type(before) is not type(after) or before != after or (isinstance(after,float) and
            before == after == 0 and math.copysign(1,before) != math.copysign(1,after)):
        result.append({'op':'set','path':list(path),'value':after})
    return result


def apply_changes(state, ops):
    for op in ops:
        if not isinstance(op,dict) or op.get('op') not in ('set','delete') or not isinstance(op.get('path'),list):
            raise ValueError('Invalid state delta')
        if set(op) != ({'op','path','value'} if op['op']=='set' else {'op','path'}):
            raise ValueError('Invalid state delta fields')
        path=op['path']
        if not path or any(not isinstance(k,str) for k in path):
            raise ValueError('Invalid state delta path')
        target=state
        for key in path[:-1]:
            if not isinstance(target,dict) or key not in target:
                raise ValueError('State delta parent does not exist')
            target=target[key]
        if not isinstance(target,dict):
            raise ValueError('State delta parent is not an object')
        if op['op']=='delete':
            if path[-1] not in target:
                raise ValueError('State delta deletes a missing key')
            del target[path[-1]]
        else:
            target[path[-1]]=deepcopy(op['value'])
    return state


def first_difference(expected, actual, path='$'):
    """Report the first deterministic JSON path, distinguishing numeric encodings."""
    if type(expected) is not type(actual):
        return path, expected, actual
    if isinstance(expected,dict):
        for key in sorted(expected.keys() | actual.keys()):
            child=path+'['+json.dumps(key,ensure_ascii=False)+']'
            if key not in expected: return child, '<missing>', actual[key]
            if key not in actual: return child, expected[key], '<missing>'
            diff=first_difference(expected[key],actual[key],child)
            if diff: return diff
    elif isinstance(expected,list):
        for i in range(min(len(expected),len(actual))):
            diff=first_difference(expected[i],actual[i],f'{path}[{i}]')
            if diff: return diff
        if len(expected)!=len(actual): return path+'.length',len(expected),len(actual)
    elif canonical(expected)!=canonical(actual):
        return path,expected,actual
    return None


def encode_packet(packet):
    """Retain JSON serialization, including invalid NaN/Infinity, without lossy sentinels.

    A Python object which JSON cannot serialize makes the entire envelope invalid;
    its replay representative must fail envelope serialization in the same way.
    """
    try:
        return {'json':json.dumps(packet,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=True)}
    except (TypeError,ValueError,UnicodeError,OverflowError,RecursionError):
        return {'invalid_envelope':True}


def decode_packet(record):
    if isinstance(record,dict) and set(record)=={'json'} and isinstance(record['json'],str):
        return json.loads(record['json'])
    if record=={'invalid_envelope':True}:
        return {'unserializable':object()}
    raise ValueError('Invalid recorded input encoding')
