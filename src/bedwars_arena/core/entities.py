"""L1 stationary ground items, capacity and atomic construction."""
import math

from .geometry import Vec2
from .messages import ScheduledTask
from .terrain import Terrain
from .time import identifier, integer


def capacity_for(inventory, item, profile):
    limits=profile['inventory']['stack_limits'];limit=limits[item]
    occupied=sum((count+limits[key]-1)//limits[key] for key,count in inventory.items())
    free=profile['inventory']['stack_capacity']-occupied
    current=inventory.get(item,0)
    partial=(limit-current%limit)%limit if current else 0
    return partial+free*limit


def make_item(*,entity_id,item,quantity,x,z,created_at,pickup_ready_at,expires_at,source,profile):
    return {'entity_id':entity_id,'item_key':item,'quantity':quantity,
            'spatial':{'x':x,'y':profile['ground_items']['center_y'],'z':z,
                       'velocity_x':0.0,'velocity_z':0.0},
            'created_at':created_at,'pickup_ready_at':pickup_ready_at,'expires_at':expires_at,
            'source':source}


def validate_item(raw, *, profile, terrain, now, phase):
    if not isinstance(raw,dict) or set(raw) != {'entity_id','item_key','quantity','spatial','created_at',
                                               'pickup_ready_at','expires_at','source'}:
        raise ValueError('Invalid ground item fields')
    identifier(raw['entity_id'],'entity_id')
    item=raw['item_key'];limits=profile['ground_items']['entity_limits']
    if item not in limits:
        raise ValueError('Unsupported ground item')
    integer(raw['quantity'],'ground quantity',1)
    if raw['quantity']>limits[item]:
        raise ValueError('Ground item exceeds entity limit')
    for key in ('created_at','pickup_ready_at','expires_at'):
        integer(raw[key],key)
    if raw['created_at']>now or raw['pickup_ready_at']<raw['created_at'] or raw['expires_at']<=raw['created_at']:
        raise ValueError('Invalid ground item time')
    if raw['expires_at']<now or raw['expires_at']==now and phase>0:
        raise ValueError('Expired ground item was not removed')
    pos=raw['spatial']
    if not isinstance(pos,dict) or set(pos)!={'x','y','z','velocity_x','velocity_z'}:
        raise ValueError('Invalid ground item spatial fields')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in pos.values()):
        raise ValueError('Ground item coordinates must be finite')
    if pos['y']!=profile['ground_items']['center_y'] or pos['velocity_x']!=0 or pos['velocity_z']!=0:
        raise ValueError('L1 ground items are stationary on the walking layer')
    source=raw['source']
    if not isinstance(source,dict) or set(source)!={'kind','source_id'} or source['kind'] not in ('generator','player_drop','recovery','death','preset'):
        raise ValueError('Invalid ground item source')
    identifier(source['source_id'],'source_id')
    gp=profile['ground_items']
    if not terrain.safe_drop(Vec2(pos['x'],pos['z']),gp['width'],gp['depth']):
        raise ValueError('Ground item position is unsafe')


def create_ground(plan,state,definitions,*,tick,item,quantity,x,z,delay,source):
    """Build one or more item entities and expiry tasks in the same plan."""
    profile=definitions.profile.data
    integer(quantity,'quantity',1);integer(delay,'pickup delay')
    gp=profile['ground_items'];limit=gp['entity_limits'][item]
    terrain=Terrain.from_world(state,definitions.map.data)
    if not terrain.safe_drop(Vec2(x,z),gp['width'],gp['depth']):
        raise ValueError('Ground item position is unsafe')
    required=(quantity+limit-1)//limit
    if len(state['entities'])+sum(v is not None for v in plan.entities.values())+required>profile['budget']['ground_entities']:
        raise ValueError('Ground entity budget exceeded')
    created=[]
    while quantity:
        count=min(limit,quantity);quantity-=count
        eid=plan.allocate();expires=tick+gp['lifetime_ticks']
        raw=make_item(entity_id=eid,item=item,quantity=count,x=x,z=z,created_at=tick,
                      pickup_ready_at=tick+delay,expires_at=expires,source=source,profile=profile)
        plan.entities[eid]=raw
        task=ScheduledTask.create(task_id=plan.allocate(),kind='expire_ground_item',created_at=tick,
                                  execute_at=expires,phase=0,source_order=0,payload={'entity_id':eid})
        plan.add_tasks.append(task)
        created.append(eid)
    return created
