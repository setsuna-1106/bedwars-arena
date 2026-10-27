"""Shared 2-D AABB, distance and segment-interior geometry for L1."""
from dataclasses import dataclass
import math


def finite(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float
    z: float

    def __post_init__(self):
        object.__setattr__(self,'x',finite(self.x,'x'))
        object.__setattr__(self,'z',finite(self.z,'z'))

    def __add__(self, other):
        return Vec2(self.x + other.x,self.z + other.z)

    def __sub__(self, other):
        return Vec2(self.x - other.x,self.z - other.z)

    def __mul__(self, scalar):
        return Vec2(self.x * scalar,self.z * scalar)

    def length(self):
        return math.hypot(self.x,self.z)

    def normalized(self):
        length = self.length()
        if not math.isfinite(length):
            # Scale before hypot to avoid overflow on large, finite inputs.
            scale = max(abs(self.x),abs(self.z))
            x,z = self.x/scale,self.z/scale
            length = math.hypot(x,z)
            return Vec2(x/length,z/length)
        if length == 0:
            return Vec2(0,0)
        return Vec2(self.x/length,self.z/length)


@dataclass(frozen=True, slots=True)
class AABB:
    min_x: float
    max_x: float
    min_z: float
    max_z: float

    def __post_init__(self):
        for key in ('min_x','max_x','min_z','max_z'):
            object.__setattr__(self,key,finite(getattr(self,key),key))
        if self.min_x >= self.max_x or self.min_z >= self.max_z:
            raise ValueError('AABB must have positive width and depth')

    @classmethod
    def centered(cls, center: Vec2, width: float, depth: float):
        width,depth=finite(width,'width'),finite(depth,'depth')
        if width <= 0 or depth <= 0:
            raise ValueError('AABB dimensions must be positive')
        return cls(center.x-width/2,center.x+width/2,center.z-depth/2,center.z+depth/2)

    def overlaps(self, other) -> bool:
        """Strict interior overlap; touching a face or corner is legal."""
        return (self.min_x < other.max_x and other.min_x < self.max_x and
                self.min_z < other.max_z and other.min_z < self.max_z)

    def expanded(self, x: float, z: float):
        x,z=finite(x,'x expansion'),finite(z,'z expansion')
        if x < 0 or z < 0:
            raise ValueError('Expansion must be nonnegative')
        return AABB(self.min_x-x,self.max_x+x,self.min_z-z,self.max_z+z)

    def contains_closed(self, point: Vec2) -> bool:
        return self.min_x <= point.x <= self.max_x and self.min_z <= point.z <= self.max_z


def grid_cell(value: float) -> int:
    """Half-open cell membership, including the negative side of zero."""
    return math.floor(finite(value,'coordinate'))


def distance_to_aabb(point: Vec2, box: AABB) -> float:
    dx=max(box.min_x-point.x,0.0,point.x-box.max_x)
    dz=max(box.min_z-point.z,0.0,point.z-box.max_z)
    return math.hypot(dx,dz)


def distance(a: Vec2, b: Vec2) -> float:
    return math.hypot(a.x-b.x,a.z-b.z)


def _open_axis_interval(start: float, delta: float, low: float, high: float):
    """Times at which start + t*delta lies strictly inside (low, high)."""
    if delta == 0:
        return (-math.inf,math.inf) if low < start < high else None
    a,b=(low-start)/delta,(high-start)/delta
    return (min(a,b),max(a,b))


def segment_enters_interior(start: Vec2, end: Vec2, box: AABB) -> bool:
    """Endpoints and edges alone do not occlude; any interior segment does."""
    delta=end-start
    ix=_open_axis_interval(start.x,delta.x,box.min_x,box.max_x)
    iz=_open_axis_interval(start.z,delta.z,box.min_z,box.max_z)
    if ix is None or iz is None:
        return False
    enter=max(0.0,ix[0],iz[0])
    exit=min(1.0,ix[1],iz[1])
    return enter < exit
