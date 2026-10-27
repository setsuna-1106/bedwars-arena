"""Sparse L1 ground, wall and bed geometry; no derived mutable cache."""
from dataclasses import dataclass
from .geometry import AABB, Vec2, segment_enters_interior


@dataclass(frozen=True, slots=True)
class Terrain:
    ground: frozenset[tuple[int,int]]
    walls: frozenset[tuple[int,int]]
    # (team_id, x, z); bed status remains in TeamState, not in terrain.
    beds: tuple[tuple[str,int,int], ...]
    bounds: tuple[int,int,int,int]

    def __post_init__(self):
        ground=frozenset(self.ground)
        walls=frozenset(self.walls)
        beds=tuple(tuple(bed) for bed in self.beds)
        bounds=tuple(self.bounds)
        for cell in ground | walls:
            if len(cell) != 2 or any(type(value) is not int for value in cell):
                raise ValueError('Terrain cells must use integer x/z coordinates')
        for bed in beds:
            if len(bed) != 3 or not isinstance(bed[0],str) or any(type(value) is not int for value in bed[1:]):
                raise ValueError('Invalid bed geometry')
        if len(bounds) != 4 or any(type(value) is not int for value in bounds) or bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
            raise ValueError('Invalid terrain bounds')
        object.__setattr__(self,'ground',ground)
        object.__setattr__(self,'walls',walls)
        object.__setattr__(self,'beds',beds)
        object.__setattr__(self,'bounds',bounds)

    @classmethod
    def from_world(cls, state: dict, map_data: dict):
        ground,walls=set(),set()
        for key in state['terrain']:
            x,y,z=(int(part) for part in key.split(','))
            if y == -1:
                ground.add((x,z))
            elif y == 0:
                walls.add((x,z))
        beds=[]
        for team in map_data['teams']:
            if state['teams'][team['team_id']]['bed_state']['status']=='present':
                beds.append((team['team_id'],team['bed']['x'],team['bed']['z']))
        b=map_data['bounds']
        return cls(frozenset(ground),frozenset(walls),tuple(sorted(beds)),
                   (b['min_x'],b['max_x'],b['min_z'],b['max_z']))

    def contains(self, point: Vec2) -> bool:
        x0,x1,z0,z1=self.bounds
        return x0 <= point.x < x1 and z0 <= point.z < z1

    def ground_at(self, x: int, z: int) -> bool:
        return (x,z) in self.ground

    def supported(self, box: AABB) -> bool:
        # The box needs a positive area of overlap, not full coverage.
        return any(box.overlaps(AABB(x,x+1,z,z+1)) for x,z in self.ground)

    def obstacles(self):
        """Stable order by grid coordinate, then kind/ID."""
        values=[((x,z,'wall',''),AABB(x,x+1,z,z+1)) for x,z in self.walls]
        values.extend(((x,z,'bed',team),AABB(x,x+1,z,z+1)) for team,x,z in self.beds)
        return tuple(sorted(values,key=lambda item:item[0]))

    def free(self, box: AABB) -> bool:
        return all(not box.overlaps(obstacle) for _,obstacle in self.obstacles())

    def line_of_sight(self, start: Vec2, end: Vec2, *, ignore: tuple | None = None) -> bool:
        return all(key == ignore or not segment_enters_interior(start,end,box)
                   for key,box in self.obstacles())

    def safe_drop(self, center: Vec2, width: float, depth: float) -> bool:
        box=AABB.centered(center,width,depth)
        return self.contains(center) and self.supported(box) and self.free(box)
