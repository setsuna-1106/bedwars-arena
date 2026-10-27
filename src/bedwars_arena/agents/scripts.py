"""Two deterministic L1 policies operating exclusively on public observations."""
import math

from bedwars_arena.core.geometry import AABB, Vec2, distance, distance_to_aabb
from bedwars_arena.core.terrain import Terrain
from bedwars_arena.core.physics import move_player


class EconomicAttacker:
    name='economic-attacker'
    version='1.0'
    intercept_range=2.8

    def __init__(self):
        self._move=None
        self._life=None
        self._sequence=0

    def on_start(self,context):
        self.player_id=context['player_id']

    def _request(self,obs,kind,payload):
        self._sequence+=1
        return {'request_id':f"{self.name}-{obs['observed_tick']}-{self._sequence}",
                'kind':kind,'payload':payload}

    def _move_to(self,obs,me,target,requests,*,axis='z'):
        pos=me['position'];dx=target[0]-pos['x'];dz=target[1]-pos['z'];tol=0.11
        if axis=='z' and abs(dz)>tol: direction=(0,1 if dz>0 else -1)
        elif abs(dx)>tol: direction=(1 if dx>0 else -1,0)
        elif abs(dz)>tol: direction=(0,1 if dz>0 else -1)
        else: direction=(0,0)
        if direction==(0,0):
            if me['movement'] is not None:
                requests.append(self._request(obs,'cancel',{'channel':'movement'}))
            self._move=(0,0)
        elif self._move!=direction or me['movement'] is None:
            requests.append(self._request(obs,'move',{'x':direction[0],'z':direction[1]}))
            self._move=direction
        return direction==(0,0)

    def _face(self,obs,me,target,requests):
        dx=target[0]-me['position']['x'];dz=target[1]-me['position']['z']
        length=math.hypot(dx,dz)
        if length and (abs(me['facing']['x']-dx/length)>1e-7 or abs(me['facing']['z']-dz/length)>1e-7):
            requests.append(self._request(obs,'turn',{'x':dx,'z':dz}))

    def _select(self,obs,me,item,requests):
        if me['held_item']!=item and item in me['inventory']:
            requests.append(self._request(obs,'select_item',{'item':item}))

    def _terrain(self,obs):
        ground=set();walls=set()
        for item in obs['terrain']['blocks']:
            (ground if item['layer']=='bridge' else walls).add((item['x'],item['z']))
        team_status={t['team_id']:t['bed']['status'] for t in obs['teams']}
        beds=tuple((b['team_id'],b['x'],b['z']) for b in obs['terrain']['beds']
                   if team_status[b['team_id']]=='present')
        bounds=obs['terrain']['bounds']
        return Terrain(frozenset(ground),frozenset(walls),beds,
                       (bounds['min_x'],bounds['max_x'],bounds['min_z'],bounds['max_z']))

    def _combat(self,obs,me,enemies,terrain,requests):
        pos=Vec2(me['position']['x'],me['position']['z'])
        close=[]
        for enemy in enemies:
            center=Vec2(enemy['position']['x'],enemy['position']['z'])
            physics=obs['rules']['physics']
            box=AABB.centered(center,physics['player_width'],physics['player_depth'])
            dist=distance_to_aabb(pos,box)
            if dist<=obs['rules']['combat']['range_blocks'] and terrain.line_of_sight(pos,center):
                close.append((dist,enemy['player_id'],enemy))
        if not close:
            return False
        _,_,enemy=min(close,key=lambda value:(value[0],value[1]))
        target=(enemy['position']['x'],enemy['position']['z'])
        self._move_to(obs,me,(pos.x,pos.z),requests)
        self._face(obs,me,target,requests)
        sword='iron_sword' if 'iron_sword' in me['inventory'] else 'wooden_sword'
        self._select(obs,me,sword,requests)
        desired={'player_id':enemy['player_id'],'life_index':enemy['life_index']}
        active=me['interaction']
        if active is None or active['kind']!='attack' or active['target']!=desired:
            requests.append(self._request(obs,'attack',desired))
        return True

    def act(self,obs):
        self._sequence=0
        me=next(p for p in obs['players'] if p['player_id']==obs['self_player_id'])
        if me['life']!='alive':
            return []
        if self._life!=me['life_index']:
            self._life=me['life_index'];self._move=None
        requests=[]
        terrain=self._terrain(obs)
        enemies=[p for p in obs['players'] if p['team_id']!=me['team_id'] and p['life']=='alive']
        if self._combat(obs,me,enemies,terrain,requests):
            return requests
        map_data=obs['map'];own=next(t for t in map_data['teams'] if t['team_id']==me['team_id'])
        enemy=next(t for t in map_data['teams'] if t['team_id']!=me['team_id'])
        enemy_state=next(t for t in obs['teams'] if t['team_id']==enemy['team_id'])
        own_island=next(i['bounds'] for i in map_data['terrain']['islands'] if
                        i['bounds']['min_x']<=own['spawn']['x']<i['bounds']['max_x'] and
                        i['bounds']['min_z']<=own['spawn']['z']<i['bounds']['max_z'])
        enemy_island=next(i['bounds'] for i in map_data['terrain']['islands'] if
                          i['bounds']['min_x']<=enemy['spawn']['x']<i['bounds']['max_x'] and
                          i['bounds']['min_z']<=enemy['spawn']['z']<i['bounds']['max_z'])
        sign=1 if enemy['spawn']['x']>own['spawn']['x'] else -1
        lane_z=-3.5;row=-4
        start=own_island['max_x']-1 if sign>0 else own_island['min_x']
        goal=enemy_island['min_x'] if sign>0 else enemy_island['max_x']-1
        frontier=start
        while frontier!=goal and (frontier+sign,row) in terrain.ground:
            frontier+=sign
        connected=frontier==goal
        pos=me['position'];inventory=me['inventory'];wool=inventory.get('wool',0);iron=inventory.get('iron',0)
        if not connected:
            missing=sum((x,row) not in terrain.ground for x in range(min(start,goal),max(start,goal)+1))
            if wool < missing:
                generator=next(g for g in map_data['generators'] if g['team_id']==me['team_id'])
                shop=own['shop'];quote=obs['rules']['shop']['products']['wool']
                needed=((missing-wool+quote['quantity']-1)//quote['quantity'])*quote['cost']
                if not (own_island['min_x']+0.5 <= pos['x'] <= own_island['max_x']-0.5):
                    self._move_to(obs,me,(own['spawn']['x'],lane_z),requests,axis='x');return requests
                if iron>=needed:
                    if self._move_to(obs,me,(shop['x'],shop['z']),requests):
                        requests.append(self._request(obs,'buy',{'product':'wool'}))
                else:
                    self._move_to(obs,me,(generator['position']['x'],generator['position']['z']),requests)
                return requests
            target_x=frontier+sign;target=(target_x+0.5,row+0.5)
            # Walk along the established bridge, never command movement past its end.
            if abs(pos['z']-lane_z)>0.11:
                self._move_to(obs,me,(pos['x'],lane_z),requests);return requests
            if distance(Vec2(pos['x'],pos['z']),Vec2(*target))>2.7:
                self._move_to(obs,me,(frontier+0.5,lane_z),requests,axis='x');return requests
            self._move_to(obs,me,(pos['x'],pos['z']),requests)
            if wool==0:
                return requests
            self._face(obs,me,target,requests);self._select(obs,me,'wool',requests)
            payload={'x':target_x,'z':row,'layer':'bridge'}
            active=me['interaction']
            if active is None or active['kind']!='place_block' or active['target']!=payload:
                requests.append(self._request(obs,'place_block',payload))
            return requests
        # After the bridge connects, go to the enemy bed by a safe path on its island.
        bed=enemy['bed'];bed_target=(bed['x']+0.5,bed['z']+0.5)
        if enemy_state['bed']['status']=='present':
            staging=(bed_target[0]-2*sign,bed_target[1])
            # Enter the enemy island on the bridge before leaving its row.
            inside=enemy_island['min_x']+1.0 if sign>0 else enemy_island['max_x']-1.0
            if sign*(pos['x']-inside)<0:
                if abs(pos['z']-lane_z)>0.11:
                    self._move_to(obs,me,(pos['x'],lane_z),requests)
                else:
                    self._move_to(obs,me,(inside,lane_z),requests,axis='x')
                return requests
            if not self._move_to(obs,me,staging,requests,axis='x'):
                return requests
            self._face(obs,me,bed_target,requests)
            if me['held_item']=='wool':
                self._select(obs,me,'wooden_sword',requests)
            payload={'team_id':enemy['team_id']};active=me['interaction']
            if active is None or active['kind']!='break_bed' or active['target']!=payload:
                requests.append(self._request(obs,'break_bed',payload))
            return requests
        if enemies:
            target=min(enemies,key=lambda e:((e['position']['x']-pos['x'])**2+
                                              (e['position']['z']-pos['z'])**2,e['player_id']))
            enemy_x=target['position']['x']
            same_island=(enemy_island['min_x'] <= pos['x'] < enemy_island['max_x'] and
                         enemy_island['min_x'] <= enemy_x < enemy_island['max_x'])
            if not same_island and abs(pos['z']-lane_z)>0.11:
                self._move_to(obs,me,(pos['x'],lane_z),requests)
            else:
                self._move_to(obs,me,(enemy_x,target['position']['z'] if same_island else lane_z),requests,axis='x')
            self._face(obs,me,(enemy_x,target['position']['z']),requests)
        else:
            self._move_to(obs,me,(pos['x'],pos['z']),requests)
        return requests


class DefensiveCounterattacker(EconomicAttacker):
    name='defensive-counterattacker'
    version='1.0'
    intercept_range=4.0

    def _combat(self,obs,me,enemies,terrain,requests):
        if super()._combat(obs,me,enemies,terrain,requests):
            return True
        pos=Vec2(me['position']['x'],me['position']['z'])
        close=[]
        for enemy in enemies:
            target=Vec2(enemy['position']['x'],enemy['position']['z'])
            if distance(pos,target)<=self.intercept_range and terrain.line_of_sight(pos,target):
                close.append((distance(pos,target),enemy['player_id'],target))
        if not close:
            return False
        _,_,target=min(close,key=lambda value:(value[0],value[1]))
        dx,dz=target.x-pos.x,target.z-pos.z
        direction=Vec2(1 if dx>0 else -1,0) if abs(dx)>0.11 else Vec2(0,1 if dz>0 else -1)
        knock=me['knockback']
        predicted=move_player(position=pos,direction=direction,knockback=Vec2(knock['x'],knock['z']),
                              terrain=terrain,physics=obs['rules']['physics'])
        if predicted.void_candidate:
            return False
        self._move_to(obs,me,(target.x,target.z),requests,axis='x')
        self._face(obs,me,(target.x,target.z),requests)
        return True
