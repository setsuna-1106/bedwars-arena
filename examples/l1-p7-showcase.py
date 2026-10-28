"""Create a short controlled replay covering recovery, collision and final death.

Usage: python examples/l1-p7-showcase.py artifacts/p7-showcase
The preset is deliberately asymmetric and is not a policy-strength comparison.
"""
import argparse
import json
from pathlib import Path

from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.replay.verify import verify_run
from bedwars_arena.replay.viewer import export_viewer
from bedwars_arena.runner.match import MatchRunner


class DemonstrationPolicy:
    name='p7-controlled-demonstration'
    version='1.0'

    def __init__(self,player_id):self.player_id=player_id

    def act(self,obs):
        tick=obs['observed_tick'];pid=self.player_id
        def req(kind,payload):
            return {'request_id':f'{pid}-{tick}-{kind}','kind':kind,'payload':payload}
        if pid=='red_1':
            if tick==0:
                return [req('place_block',{'x':-16,'z':0,'layer':'bridge'})]
            if tick==5:
                return [req('select_item',{'item':'shears'})]
            if tick==6:
                block=next(item for item in obs['terrain']['blocks'] if item['x']==-16 and item['z']==0 and item['layer']=='bridge')
                return [req('break_block',{'x':-16,'z':0,'layer':'bridge','instance_id':block['instance_id']})]
        if pid=='red_2':
            if tick==0:
                return [req('move',{'x':1,'z':-0.5}),req('attack',{'player_id':'blue_1','life_index':1})]
            if tick==26:
                return [req('cancel',{'channel':'movement'})]
        return []


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',help='new output directory')
    args=parser.parse_args()
    definitions=load_l1_definitions()
    preset={'source':'p7-controlled-showcase','beds':{'blue':False},'players':{
        'red_1':{'x':-17.2,'z':0.5,'held_item':'wool',
                 'inventory':{'wooden_sword':1,'shears':1,'wool':1},'protection_ticks':0},
        'red_2':{'x':-25,'z':2,'protection_ticks':0},
        'blue_1':{'x':-23,'z':2,'health':4,'protection_ticks':0},
        'blue_2':{'protection_ticks':0}}}
    world=WorldEngine.create(definitions,seed=101,match_id='p7-showcase-101',preset=preset)
    policies={p['player_id']:DemonstrationPolicy(p['player_id'])
              for p in definitions.scenario.data['players']}
    runner=MatchRunner(world,policies,episode_limit_ticks=45)
    runner.run();root=runner.write_artifacts(Path(args.output))
    verified=verify_run(root)
    html=export_viewer(root,root/'replay.html')
    events=[{'tick':f['happened_at'],'kind':f['kind'],'payload':f['payload']} for f in runner.events
            if f['kind'] in ('movement_collision','block_broken','player_died')]
    print(json.dumps({'summary':runner.summary(),'verification':verified,'key_events':events,
                      'replay':str(html.resolve())},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
