from collections.abc import MutableSequence, MutableSet, Sequence, Set
from dataclasses import dataclass
import itertools
import math
import random
import time
import array
import copy
from tkinter import CENTER
from typing import Final, override
import pixpy as pix
from grid import Rect, Edge, project

Int2 = pix.Int2

FLOOR: int = 0
WALL: int = 1
DOOR: int = 2

# Generate an area of  rooms with tunnels and doors into `target`
#
# Use BSP to split up area into a tree
# Randomly join some leaves to create non-rectangular rooms
# Join other nodes with tunnels
# Join some adjacent leaves from other branches together
# Add doors/tunnels to connect to the given border entry-points


def nrand(avg: float, var: float, limit: float = 0.5):
    return min(max(random.gauss(avg, var), avg - limit), avg + limit)


HORIZ: int = 1
VERT: int = 2


def dist(a: Int2, b: Int2) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def distr(a: Int2, b: Int2) -> int:
    return int(math.hypot(a.x - b.x, a.y - b.y))


class Node:
    def __init__(self, rect: Rect):
        self.rect: Rect = rect
        self.children: tuple[Node, Node] | None = None

    # Split along specified axis, or best fitting
    def split(self, axis: int = 0):
        r = self.rect

        if axis == 0:
            axis = HORIZ if r.h > r.w else VERT

        v = nrand(0.5, 0.15, 0.35)
        if axis == HORIZ:
            a = int(v * self.rect.h)
            top_rect = Rect(r.x, r.y, r.w, a)
            bottom_rect = Rect(r.x, r.y + a, r.w, r.h - a)
            self.children = (Node(top_rect), Node(bottom_rect))
        else:
            a = int(v * self.rect.w)
            left_rect = Rect(r.x, r.y, a, r.h)
            right_rect = Rect(r.x + a, r.y, r.w - a, r.h)
            self.children = (Node(left_rect), Node(right_rect))


# Generate a BSP (K-D) tree. Start with the given size, and create child
# nodes using split() until a node has a width or height that is smaller than min_size
# (If a any child of a node is too small, abondon the split and keep the node as a leaf)
def generate_tree(root: Rect, min_size: int) -> Node:
    node = Node(root)

    node.split()
    if node.children:
        left_child, right_child = node.children
        if (
            left_child.rect.w >= min_size
            and left_child.rect.h >= min_size
            and right_child.rect.w >= min_size
            and right_child.rect.h >= min_size
        ):
            node.children = (
                generate_tree(left_child.rect, min_size),
                generate_tree(right_child.rect, min_size),
            )
        else:
            node.children = None
    return node


def get_rects(root: Node) -> list[Rect]:
    # Get all leaf nodes
    def get_leaves(n: Node, leaves: list[Node]):
        if n.children is None:
            leaves.append(n)
        else:
            get_leaves(n.children[0], leaves)
            get_leaves(n.children[1], leaves)

    leaves: list[Node] = []
    get_leaves(root, leaves)

    return list([n.rect for n in leaves])


@dataclass
class Room:
    rects: list[Rect]
    connections: MutableSet[int]

    def __init__(self, rect: Rect):
        self.rects = [rect]
        self.connections = set()

    @property
    def center(self) -> Int2:
        return sum([r.center for r in self.rects], Int2.ZERO) // len(self.rects)


class Map:
    def __init__(self, size: Int2):
        self.rooms: list[Room] = []

        self.width: Final = size.x
        self.height: Final = size.y

        root = Rect(0, 0, self.width, self.height)
        node = generate_tree(root, 8)
        self.rooms = list([Room(r) for r in get_rects(node)])
        self.shrink_rooms()
        self.tiles: Final = array.array("H", [0] * self.width * self.height)
        self.merge_rooms()
        self.draw_rooms()
        self.build_graph()
        self.join_rooms()

    # Potentially make rects in each node smaller.
    # Each of the 4 sides of every rect has a 50% chance of being
    # moved ~10-20% towards the center, shrinking the rectangle randomly
    def shrink_rooms(self, shrink_chance: float = 0.7):
        percent = 0.25

        for room in self.rooms:
            r = room.rects[0]
            # Each side has 50% chance of shrinking by ~10-20% toward center
            # Left side: move right
            if random.random() < shrink_chance:
                shrink = int(nrand(percent, 0.05, 0.15) * r.w)
                r.x += shrink
                r.w -= shrink

            # Right side: move left
            if random.random() < shrink_chance:
                shrink = int(nrand(percent, 0.05, 0.15) * r.w)
                r.w -= shrink

            # Top side: move down
            if random.random() < shrink_chance:
                shrink = int(nrand(percent, 0.05, 0.15) * r.h)
                r.y += shrink
                r.h -= shrink

            # Bottom side: move up
            if random.random() < shrink_chance:
                shrink = int(nrand(percent, 0.05, 0.15) * r.h)
                r.h -= shrink

    def draw_rooms(self, offs: int = 10):
        for i, room in enumerate(self.rooms):
            for r in room.rects:
                for y in range(r.h):
                    for x in range(r.w):
                        self.tiles[r.x + x + self.width * (r.y + y)] = i + offs

    def plot(self, p: Int2, v: int):
        self.tiles[p.x + p.y * self.width] = v

    def draw_tunnel(self, frm: Int2, to: Int2, tile: int = 1):

        dx = 1 if to.x > frm.x else -1
        dy = 1 if to.y > frm.y else -1
        p = frm
        while p.x != to.x:
            self.plot(p, tile)
            p += (dx, 0)
        while p.y != to.y:
            self.plot(p, tile)
            p += (0, dy)
        self.plot(p, tile)

    def horiz_draw(self, mid: Rect, to: Rect):
        p = mid.center
        while True:
            self.plot(p, 1)

    def ldraw(self, a: Edge, b: Edge):
        p = a.mid
        end = b.mid
        print(f"###################### FROM {p} to {end}, {a.norm}, -{b.norm}")
        return
        while p.x != end.x and p.y != end.y:
            self.plot(p, 1)
            p += a.norm
            # print(p)
        while end != p:
            self.plot(p, 1)
            p -= b.norm
            # print(p)

    def sdraw(self, a: Edge, b: Edge) -> bool:
        proj = project(e0, e1)
        # Can we go from e0 -> e1
        if proj and e0.pos.y > e1.pos.y:
            p = proj.mid
            tp = Int2(p.x, e1.pos.y)
            while p != tp:
                self.plot(p, 1)
                p += proj.norm

    def join_rects(self, a: Rect, b: Rect):

        e0, e1 = a.top_edge, b.bottom_edge
        proj = project(e0, e1)
        # Can we go from e0 -> e1
        if proj and e0.pos.y > e1.pos.y:
            p = proj.mid
            y = e1.pos.y
            while p.y != y:
                self.plot(p, 1)
                p += proj.norm
            return
        e0, e1 = a.left_edge, b.right_edge
        proj = project(e0, e1)
        # Can we go from e0 -> e1
        if proj and e0.pos.x > e1.pos.x:
            p = proj.mid
            x = e1.pos.x
            while p.x != x:
                self.plot(p, 1)
                p += proj.norm
                # p -= (1, 0)
            return

        dists: list[tuple[int, int, int]] = []
        for i in range(4):
            m = a.edge(i).mid
            j = (i - 1) & 3
            d = dist(m, b.edge(j).mid)
            dists.append((d, i, j))
            j = (i + 1) & 3
            d = dist(m, b.edge(j).mid)
            dists.append((d, i, j))

        dists.sort()
        print(dists)
        _, i, j = dists[0]
        print(f"JOIN EDGE {a.edge(i)} with {b.edge(j)}")
        self.ldraw(a.edge(i), b.edge(j))

    def join_rooms(self):
        for i, room in enumerate(self.rooms):
            for c in room.connections:
                other = self.rooms[c]
                d = [
                    (dist(r.center, other.center), i) for i, r in enumerate(room.rects)
                ]
                d2 = sorted(d)
                closest = room.rects[d2[0][1]]
                e = [
                    (dist(closest.center, r.center), i)
                    for i, r in enumerate(other.rects)
                ]
                e2 = sorted(e)
                closest2 = other.rects[e2[0][1]]
                print(f"Room {i} : {closest} -> {c} : {closest2}")
                self.join_rects(closest, closest2)

    def merge_rooms(self):

        for i, room in enumerate(self.rooms):
            for j, room2 in enumerate(self.rooms):
                if i == j or len(room2.rects) == 0:
                    continue
                for r1 in room.rects[:]:
                    for r2 in room2.rects:
                        if r1.touches_along_edge(r2):
                            room.rects.extend(room2.rects)
                            room2.rects = []
                            break
        self.rooms = list([room for room in self.rooms if len(room.rects) > 0])

    def build_graph(self):
        centers = [room.center for room in self.rooms]
        K = 4  # neighbors per room (tunable)

        candidate_edges: set[tuple[int, int, int]] = set()  # (i, j, weight)

        for i, ci in enumerate(centers):
            distances: list[tuple[int, int]] = []
            for j, cj in enumerate(centers):
                if i == j:
                    continue
                distances.append((dist(ci, cj), j))
            distances.sort()
            d = distances[0][0]
            no = distances[0][1]
            print(f"{len(distances)} ROOM #{i} closest {no} ({d} tiles)")
            for _, j in distances[:K]:
                a, b = sorted((i, j))
                candidate_edges.add((a, b, dist(centers[a], centers[b])))

        parent: list[int] = list(range(len(self.rooms)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int):
            ra = find(a)
            rb = find(b)
            if ra != rb:
                parent[rb] = ra
                return True
            return False

        edges_sorted = sorted(candidate_edges, key=lambda e: e[2])

        # graph: dict[int, MutableSet[int]] = {i: set() for i in range(len(self.rooms))}
        # mst_edges: list[tuple[int, int]] = []

        for a, b, _ in edges_sorted:
            if union(a, b):
                self.rooms[a].connections.add(b)
                self.rooms[b].connections.add(a)

        EXTRA_CONNECTION_PROB = 0.20

        # for a, b, _ in edges_sorted:
        #     if b in self.rooms[a].connections:
        #         continue  # already in MST
        #
        #     if random.random() < EXTRA_CONNECTION_PROB:
        #         self.rooms[a].connections.add(b)
        #         self.rooms[b].connections.add(a)

    def add_extra_connections(self):
        pass

    def draw_tunnels(self):
        used: MutableSet[int] = set()
        for i, room0 in enumerate(self.rooms):
            for c in room0.connections:
                if c in used:
                    continue
                room1 = self.rooms[c]
                self.draw_tunnel(room0.center, room1.center)
            used.add(i)

    def print(self):
        chars = (
            " ##3456789ABCDEFGHIJKLMNOPQRSTUVWXYabcdefghijklmnopqrstuvwxyz!@#$%&*+=?!"
        )
        c = [" ", "#", "."]

        n = 0
        for y in range(self.height):
            s = "".join([chars[i] for i in self.tiles[n : n + self.width]])
            print(s)
            n += self.width


def print_area(area: Sequence[int], width: int):
    chars = (
        " #ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz!@#$%&*+=?!"
    )
    c = [" ", "#", "."]
    height = len(area) // width

    n = 0
    for y in range(height):
        s = "".join([chars[i] for i in area[n : n + width]])
        print(s)
        n += width


def test_bsp():
    """Test function that generates and prints a BSP tree."""
    random.seed(1)
    map = Map()
    map.draw_tunnels()
    map.print()


if __name__ == "__main__":
    pass
