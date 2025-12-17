from collections.abc import MutableSequence
from dataclasses import dataclass
import random
import time

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


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


HORIZ: int = 1
VERT: int = 2


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

    # Check if this node is large enough to split
    if root.w >= min_size * 2 and root.h >= min_size * 2:
        # Split the node
        node.split()

        # Recursively generate trees for the children
        if node.children:
            left_child, right_child = node.children
            # Check if both children would be valid (not too small)
            if (
                left_child.rect.w >= min_size
                and left_child.rect.h >= min_size
                and right_child.rect.w >= min_size
                and right_child.rect.h >= min_size
            ):
                # Valid split, recursively generate subtrees
                node.children = (
                    generate_tree(left_child.rect, min_size),
                    generate_tree(right_child.rect, min_size),
                )
            else:
                # Split would create invalid children, abandon it
                node.children = None

    return node


def print_bsp(node: Node):
    """Print a BSP tree by drawing rectangles with unique characters for each node."""

    # Get all leaf nodes
    def get_leaves(n: Node, leaves: list[Node]):
        if n.children is None:
            leaves.append(n)
        else:
            get_leaves(n.children[0], leaves)
            get_leaves(n.children[1], leaves)

    leaves: list[Node] = []
    get_leaves(node, leaves)

    # Create a grid
    max_x = node.rect.x + node.rect.w
    max_y = node.rect.y + node.rect.h
    grid = [[" " for _ in range(max_x)] for _ in range(max_y)]

    # Characters to use for different nodes
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz@#$%&*+=?"

    # Draw each leaf node
    for i, leaf in enumerate(leaves):
        char = chars[i % len(chars)]
        r = leaf.rect

        # Fill the rectangle with the character
        for y in range(r.y, r.y + r.h):
            for x in range(r.x, r.x + r.w):
                grid[y][x] = char

        # Draw borders for clarity
        for x in range(r.x, r.x + r.w):
            if r.y > 0:
                grid[r.y][x] = "-"
            if r.y + r.h < max_y:
                grid[r.y + r.h - 1][x] = "-"

        for y in range(r.y, r.y + r.h):
            if r.x > 0:
                grid[y][r.x] = "|"
            if r.x + r.w < max_x:
                grid[y][r.x + r.w - 1] = "|"

    # Print the grid
    for row in grid:
        print("".join(row))


def test_bsp():
    """Test function that generates and prints a BSP tree."""
    random.seed(None)

    root_rect = Rect(0, 0, 120, 50)
    tree = generate_tree(root_rect, min_size=6)

    print_bsp(tree)

    # Count leaves
    def count_leaves(n: Node) -> int:
        if n.children is None:
            return 1
        return count_leaves(n.children[0]) + count_leaves(n.children[1])

    num_leaves = count_leaves(tree)
    print()
    print(f"Generated tree with {num_leaves} leaf nodes")


if __name__ == "__main__":
    test_bsp()
