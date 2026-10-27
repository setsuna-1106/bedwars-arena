"""L1 planar continuous movement, swept contacts and path support (P01–P09)."""
from dataclasses import dataclass
import math

from .geometry import AABB, Vec2, _open_axis_interval
from .terrain import Terrain


@dataclass(frozen=True, slots=True)
class MotionResult:
    position: Vec2
    knockback: Vec2
    void_candidate: bool
    contacts: tuple[tuple, ...]
    iteration_limit_reached: bool


def combined_velocity(direction: Vec2, knockback: Vec2, physics: dict) -> Vec2:
    """P07: reverse input weakens knockback only by alpha*K; lateral <= beta*K."""
    active=direction.normalized()*physics['speed_blocks_per_tick']
    magnitude=knockback.length()
    if magnitude < physics['knockback_stop_below']:
        return active
    normal=knockback*(1.0/magnitude)
    parallel=active.x*normal.x+active.z*normal.z
    side=active-normal*parallel
    side_length=side.length()
    side_limit=physics['control_beta']*magnitude
    if side_length > side_limit:
        side=side*(side_limit/side_length)
    return knockback+normal*max(parallel,-physics['control_alpha']*magnitude)+side


def add_knockback(current: Vec2, impulse: Vec2, physics: dict) -> Vec2:
    """Add independently generated impulses and cap the resulting vector."""
    result=current+impulse
    magnitude=result.length()
    cap=physics['knockback_speed_cap']
    return result*(cap/magnitude) if magnitude > cap else result


def _first_support_loss(start: Vec2, delta: Vec2, terrain: Terrain,
                        half_x: float, half_z: float) -> float | None:
    """Earliest t in [0,1] with zero positive-area support along this segment.

    Every supporting cell gives an open interval of center positions expanded by
    half the player's footprint. The connected union, not the two endpoints,
    decides whether the path remains supported.
    """
    intervals=[]
    for x,z in terrain.ground:
        ix=_open_axis_interval(start.x,delta.x,x-half_x,x+1+half_x)
        iz=_open_axis_interval(start.z,delta.z,z-half_z,z+1+half_z)
        if ix is None or iz is None:
            continue
        low,high=max(ix[0],iz[0]),min(ix[1],iz[1])
        if low < high and high >= 0 and low <= 1:
            intervals.append((low,high))
    ending=max((high for low,high in intervals if low < 0 < high),default=0.0)
    if ending == 0.0:
        return 0.0
    for low,high in sorted(intervals):
        if low >= ending:
            break  # open intervals meeting only at an endpoint have no support there
        if high > ending:
            ending=high
    return None if ending > 1.0 else max(0.0,ending)


def _swept_contact(start: Vec2, delta: Vec2, obstacle: AABB,
                   half_x: float, half_z: float, time_tol: float):
    """Point against expanded obstacle; return entry time and outward normals."""
    box=obstacle.expanded(half_x,half_z)
    ix=_open_axis_interval(start.x,delta.x,box.min_x,box.max_x)
    iz=_open_axis_interval(start.z,delta.z,box.min_z,box.max_z)
    if ix is None or iz is None:
        return None
    entry=max(ix[0],iz[0]); exit=min(ix[1],iz[1])
    if exit <= max(entry,0.0) or entry > 1.0 or exit <= 0.0:
        return None
    if entry < 0:
        raise ValueError('Motion starts inside an obstacle')
    normals=[]
    if delta.x and abs(ix[0]-entry) <= time_tol:
        normals.append((-1,0) if delta.x > 0 else (1,0))
    if delta.z and abs(iz[0]-entry) <= time_tol:
        normals.append((0,-1) if delta.z > 0 else (0,1))
    if not normals:
        raise ValueError('Collision without a contact normal')
    return entry,tuple(normals),box


def move_player(*, position: Vec2, direction: Vec2, knockback: Vec2,
                terrain: Terrain, physics: dict) -> MotionResult:
    """Sweep and slide on static walls/beds, stopping at first loss of support.

    No player is passed as an obstacle. Collision removes only inward knockback
    components; the remaining knockback then decays for the following tick.
    """
    width,depth=physics['player_width'],physics['player_depth']
    half_x,half_z=width/2,depth/2
    if not terrain.free(AABB.centered(position,width,depth)):
        raise ValueError('Player starts inside an obstacle')
    if knockback.length() < physics['knockback_stop_below']:
        knockback=Vec2(0,0)
    remaining=combined_velocity(direction,knockback,physics)
    location=position
    contacts=[]
    iteration_limit=False
    void=False
    distance_tol=physics['contact_distance_tolerance']
    time_tol=physics['contact_time_tolerance']
    zero_tol=physics['velocity_zero_tolerance']
    if not terrain.supported(AABB.centered(location,width,depth)):
        return MotionResult(location,knockback,True,(),False)
    iterations=0
    while remaining.length() > zero_tol:
        if iterations >= physics['collision_iterations_per_tick']:
            iteration_limit=True
            break
        iterations+=1
        hits=[]
        for key,obstacle in terrain.obstacles():
            hit=_swept_contact(location,remaining,obstacle,half_x,half_z,time_tol)
            if hit is not None:
                hits.append((hit[0],key,hit[1],hit[2]))
        if not hits:
            loss=_first_support_loss(location,remaining,terrain,half_x,half_z)
            if loss is None:
                location=location+remaining
            else:
                location=location+remaining*loss
                void=True
            remaining=Vec2(0,0)
            break
        earliest=min(hit[0] for hit in hits)
        segment=remaining*earliest
        loss=_first_support_loss(location,segment,terrain,half_x,half_z)
        if loss is not None:
            location=location+segment*loss
            void=True
            remaining=Vec2(0,0)
            break
        location=location+segment
        simultaneous=sorted((hit for hit in hits if hit[0]-earliest <= time_tol),key=lambda h:h[1])
        block_x=block_z=False
        x,z=location.x,location.z
        kx,kz=knockback.x,knockback.z
        for _,key,normals,expanded in simultaneous:
            for nx,nz in normals:
                contacts.append((key,nx,nz))
                if nx:
                    block_x=True
                    face=expanded.min_x if nx < 0 else expanded.max_x
                    if abs(x-face) <= distance_tol:
                        # Reconstructing the player's AABB can round a nominal
                        # contact one ULP into the obstacle. Move only outward.
                        boundary=key[0] if nx < 0 else key[0]+1
                        if nx < 0:
                            while face+half_x > boundary:
                                face=math.nextafter(face,-math.inf)
                        else:
                            while face-half_x < boundary:
                                face=math.nextafter(face,math.inf)
                        x=face
                    if kx*nx < 0:
                        kx=0.0
                if nz:
                    block_z=True
                    face=expanded.min_z if nz < 0 else expanded.max_z
                    if abs(z-face) <= distance_tol:
                        boundary=key[1] if nz < 0 else key[1]+1
                        if nz < 0:
                            while face+half_z > boundary:
                                face=math.nextafter(face,-math.inf)
                        else:
                            while face-half_z < boundary:
                                face=math.nextafter(face,math.inf)
                        z=face
                    if kz*nz < 0:
                        kz=0.0
        location=Vec2(x,z)
        knockback=Vec2(kx,kz)
        remaining=remaining*(1.0-earliest)
        remaining=Vec2(0.0 if block_x else remaining.x,0.0 if block_z else remaining.z)
    knockback=knockback*physics['knockback_decay']
    if knockback.length() < physics['knockback_stop_below']:
        knockback=Vec2(0,0)
    return MotionResult(location,knockback,void,tuple(contacts),iteration_limit)
