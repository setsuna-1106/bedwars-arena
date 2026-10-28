"""Versioned public-observation and discrete-request adapter for L1 PPO."""
from math import floor, hypot, isfinite
import numpy as np

GRID_X=16
GRID_Z=8
MAP_CHANNELS=4
PLAYER_FEATURES=31
ITEM_LIMIT=16
ITEM_FEATURES=6
GLOBAL_FEATURES=9
FEATURE_SIZE=GRID_X*GRID_Z*MAP_CHANNELS+4*PLAYER_FEATURES+ITEM_LIMIT*ITEM_FEATURES+GLOBAL_FEATURES
ENCODING_VERSION='l1-ppo-observation-v1'
DIRECTIONS=((1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1))
ITEMS=('wooden_sword','iron_sword','wool','shears','iron')
PRODUCTS=('wool','iron_sword','armor_1')
ACTIONS=(('hold','cancel_movement','cancel_interaction')+
         tuple(f'move_{x}_{z}' for x,z in DIRECTIONS)+
         tuple(f'turn_{x}_{z}' for x,z in DIRECTIONS)+
         tuple(f'select_{item}' for item in ITEMS)+
         ('attack_nearest','break_enemy_bed','break_nearest_wool')+
         tuple(f'place_bridge_{x}_{z}' for x,z in DIRECTIONS)+
         tuple(f'place_wall_{x}_{z}' for x,z in DIRECTIONS)+
         tuple(f'buy_{product}' for product in PRODUCTS)+('drop_one','drop_eight','drop_all'))
ACTION_VERSION='l1-ppo-discrete-v1'


def _clip(value,maximum=1.0):
    return max(-maximum,min(maximum,float(value)))


def _position(value,low,high):
    return _clip(2*(float(value)-low)/(high-low)-1)


def _me(obs):
    return next(p for p in obs['players'] if p['player_id']==obs['self_player_id'])


def encode_observation(obs):
    """Encode only public observation fields in a fixed, documented 741-vector."""
    bounds=obs['map']['bounds']; xmin,xmax=bounds['min_x'],bounds['max_x'];zmin,zmax=bounds['min_z'],bounds['max_z']
    if xmax<=xmin or zmax<=zmin or len(obs['players'])!=4:
        raise ValueError('L1 PPO requires bounded 2v2 observations')
    cells=np.zeros((MAP_CHANNELS,GRID_Z,GRID_X),dtype=np.float64)
    # Aggregate the public cells into map-relative bins; each input cell has exactly one bin.
    bin_area=max(1.0,(xmax-xmin)*(zmax-zmin)/(GRID_X*GRID_Z))
    def put(channel,x,z):
        ix=int((x-xmin)*GRID_X/(xmax-xmin)); iz=int((z-zmin)*GRID_Z/(zmax-zmin))
        if 0<=ix<GRID_X and 0<=iz<GRID_Z: cells[channel,iz,ix]+=1/bin_area
    for b in obs['terrain']['blocks']:
        channel=0 if b['kind']=='original' and b['layer']=='bridge' else 1 if b['layer']=='bridge' else 2
        put(channel,b['x'],b['z'])
    teams={t['team_id']:t for t in obs['teams']}
    for bed in obs['terrain']['beds']:
        if teams[bed['team_id']]['bed']['status']=='present': put(3,bed['x'],bed['z'])
    np.clip(cells,0,1,out=cells)
    me=_me(obs); order=[me]+sorted((p for p in obs['players'] if p['player_id']!=me['player_id']),
                                   key=lambda p:(p['team_id']!=me['team_id'],p['player_id']))
    players=[]
    for p in order:
        alive=p['life']=='alive'; pos=p.get('position',{'x':(xmin+xmax)/2,'z':(zmin+zmax)/2})
        face=p.get('facing',{'x':0,'z':0});vel=p.get('velocity',{'x':0,'z':0});kb=p.get('knockback',{'x':0,'z':0})
        inv=p.get('inventory',{});cd=p.get('cooldowns',{});action=p.get('interaction') or {};kind=action.get('kind')
        players.extend([1.0,float(p['player_id']==me['player_id']),float(p['team_id']==me['team_id']),
            float(alive),float(p['life']=='respawning'),float(p['life']=='eliminated'),
            _position(pos['x'],xmin,xmax),_position(pos['z'],zmin,zmax),_clip(face['x']),_clip(face['z']),
            _clip(p.get('health',0)/obs['rules']['combat']['max_hp']),_clip(p.get('armor_tier',0)),
            _clip(p.get('protection_remaining',0)/max(1,obs['rules']['life']['protection_duration_ticks'])),
            _clip(inv.get('iron',0)/512),_clip(inv.get('wool',0)/512),float('wooden_sword' in inv),
            float('iron_sword' in inv),float('shears' in inv),_clip(vel['x']),_clip(vel['z']),
            _clip(kb['x']),_clip(kb['z']),_clip(cd.get('attack',0)/20),_clip(cd.get('hurt',0)/20),
            float(p.get('movement') is not None),float(kind=='attack'),float(kind=='break_block'),
            float(kind=='break_bed'),float(kind=='place_block'),_clip(action.get('progress',0)/40),
            _clip(p.get('respawn_remaining',0)/max(1,obs['rules']['life']['respawn_delay_ticks']))])
    pos=me.get('position',{'x':(xmin+xmax)/2,'z':(zmin+zmax)/2})
    ground=sorted(obs['ground_items'],key=lambda e:((e['position']['x']-pos['x'])**2+
                    (e['position']['z']-pos['z'])**2,e['entity_id']))[:ITEM_LIMIT]
    items=[]
    for e in ground:
        items.extend([1.0,_position(e['position']['x'],xmin,xmax),_position(e['position']['z'],zmin,zmax),
                      float(e['item_key']=='iron'),float(e['item_key']=='wool'),_clip(e['quantity']/64)])
    items.extend([0.0]*(ITEM_FEATURES*(ITEM_LIMIT-len(ground))))
    roster=[p['player_id'] for p in obs['players']];self_index=roster.index(me['player_id'])
    own=teams[me['team_id']];enemy=next(t for t in obs['teams'] if t['team_id']!=me['team_id'])
    globals_=[_clip(obs['observed_tick']/max(1,obs['schedule']['game_end_tick']))]
    globals_.extend(float(self_index==i) for i in range(4))
    globals_.extend([float(own['bed']['status']=='present'),float(enemy['bed']['status']=='present'),
                     _clip(len(obs['ground_items'])/ITEM_LIMIT),float(me['team_id']==obs['map']['teams'][0]['team_id'])])
    result=np.concatenate((cells.ravel(),np.asarray(players,dtype=np.float64),np.asarray(items,dtype=np.float64),
                           np.asarray(globals_,dtype=np.float64)))
    if result.shape!=(FEATURE_SIZE,) or not np.isfinite(result).all():
        raise ValueError('Invalid PPO observation encoding')
    return result


def _nearest_enemy(obs,me):
    pos=me['position'];physics=obs['rules']['physics'];half_x=physics['player_width']/2;half_z=physics['player_depth']/2
    enemies=[]
    for p in obs['players']:
        if p['team_id']==me['team_id'] or p['life']!='alive':continue
        dx=abs(pos['x']-p['position']['x']);dz=abs(pos['z']-p['position']['z'])
        d=hypot(max(0,dx-half_x),max(0,dz-half_z))
        if d<=obs['rules']['combat']['range_blocks']:
            enemies.append((d,p['player_id'],p))
    return min(enemies,key=lambda x:(x[0],x[1]))[2] if enemies else None


def _nearest_bed(obs,me):
    states={t['team_id']:t for t in obs['teams']};p=me['position'];out=[]
    for bed in obs['terrain']['beds']:
        if bed['team_id']==me['team_id'] or states[bed['team_id']]['bed']['status']!='present':continue
        d=hypot(p['x']-(bed['x']+0.5),p['z']-(bed['z']+0.5))
        if d<=obs['rules']['building']['range_blocks']:out.append((d,bed['team_id']))
    return min(out)[1] if out else None


def _nearest_wool(obs,me):
    p=me['position'];out=[]
    for block in obs['terrain']['blocks']:
        if block['kind']!='wool' or 'instance_id' not in block:continue
        d=hypot(p['x']-(block['x']+0.5),p['z']-(block['z']+0.5))
        if d<=obs['rules']['building']['range_blocks']:
            out.append((d,block['x'],block['z'],block['layer'],block['instance_id'],block))
    return min(out,key=lambda a:a[:-1])[-1] if out else None


def action_mask(obs):
    """Mask absent targets/items; the core still decides distance, LOS and validity."""
    me=_me(obs);mask=np.zeros(len(ACTIONS),dtype=np.bool_);mask[0]=True
    if me['life']!='alive':return mask
    inv=me['inventory'];p=me['position'];map_data=obs['map'];bounds=map_data['bounds']
    shop=next(t['shop'] for t in map_data['teams'] if t['team_id']==me['team_id'])
    near_shop=hypot(p['x']-shop['x'],p['z']-shop['z'])<=obs['rules']['shop']['range_blocks']
    for i,action in enumerate(ACTIONS[1:],1):
        if action=='cancel_movement':mask[i]=me.get('movement') is not None
        elif action=='cancel_interaction':mask[i]=me.get('interaction') is not None
        elif action.startswith(('move_','turn_')):mask[i]=True
        elif action.startswith('select_'):mask[i]=action[7:] in inv
        elif action=='attack_nearest':mask[i]=_nearest_enemy(obs,me) is not None
        elif action=='break_enemy_bed':mask[i]=_nearest_bed(obs,me) is not None
        elif action=='break_nearest_wool':mask[i]=_nearest_wool(obs,me) is not None
        elif action.startswith('place_'):
            x,z=map(int,action.rsplit('_',2)[-2:]);tx,tz=floor(p['x'])+x,floor(p['z'])+z
            mask[i]=inv.get('wool',0)>0 and bounds['min_x']<=tx<bounds['max_x'] and bounds['min_z']<=tz<bounds['max_z']
        elif action.startswith('buy_'):
            product=action[4:];mask[i]=near_shop and inv.get('iron',0)>=obs['rules']['shop']['products'][product]['cost']
        elif action.startswith('drop_'):mask[i]=inv.get('iron',0)>0
    return mask


def decode_action(obs,index):
    if type(index) is not int or not 0<=index<len(ACTIONS):raise ValueError('Invalid PPO action index')
    if not action_mask(obs)[index]:raise ValueError('PPO action is masked')
    action=ACTIONS[index];me=_me(obs);pid=obs['self_player_id'];tick=obs['observed_tick']
    if action=='hold':return []
    if action.startswith('cancel_'):kind='cancel';payload={'channel':action[7:]}
    elif action.startswith(('move_','turn_')):
        kind=action.split('_',1)[0];x,z=map(int,action.rsplit('_',2)[-2:]);payload={'x':x,'z':z}
    elif action.startswith('select_'):kind='select_item';payload={'item':action[7:]}
    elif action=='attack_nearest':
        target=_nearest_enemy(obs,me);kind='attack';payload={'player_id':target['player_id'],'life_index':target['life_index']}
    elif action=='break_enemy_bed':kind='break_bed';payload={'team_id':_nearest_bed(obs,me)}
    elif action=='break_nearest_wool':
        b=_nearest_wool(obs,me);kind='break_block';payload={k:b[k] for k in ('x','z','layer','instance_id')}
    elif action.startswith('place_'):
        _,layer,x,z=action.split('_');kind='place_block';payload={'x':floor(me['position']['x'])+int(x),'z':floor(me['position']['z'])+int(z),'layer':layer}
    elif action.startswith('buy_'):kind='buy';payload={'product':action[4:]}
    else:
        amount=me['inventory']['iron'];kind='drop_resource';payload={'resource':'iron',
            'quantity':1 if action=='drop_one' else min(8,amount) if action=='drop_eight' else amount}
    return [{'request_id':f'ppo-{pid}-{tick}-{index}','kind':kind,'payload':payload}]
