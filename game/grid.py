from dataclasses import dataclass
from typing import override
import pixpy as pix

Int2 = pix.Int2


def intervals_overlap_strict(a0: int, a1: int, b0: int, b1: int) -> bool:
    # positive-length overlap (not just a point)
    return min(a1, b1) > max(a0, b0)


TOP = 0
RIGHT = 1
BOTTOM = 2
LEFT = 3

NAMES = ["TOP", "RIGHT", "BOTTOM", "LEFT"]

DELTAS = [Int2(1, 0), Int2(0, 1), Int2(-1, 0), Int2(0, -1)]


@dataclass
class Edge:
    """Represents the Edge of a Rectangle"""

    pos: Int2
    l: int
    dir: int

    @property
    def delta(self) -> Int2:
        return DELTAS[self.dir]

    @property
    def mid(self) -> Int2:
        return self.pos + self.delta * (self.l // 2)

    @property
    def endp(self) -> Int2:
        return self.pos + self.delta * self.l

    @property
    def norm(self) -> Int2:
        return DELTAS[(self.dir - 1) & 3]

    @property
    def is_horiz(self) -> bool:
        return self.dir == TOP or self.dir == BOTTOM

    @property
    def is_vert(self) -> bool:
        return self.dir == LEFT or self.dir == RIGHT

    def opposes(self, other: "Edge") -> bool:
        n = self.dir | other.dir
        return n == 2 or n == 4

    def faces(self, other: "Edge") -> bool:
        """Return True if edges opposes and points to each other"""
        if self.dir == TOP:
            return other.dir == BOTTOM and other.pos.y < self.pos.y
        if self.dir == BOTTOM:
            return other.dir == TOP and other.pos.y > self.pos.y
        if self.dir == LEFT:
            return other.dir == RIGHT and other.pos.x < self.pos.x
        if self.dir == RIGHT:
            return other.dir == LEFT and other.pos.x > self.pos.x
        return False

    def faces_point(self, other: Int2):
        if self.dir == TOP:
            return other.y < self.pos.y
        if self.dir == BOTTOM:
            return other.y > self.pos.y
        if self.dir == LEFT:
            return other.x < self.pos.x
        if self.dir == RIGHT:
            return other.x > self.pos.x
        return False


    @override
    def __repr__(self):
        n = NAMES[self.dir]
        return f"{n} : {self.pos} -> {self.endp}"

    def shrink(self, delta: int) -> "Edge":
        return Edge(self.pos + self.delta * delta, self.l - delta * 2, self.dir)


def project(a: Edge, b: Edge) -> Edge | None:
    """
    'Project' one Edge onto another. If edges are opposing, return the part of
    edge 'a' that overlaps with edge 'b'. Otherwise return None
    """
    if a.dir == b.dir:
        return None
    if a.is_horiz and b.is_horiz:
        if a.dir == TOP:
            s = max(a.pos.x, b.endp.x)
            e = min(a.endp.x, b.pos.x)
        else:
            s = min(a.pos.x, b.endp.x)
            e = max(a.endp.x, b.pos.x)
        print(f"{s} {e}")
        if e > s and a.dir == TOP:
            return Edge(Int2(s, a.pos.y), e - s, a.dir)
        if e < s and a.dir == BOTTOM:
            return Edge(Int2(s, a.pos.y), s - e, a.dir)
        return None
    if a.is_vert and b.is_vert:
        if a.dir == RIGHT:
            s = max(a.pos.y, b.endp.y)
            e = min(a.endp.y, b.pos.y)
        else:
            s = min(a.pos.y, b.endp.y)
            e = max(a.endp.y, b.pos.y)
        print(f"{s} {e}")
        if e > s and a.dir == RIGHT:
            return Edge(Int2(a.pos.x, s), e - s, a.dir)
        elif e < s and a.dir == LEFT:
            return Edge(Int2(a.pos.x, s), s - e, a.dir)
        return None
    return None


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def xy(self) -> Int2:
        return Int2(self.x, self.y)

    def edge(self, dir: int) -> Edge:
        if dir == TOP:
            return Edge(self.xy, self.w, dir)
        elif dir == RIGHT:
            return Edge(self.xy + (self.w - 1, 0), self.h, dir)
        elif dir == BOTTOM:
            return Edge(self.xy + (self.w - 1, self.h - 1), self.w, dir)
        else:
            return Edge(self.xy + (0, self.h - 1), self.h, dir)

    @property
    def top_edge(self) -> Edge:
        return self.edge(TOP)

    @property
    def bottom_edge(self) -> Edge:
        return self.edge(BOTTOM)

    @property
    def left_edge(self) -> Edge:
        return self.edge(LEFT)

    @property
    def right_edge(self) -> Edge:
        return self.edge(RIGHT)

    @property
    def center(self) -> Int2:
        return Int2(self.x + self.w // 2, self.y + self.h // 2)

    @property
    def bottom_center(self) -> Int2:
        return Int2(self.x + self.w / 2, self.y + self.h)

    @property
    def top_center(self) -> Int2:
        return Int2(self.x + self.w / 2, self.y)

    @property
    def left_center(self) -> Int2:
        return Int2(self.x, self.y + self.h / 2)

    @property
    def right_center(self) -> Int2:
        return Int2(self.x + self.w, self.y + self.h / 2)

    @property
    def x1(self) -> int:
        return self.x + self.w

    @property
    def y1(self) -> int:
        return self.y + self.h

    def touches_along_edge(self, b: "Rect") -> bool:
        # Vertical edge touch
        if self.x1 == b.x or self.x == b.x1:
            return intervals_overlap_strict(self.y, self.y1, b.y, b.y1)

        # Horizontal edge touch
        if self.y == b.y1 or self.y1 == b.y:
            return intervals_overlap_strict(self.x, self.x1, b.x, b.x1)

        return False


if __name__ == "__main__":
    e0 = Edge(pix.Int2(1, 1), 10, TOP)
    e1 = Edge(pix.Int2(8, 3), 5, BOTTOM)
    print(project(e0, e1))
    print(project(e1, e0))

    e0 = Edge(pix.Int2(1, 1), 10, TOP)
    e1 = Edge(pix.Int2(18, 3), 7, BOTTOM)
    print(project(e0, e1))
    print(project(e1, e0))

    e0 = Edge(pix.Int2(10, 10), 50, RIGHT)
    e1 = Edge(pix.Int2(100, 40), 12, LEFT)
    print(project(e0, e1))
    print(project(e1, e0))
