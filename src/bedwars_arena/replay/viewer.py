"""Export a self-contained, offline Canvas viewer for a completed P7 record."""
from importlib.resources import files
import json
from pathlib import Path

from .verify import _load, _lines


def export_viewer(directory, output):
    root,manifest,definitions,inputs,external,rounds,events,index=_load(directory)
    frames=_lines(root/'frames.jsonl')
    if len(frames)!=manifest['frame_count']:
        raise ValueError('Replay frame log is incomplete')
    initial=json.loads((root/'initial-snapshot.json').read_text(encoding='utf-8'))
    payload={'manifest':manifest,'definitions':{k:getattr(definitions,k).data for k in ('profile','map','scenario')},
             'initial_state':initial['state'],'frames':frames,'events':events}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    encoded=encoded.replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    encoded=encoded.replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    template=files('bedwars_arena.replay').joinpath('viewer.html').read_text(encoding='utf-8')
    if template.count('/*__REPLAY_DATA__*/')!=1:
        raise ValueError('Invalid viewer template')
    target=Path(output)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as out:
        out.write(template.replace('/*__REPLAY_DATA__*/',encoded))
    return target
